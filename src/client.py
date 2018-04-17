#!/usr/bin/env python
#
# Lara Maia <dev@lara.click> 2015 ~ 2018
#
# The stlib is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation, either version 3 of
# the License, or (at your option) any later version.
#
# The stlib is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see http://www.gnu.org/licenses/.
#

import multiprocessing
import os
from multiprocessing import connection
from types import TracebackType
from typing import Any, Callable, Optional, Type, TypeVar

from stlib import steam_api  # type: ignore

SteamApiExecutorType = TypeVar('SteamApiExecutorType', bound='SteamApiExecutor')
PipeType = connection.Connection


class _CaptureSTD(object):
    def __init__(self) -> None:
        self.old_descriptor = os.dup(1)

    def __enter__(self) -> None:
        new_descriptor = os.open(os.path.devnull, os.O_WRONLY)
        os.dup2(new_descriptor, 2)

    def __exit__(self,
                 exception_type: Optional[Type[BaseException]],
                 exception_value: Optional[Exception],
                 traceback: Optional[TracebackType]) -> None:
        os.dup2(self.old_descriptor, 1)


class SteamGameServer(object):
    def __init__(self, ip: int = 0, steam_port: int = 0, game_port: int = 0) -> None:
        result = steam_api.server_init(ip, steam_port, game_port)

        if result is False:
            raise AttributeError("Unable to initialize SteamGameServer")

    def __enter__(self) -> Any:
        return steam_api.SteamGameServer()

    def __exit__(self,
                 exception_type: Optional[Type[BaseException]],
                 exception_value: Optional[Exception],
                 traceback: Optional[TracebackType]) -> None:
        steam_api.server_shutdown()


class SteamApiExecutor(multiprocessing.Process):
    def __init__(self: SteamApiExecutorType, game_id: int = 480) -> None:
        super().__init__()
        self.game_id = game_id

        self.exit_now = multiprocessing.Event()

        self._init_return, self.__child_init_return = multiprocessing.Pipe(False)
        self._init_exception, self.__child_init_exception = multiprocessing.Pipe(False)

        self.__child_interface, self._interface = multiprocessing.Pipe(False)
        self._interface_return, self.__child_interface_return = multiprocessing.Pipe(False)
        self._interface_exception, self.__child_interface_exception = multiprocessing.Pipe(False)

    def __enter__(self: SteamApiExecutorType) -> SteamApiExecutorType:
        result = self.init()

        if result is False:
            raise AttributeError("Unable to initialize SteamAPI (Invalid game id?)")

        return self

    def __exit__(self: SteamApiExecutorType,
                 exception_type: Optional[Type[BaseException]],
                 exception_value: Optional[Exception],
                 traceback: Optional[TracebackType]) -> None:
        self.shutdown()

    @staticmethod
    def _wait_return(return_pipe: PipeType, exception_pipe: PipeType) -> Any:
        if return_pipe.poll(timeout=5):
            return return_pipe.recv()
        else:
            if exception_pipe.poll():
                raise exception_pipe.recv()
            else:
                raise multiprocessing.TimeoutError("No return from `Process' in SteamAppExecutor")

    def init(self: SteamApiExecutorType) -> Any:
        self.exit_now.clear()
        self.start()

        return self._wait_return(self._init_return, self._init_exception)

    def shutdown(self: SteamApiExecutorType) -> None:
        steam_api.shutdown()
        self.exit_now.set()
        self.join(5)
        self.close()  # type: ignore # https://github.com/python/typeshed/issues/2022

    def call(self: SteamApiExecutorType, method: Callable[..., Any]) -> Any:
        self._interface.send(method)

        return self._wait_return(self._interface_return, self._interface_exception)

    def run(self: SteamApiExecutorType) -> None:
        os.environ["SteamAppId"] = str(self.game_id)

        try:
            with _CaptureSTD():
                result = steam_api.init()
        except Exception as exception:
            self.__child_init_exception.send(exception)
            return None
        else:
            self.__child_init_return.send(result)

        while not self.exit_now.is_set():
            if self.__child_interface.poll():
                interface_class = self.__child_interface.recv()
                try:
                    result = interface_class()
                except Exception as exception:
                    self.__child_interface_exception.send(exception)
                    return None
                else:
                    self.__child_interface_return.send(result)