import asyncio
import functools
import os
from contextlib import asynccontextmanager
from inspect import iscoroutinefunction
from typing import Literal, Coroutine, Callable
from uuid import UUID

import anyio
from anyio.streams.memory import MemoryObjectSendStream, MemoryObjectReceiveStream
from fastapi import FastAPI, HTTPException, status
from fastmcp import FastMCP
from loguru import logger
from mcp import types
from pydantic import ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect
from uuid_extensions import uuid7

from utilities.func import get_process_stats

MemObjSS = MemoryObjectSendStream
MemObjRS = MemoryObjectReceiveStream
MCP_APP_SUFFIX = "_mcp_app"
MCP_ENDPOINT_ROUTE_NAME = "mcp_endpoint"


def _async_wrapper(fn) -> Callable[..., Coroutine]:
	if not iscoroutinefunction(fn):
		@functools.wraps(fn)
		async def wrapper(*args, **kwargs):
			return await asyncio.to_thread(fn, *args, **kwargs)

		return wrapper
	else:
		return fn


class MCPServer(FastMCP):
	"""
	Stateless tools executor server, leverage MCP. Intentionally be used to create a scalable tool executor server.

	Notes:
		Tool philosophy : Operation should only be considered as a tool when it's optional for workflow, that means it can
		be called or not. Operations that must be called (such as retrieve chat history) should not be considered as tool.

	Examples:
		from fastapi import FastAPI
		from ray import serve

		def tool1(n: str) -> str:
			return f" Tool 1 receive {n}."

		app = MCPServer(tools=[tool1]).app('/search')

		@serve.deployment(name='mcp_server_app', num_replicas=1)
		@serve.ingress(app)
		class MCPServerApp:
			pass

		if __name__ == '__main__':
			# uvicorn.run(app)
			serve.run(MCPServerApp.bind(),blocking=True)
		"""

	def __init__(self, *args, name: str | None = None, tools: list[types.AnyFunction] | None = None,
	             websocket: WebSocket | None = None, **kwargs):
		"""
		This object should be created one time manually by this method as a factory.
		 Other created should be done by self._create_new_mcp.
		"""
		super().__init__(*args, **kwargs)
		self.__is_factory__ = kwargs.pop('__IS_FACTORY__', True)
		"""Only factory can create app. Other while they are executor, that can do executions."""
		if self.__is_factory__ and name is None:
			raise ValueError('Factory need a name to be used in \'app_name\' property.')
		self._name = name

		self.id: UUID = uuid7()
		# append and remove are thread safe. So don't need to lock.
		self._servers: list[UUID] = []
		self._raw_tools = []  # will be updated by _init_tools() and @tool()
		self._init_tools(tools)

		self._websockets: list[WebSocket] = []
		"""This is websockets record for factory, not the ws for execution."""

		self.read_stream_writer, self.read_stream = anyio.create_memory_object_stream(0)
		self.write_stream, self.write_stream_reader = anyio.create_memory_object_stream(0)

		self.websocket = websocket
		"""This is websocket for execution, can be None for factory"""

		self.pid = os.getpid()
		self._mcp_path: str | None = None
		self._app: FastAPI | None = None

	@property
	def app_name(self) -> str:
		"""Name of factory + MCP_APP_SUFFIX"""
		self.check_factory()
		return self._name + MCP_APP_SUFFIX

	#################################### Factory methods
	def check_factory(self, raise_when_no_factory=True):
		"""
		Args:
			raise_when_no_factory: False mean that raise exception when it's a factory.
		"""
		if raise_when_no_factory:
			if not self.__is_factory__:
				raise Exception("Only Factory can use this method.")
		elif self.__is_factory__:
			raise Exception("Factory cannot use this method.")

	def add_tool(self, fn: types.AnyFunction, name: str | None = None, description: str | None = None,
		tags: set[str] | None = None, ) -> None:
		fn = _async_wrapper(fn)
		self._raw_tools.append(fn)
		super().add_tool(fn, name, description, tags)

	def _init_tools(self, tools: list | None):
		if tools is not None:
			for tool in tools:
				self.add_tool(tool)

	@asynccontextmanager
	async def _create_new_mcp(self, websocket: WebSocket):
		self.check_factory()
		mcp = self.__class__(tools=self._raw_tools, websocket=websocket, __IS_FACTORY__=False)
		try:
			self._servers.append(mcp.id)
			logger.debug(f"\nCreate new MCPServer executor with id: \'{mcp.id}\'.\n"
			             f"Number of MCPServer executor now: {len(self._servers)}.")
			yield mcp
		except Exception as e:
			logger.exception(e)
		finally:
			self._servers.remove(mcp.id)
			logger.debug(f"Delete MCPServer executor with id: \'{mcp.id}\'.\n"
			             f"Number of MCPServer executor now: {len(self._servers)}")

	def app(self, mcp_path: str) -> FastAPI:
		"""
		Create FastAPI app with mcp websocket endpoint at the prefix. Come along with the monitor and get_state endpoints for debug.
		Returns:
			FastAPI app with 3 endpoints.
		"""
		self.check_factory()
		if self._app is not None:
			return self._app
		if not mcp_path.startswith('/'):
			raise ValueError("\'mcp_path\' should start with /.")

		async def mcp_endpoint(websocket: WebSocket):
			try:
				await websocket.accept(subprotocol="mcp")
				self._websockets.append(websocket)

				logger.info(f"MCPServer App \'{self.app_name}\': Websocket endpoint connected.{"=" * 10}")
				async with self._create_new_mcp(websocket) as mcp:
					await mcp._run()

				self._websockets.remove(websocket)
				logger.info(f"MCPServer App \'{self.app_name}\': Websocket endpoint disconnected.{"~" * 10}")
			except Exception as e:
				logger.exception(e)
				raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

		async def states_capture(pid: int | Literal['current']):
			pid = pid if isinstance(pid, int) else None
			ts = [t.get_coro().__qualname__ for t in asyncio.all_tasks()]
			# ts.remove('states_capture')
			svs = [str(uid) for uid in self._servers]
			wss = [ws.__repr__() for ws in self._websockets]
			data = dict(mcp_servers=dict(count=len(svs), list=svs), mcp_websockets=dict(count=len(wss), list=wss),
				tasks=dict(count=len(ts), list=ts), process_stats=get_process_stats(pid), )
			return data

		async def monitor_endpoint(websocket: WebSocket, pid: int | Literal['current']):
			asyncio.current_task().set_name('monitor_endpoint')
			await websocket.accept()
			self._websockets.append(websocket)
			logger.info("Monitor task running - Add 1 tasks in total tasks.\n"
			            "This monitor only use for debug, for 1 replica.\n"
			            "Note that Fastapi itself run 2 tasks, endpoint run 1 task.\n")

			async def receive_text(t: int):
				while True:
					await asyncio.sleep(t)
					await websocket.receive_text()

			async def send_data(t: int):
				while True:
					data = await states_capture(pid)
					data['notes'] = (
						f"Only websockets created by MCP servers is shown. But tasks is contain app tasks of the FastApi app.\n"
						f"This monitor only use for debug, for 1 replica.",)
					await websocket.send_json(data)
					await asyncio.sleep(t)

			tasks = [asyncio.create_task(receive_text(0.001), name='dummy_receive_text'),
			         asyncio.create_task(send_data(0.001), name='send_data_periodically')]

			try:
				done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
				for task in pending:
					task.cancel()
				for task in done:
					if task.exception() is not None:
						raise task.exception()
			except WebSocketDisconnect:
				logger.info("Monitor task stopped")
			finally:
				self._websockets.remove(websocket)

		app = FastAPI()
		app.add_api_websocket_route(mcp_path, mcp_endpoint, name=MCP_ENDPOINT_ROUTE_NAME)
		app.add_api_route('/_states/{pid}', states_capture, name='states_endpoint')
		app.add_api_websocket_route('/_monitor/{pid}', monitor_endpoint, name='monitor_endpoint')

		self._mcp_path = mcp_path
		self._app = app
		logger.info(f"MCPServer Application \'{self.app_name}\' created at PID {os.getpid()}.")
		return self._app

	#################################### Execution methods
	async def _read_websocket(self):
		"""
		- Read value from websocket,
		- Write value to read_stream_writer.send(),
		- MCP server can read value through read_stream.
		"""
		try:
			async with self.read_stream_writer:
				async for msg in self.websocket.iter_text():
					try:
						client_message = types.JSONRPCMessage.model_validate_json(msg)
					except ValidationError as exc:
						await self.read_stream_writer.send(exc)
						continue
					await self.read_stream_writer.send(client_message)
		except anyio.ClosedResourceError:
			logger.debug("_read_websocket except.")
			await self.websocket.close()  # logger.debug(f"_read_socket: ws_state-{self.websocket.application_state}, stream-close-{self.read_stream_writer._closed}")

	async def _write_websocket(self):
		"""
		- MCP Server write value to write_stream.
		- Read that value from write_stream_reader.
		- Write value to websocket.send_text.
		"""
		try:
			async with self.write_stream_reader:
				async for message in self.write_stream_reader:
					obj = message.model_dump_json(by_alias=True, exclude_none=True)
					await self.websocket.send_text(obj)
		except anyio.ClosedResourceError:
			logger.debug("_write_websocket except.")
			await self.websocket.close()  # logger.debug(f"_write_socket: ws_state-{self.websocket.application_state}, stream-close-{self.write_stream_reader._closed}")

	async def _run_server(self):
		await self._mcp_server.run(self.read_stream, self.write_stream,
		                           self._mcp_server.create_initialization_options())

	async def _run(self):
		"""
		Run MCP server and stream handles tasks.
		If one of those is done, cancel all remaining tasks.
		"""
		self.check_factory(raise_when_no_factory=False)

		if self.websocket is None:
			raise AttributeError("This server does not have websocket.")

		logger.debug("Websocket accepted.")

		tasks = [asyncio.create_task(self._read_websocket(), name='read_websocket'),
		         asyncio.create_task(self._write_websocket(), name='write_websocket'),
		         asyncio.create_task(self._run_server(), name='run_server'), ]

		# Cancels all remain a task except debug.
		done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
		for task in done:
			logger.debug(f"Task {task.get_coro().__qualname__} is DONE. Exception={task.exception()}")
		for task in pending:
			task.cancel()
			logger.debug(
				f"Task {task.get_coro().__qualname__} is CANCELED.")  # logger.debug(f"{self.websocket.application_state}")
