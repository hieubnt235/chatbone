key = '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'
import asyncio
import os

from langchain_tavily import TavilySearch

os.environ['TAVILY_API_KEY'] = key
tool = TavilySearch(max_results=5)

done = False


async def echo():
	global done
	t = 0
	while not done:
		print(f'running {t}')
		t += 1
		await asyncio.sleep(1)


async def invoke():
	global done
	r = await tool.ainvoke(dict(query='hunter x hunter', include_images=True))
	print(f"Done")
	done = True
	return r


async def main():
	e = asyncio.create_task(echo(), name='echo')
	i = asyncio.create_task(invoke(), name='invoke')

	r = await asyncio.gather(e, i)
	print(r[1])


from viztracer import VizTracer

with VizTracer(log_async=True):
	print('running')
	asyncio.run(invoke(), debug=True)
