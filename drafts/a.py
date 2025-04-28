import asyncio


class A:

	async def __aenter__(self):
		return self

	async def __aexit__(self, exc_type, exc_val, exc_tb):
		print("exited")

async def main():
	async with A() as a:
		raise Exception("fake raise")


asyncio.run(main())