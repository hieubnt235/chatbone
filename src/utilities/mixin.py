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

	Note: Does not inherit to DeclarativeBase for implement multiple database in the same service.
	So that the Base have to manually do that.
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

