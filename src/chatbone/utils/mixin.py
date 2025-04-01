from abc import ABC, abstractmethod

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession


class RepoMixin(ABC):
    exception_type= Exception

    def __init__(self,session: AsyncSession):
        self._session=session

    @abstractmethod
    async def flush(self):
        pass

    @abstractmethod
    async def refresh(self,obj):
        pass

class ModelMixin:
    """
    Universal properties for all models, such at print format.
    """
    def __repr__(self):
        mapper = inspect(self.__class__)
        c = {c.key: getattr(self, c.key) for c in mapper.column_attrs}
        c_str = ", ".join(f"{k}=\'{v}\'" if isinstance(v, str) else f"{k}={v}" for k, v in c.items())
        return f"{self.__class__.__name__}({c_str})"

    def as_dict(self)->dict[str,str]:
        mapper = inspect(self.__class__)
        c = {c.key: getattr(self, c.key) for c in mapper.column_attrs}
        return c