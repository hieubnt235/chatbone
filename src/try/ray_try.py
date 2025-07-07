import asyncio
import time

import ray
from ray.exceptions import RayTaskError

@ray.remote
class Actor:
	async def f(self):
		try:
			await asyncio.sleep(5)
		except asyncio.CancelledError:
			print("Enter cancelled")
			for i in range(5):
				print(i)
				await asyncio.sleep(1)
			print("Actor task canceled.")


actor = Actor.remote()
ref = actor.f.remote()

time.sleep(1)
ray.cancel(ref)


async def main():
	try:
		await ref
	except RayTaskError as e:
		print("Object reference was cancelled.")

asyncio.run(main())
