__all__ = ["ToolsClient"]

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Sequence, AsyncContextManager
from urllib.parse import urlparse

import aiohttp
from fastmcp import Client
from fastmcp.client import WSTransport
from langchain_core.tools import StructuredTool
from langchain_mcp_adapters.tools import load_mcp_tools

from utilities.logger import logger

MCP_APP_SUFFIX = "_mcp_app"


def _str2ws_transport(tp: dict[str, str | WSTransport]):
	for k, t in tp.items():
		tp[k] = t if isinstance(t, WSTransport) else WSTransport(t)


class ToolsClient:
	"""
	Persist connections to MCPServers to get langchain Tools. Tools can be called later with ainvoke.

	Examples:
		# RUN DUMMY APP FIRST

		client = ToolsClient(base_tools_app_url='http://127.0.0.1:8000')

		async def test_one_client_multiple_tools(tools: StructuredTool, n:int = 9):
				t = convert_to_openai_tool(tools[0])
				print(json.dumps(t,indent=2))
				start = time.time()
				tasks=([asyncio.create_task(tools[0].ainvoke({'name': 'HunterxHunter release date', 'repeat': 3})) for _ in range(n)]
				+[asyncio.create_task(tools[1].ainvoke({'name': 'HunterxHunter release date', 'repeat': 3})) for _ in range(n)])

				while True:
					done,pending  = await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
					for t in done:
						logger.debug(t.result())
						tasks.remove(t)
					if not pending:
						break
				logger.info(f"One client, {n} tasks: {time.time() - start}")

		async def test_multiple_client(c:int=3,n:int=3):
			start = time.time()
			async with AsyncExitStack() as stack:
				clients = [await stack.enter_async_context(client.get_tools(client.mcp_apps))  for _ in range(c) ]
				await asyncio.gather(*[test_one_client_multiple_tools(cli,n) for cli in clients])

			logger.info(f"{c} clients, {n} tasks per client: {time.time()-start}")

		async def main():
			try:
				logger.info(client.mcp_apps)

				# Test one client with multiple calls.
				async with client.get_tools( client.mcp_apps ) as tools:
					await test_one_client_multiple_tools(tools)

				await test_multiple_client()
				# Multi clients test is little faster
			except Exception as e:
				logger.exception(e)

		asyncio.run(main())
	"""

	def __init__(self, *, ws_urls_or_transports: dict[str, str | WSTransport] | None = None,
	             base_tools_app_url: str | None = None):
		"""
		Args:
			ws_urls_or_transports: urls or transports for multiple tools servers. Keys of dict are mcp app name.
			base_tools_app_url: If this url is provided, call to /list_mcp_apps endpoint and retrieve all mcp app.
			 See tools.app.tools_app for details. Note that this url is http, not ws.
		"""

		# Init transports ##########################
		if ws_urls_or_transports is None and base_tools_app_url is None:
			raise ValueError('Urls or transports must be provided.')

		self._transports: dict[str, WSTransport] = {}
		"""Keys are app names, values are transports."""

		if ws_urls_or_transports is not None:
			assert [isinstance(t, str) or isinstance(t, WSTransport) for t in ws_urls_or_transports.values()]
			_str2ws_transport(ws_urls_or_transports)
			self._transports.update(ws_urls_or_transports)

		if base_tools_app_url is not None:
			asyncio.run(self._create_transports_from_tools_app(base_tools_app_url))
		############################################

		self._servername2clients: dict[str, Client] = {}
		"""app server name:connected client"""
		self._aestack = AsyncExitStack()
		self._servername2tools: dict[str, list[StructuredTool] | Exception] = {}

	async def _create_transports_from_tools_app(self, base_tools_app_url: str) -> list[WSTransport]:
		base_tools_app_url = base_tools_app_url.removesuffix('/')
		url = urlparse(base_tools_app_url)
		async with aiohttp.ClientSession() as session:
			async with session.get(url.geturl() + '/list_mcp_apps', raise_for_status=True) as response:
				result = await response.json()
				for name, path in result.items():
					assert isinstance(path, str)
					result[name] = path.format(host_and_port_or_domain=url.netloc)
				_str2ws_transport(result)
				self._transports.update(result)

	@property
	def mcp_apps(self) -> list[str]:
		return list(self._transports.keys())

	async def _connect_clients(self, mcp_apps: list[str] | str | None) -> Client:
		if mcp_apps is None:
			mcp_apps = self.mcp_apps
		else:
			if not isinstance(mcp_apps, Sequence):
				mcp_apps = [mcp_apps]
			for app in mcp_apps:
				if app not in self.mcp_apps:
					raise ValueError(f"Does not have mcp app name \'{app}\'.")
		for app_name in mcp_apps:
			self._servername2clients[app_name] = await self._aestack.enter_async_context(
				Client(self._transports[app_name]))

	@asynccontextmanager
	async def get_tools(self, mcp_apps: list[str] | str | None, *, timeout: float | None = 30.0,
	                    stop_when_one_fail: bool = False, raise_exception: bool = False, ) -> AsyncContextManager[
		list[StructuredTool]]:
		"""
		Enter and get langchain tool. Default setup is yielding all available tools gotten before timeout.
		Args:
			mcp_apps: list of mcp server app name.
			stop_when_one_fail: If True, stop query when one server fail, return tools that already gotten.
			timeout: if timeout is reached, return tools that already gotten.
			raise_exception: If True, raise exception when timeout, first exception,... else return tools that already gotten.
		Returns:
		"""
		try:
			await self._connect_clients(mcp_apps)

			tasks = [asyncio.create_task(load_mcp_tools(c.session), name=name) for name, c in
			         self._servername2clients.items()]
			if stop_when_one_fail:
				done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION, timeout=timeout)
			else:
				done, pending = await asyncio.wait(tasks, return_when=asyncio.ALL_COMPLETED, timeout=timeout)

			for task in done:
				if task.exception() is not None:
					if raise_exception:
						raise task.exception()
				else:
					self._servername2tools[task.get_name()] = task.result()
			for task in pending:
				task.cancel()
				logger.debug(f"Haven't got tools from {task.get_name}.")

			# Change tool name become appname_toolname (ex: math_add)
			ret_tools: list[StructuredTool] = []
			for name, tools in self._servername2tools.items():
				for tool in tools:
					tool.name = name.removesuffix(MCP_APP_SUFFIX) + '__' + tool.name
				ret_tools.extend(tools)
			yield ret_tools

		except Exception as e:
			raise e
		finally:
			await self.clean()

	async def clean(self):
		self._servername2clients = {}
		self._servername2tools = {}
		await self._aestack.aclose()
		logger.debug("Client is cleaned.")
