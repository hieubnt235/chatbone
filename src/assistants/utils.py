import asyncio

from concurrent.futures import ThreadPoolExecutor

from langchain_core.messages import AnyMessage


async def messages2contents(messages: list[AnyMessage]) -> list[str]:
	def helper(messages: list[AnyMessage]) -> list[str]:
		r = []
		for m in messages:
			if isinstance(m.content, str):
				r.append(m)
			else:
				r.extend(m.content)
		return r

	with ThreadPoolExecutor() as pool:
		return await  asyncio.get_running_loop().run_in_executor(pool, helper, messages)


async def cluster_messages(clusters: list[list[int]], messages: list[AnyMessage]) -> list[list[AnyMessage]]:
	def helper(clusters, messages):
		result = []
		for c in clusters:
			result.append([messages[i] for i in c])
		return result
	with ThreadPoolExecutor() as pool:
		return await asyncio.get_running_loop().run_in_executor(pool, helper, clusters, messages)


async def compose_messages(contents: list[str], f: str)->str:
	def helper(contents: list[str], f: str)->str:
		return f.format("\n".join(contents))
	with ThreadPoolExecutor() as pool:
		return await asyncio.get_running_loop().run_in_executor(pool, helper, contents,f)
