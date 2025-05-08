import asyncio
import json
import time
from contextlib import AsyncExitStack

from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_tavily.tavily_search import TavilySearchInput

from utilities.logger import logger
from utilities.settings.clients.tools.client import ToolsClient

client = ToolsClient(base_tools_app_url='http://127.0.0.1:8000')

search_input = TavilySearchInput(query='Who is Ho CHi Minh?', search_depth='advanced')


async def test_one_client_multiple_tools(tools: StructuredTool, n: int = 9):
	#
	start = time.time()
	tasks = [asyncio.create_task(tools[0].ainvoke(dict(search_input=search_input))) for _ in range(n)]

	while True:
		done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
		for t in done:
			logger.debug(f"\n{t.result()}")
			tasks.remove(t)
		if not pending:
			break
	logger.info(f"One client, {n} tasks: {time.time() - start}")


async def test_multiple_client(c: int = 3, n: int = 3):
	start = time.time()
	async with AsyncExitStack() as stack:
		tools = [await stack.enter_async_context(client.get_tools(client.mcp_apps)) for _ in range(c)]
		await asyncio.gather(*[test_one_client_multiple_tools(cli, n) for cli in tools])

	logger.info(f"{c} clients, {n} tasks per client: {time.time() - start}")


async def main():
	# try:
	logger.info(client.mcp_apps)

	# Test one client with multiple calls.
	async with client.get_tools(client.mcp_apps) as tools:
		t = convert_to_openai_tool(tools[0])
		print(json.dumps(t, indent=2))
		await test_one_client_multiple_tools(tools)

	await test_multiple_client()


# Multi clients test is little faster
# except Exception as e:
# 	logger.exception(e)

asyncio.run(main())
