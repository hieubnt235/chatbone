import asyncio

from chatbone.settings import REDIS

async def main():
	print(REDIS.connection_pool.connection_kwargs.get("protocol"))
	print(await REDIS.xread({"ssccs":"0"},block=5000,count=3))

asyncio.run(main())
