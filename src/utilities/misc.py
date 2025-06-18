import asyncio
import threading
from contextlib import asynccontextmanager, contextmanager
from copy import deepcopy
from typing import Mapping

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


class UniversalLock:
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

class ReferableDict[KT, VT](Mapping[KT,VT]):
	"""
	A class that mimics a dictionary's key-value storage but keeps
	keys and values in separate, synchronized lists.
	The .values property provides a direct reference to the list of values.
	"""
	__NOT_DEFAULT__ = object()

	def __iter__(self):
		return deepcopy(self.keys)

	def __init__(self, init_dict=None, **kwargs):
		self._lock = UniversalLock()
		init_dict = init_dict or {}
		self._keys: list[KT] = []
		self._values: list[VT] = []

		for k,v in init_dict.items():
			self[k] = v
		for k,v in kwargs.items():
			self[k] = v
		print(self)

	@property
	def values(self)->list[VT]:
		return self._values

	@property
	def keys(self):
		return self._keys

	def __setitem__(self, key: KT, value: VT):
		with self._lock:
			if key in self._keys:
				index = self._keys.index(key)
				self._values[index] = value
			else:
				self._keys.append(key)
				self._values.append(value)

	def __getitem__(self, key: KT):
		"""Handles the access syntax: x = my_mimic[key]"""
		if key in self._keys:
			index = self._keys.index(key)
			return self._values[index]
		else:
			# If key is not found, raise a KeyError, just like a real dict
			raise KeyError(f"Key '{key}' not found.")

	def __len__(self):
		return len(self._keys)

	def __repr__(self):
		if not self._keys:
			return "{}"
		items = [f"'{k}': '{v}'" for k, v in zip(self._keys, self._values)]
		return "{" + ", ".join(items) + "}"

	def pop(self,key: KT, default = __NOT_DEFAULT__):
		with self._lock:
			try:
				index = self._keys.index(key)
				self._keys.pop(index)
				return self._values.pop(index)
			except ValueError:
				if default is self.__NOT_DEFAULT__:
					raise KeyError(f"Invalid key {key} .")
				else:
					return default