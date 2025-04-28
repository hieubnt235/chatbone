import asyncio


class Seller:
	def __init__(self):
		pass

	async def __call__(self, *args, **kwargs):
		for i in range(10):
			yield f"This is {i} from {self.__class__.__name__}\n"
			await asyncio.sleep(0.2)