import asyncio
import threading
from contextlib import asynccontextmanager, contextmanager

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession


class RepoMixin:

	def __init__(self, session: AsyncSession):
		self._session = session

	async def flush(self):
		await self._session.flush()

	async def refresh(self, obj):
		await self._session.refresh(obj)


class ModelMixin:
	"""
	Universal properties for all models, such at print format.

	Note: Does not inherit to DeclarativeBase for implement multiple databases in the same service.
	So that the Base has to manually do that.
	"""

	def __repr__(self):
		mapper = inspect(self.__class__)
		c = {c.key: getattr(self, c.key) for c in mapper.column_attrs}
		c_str = ", ".join(f"{k}=\'{v}\'" if isinstance(v, str) else f"{k}={v}" for k, v in c.items())
		return f"{self.__class__.__name__}({c_str})"

	def as_dict(self) -> dict[str, str]:
		mapper = inspect(self.__class__)
		c = {c.key: getattr(self, c.key) for c in mapper.column_attrs}
		return c


class LockContextManager:
	def __init__(self):
		self._tlock = threading.Lock()

	async def __aenter__(self):
		return await asyncio.to_thread(self._tlock.acquire)

	async def __aexit__(self, exc_type, exc_val, exc_tb):
		await asyncio.to_thread(self._tlock.release)

	@asynccontextmanager
	async def alock(self,blocking:bool=True,timeout:float=-1, raise_when_false: bool=True):
		if flag:= await asyncio.to_thread(self._tlock.acquire,blocking,timeout):
			try:
				yield flag
			finally:
				await asyncio.to_thread(self._tlock.release)
		elif raise_when_false:
			raise TimeoutError(flag)
		else:
			yield flag

	def __enter__(self):
		self._tlock.acquire()

	def __exit__(self, exc_type, exc_val, exc_tb):
		self._tlock.release()

	@contextmanager
	def lock(self,blocking:bool=True,timeout:float=-1, raise_when_false: bool=True):
		if flag:= self._tlock.acquire(blocking,timeout):
			try:
				yield flag
			finally:
				self._tlock.release()
		elif raise_when_false:
			raise TimeoutError(flag)
		else:
			yield flag
