import asyncio
import functools
import sys
import threading
from contextlib import asynccontextmanager, contextmanager, ExitStack
from copy import deepcopy
from typing import Mapping, ClassVar, Any, get_origin, Callable, get_args

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from pydantic_core import PydanticUndefinedType
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
        c_str = ", ".join(
            f"{k}='{v}'" if isinstance(v, str) else f"{k}={v}" for k, v in c.items()
        )
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
    async def alock(
        self, blocking: bool = True, timeout: float = -1, raise_when_false: bool = True
    ):
        if flag := await asyncio.to_thread(self._tlock.acquire, blocking, timeout):
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
    def lock(
        self, blocking: bool = True, timeout: float = -1, raise_when_false: bool = True
    ):
        if flag := self._tlock.acquire(blocking, timeout):
            try:
                yield flag
            finally:
                self._tlock.release()
        elif raise_when_false:
            raise TimeoutError(flag)
        else:
            yield flag


class ReferableDict[KT, VT](Mapping[KT, VT]):
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

        for k, v in init_dict.items():
            self[k] = v
        for k, v in kwargs.items():
            self[k] = v
        print(self)

    @property
    def values(self) -> list[VT]:
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

    def pop(self, key: KT, default=__NOT_DEFAULT__):
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


class SyncList(BaseModel):
    """Helper class to sync all lists. Used when others want to trace lists in this class, and these lists must be sync to other lists."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_default=True,
        validate_assignment=True,
    )
    adapters: ClassVar[dict[str, TypeAdapter]] = {}

    lock: UniversalLock = Field(UniversalLock(), exclude=True)

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        fields = cls.model_fields
        fields.pop("lock")

        default = next(iter(fields.values())).default
        for name, field in fields.items():
            if get_origin(field.annotation) == list:
                cls.adapters[name] = TypeAdapter(
                    get_args(field.annotation)[0],
                    config=ConfigDict(arbitrary_types_allowed=True),
                )

                if isinstance(
                    df := field.default, PydanticUndefinedType
                ) and isinstance(default, PydanticUndefinedType):
                    continue
                if isinstance(df, list) and isinstance(default, list):
                    if len(df) == len(default):
                        continue
                raise ValueError(
                    f"All lists must have equal length or be all None as default. Diff: {df} and {default}."
                )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        ref_l = len(getattr(self, self.list_names[0]))
        for name in self.list_names:
            if (ll := len(getattr(self, name))) != ref_l:
                raise ValueError(
                    f"All lists must have equal length at init. Got {ll} and {ref_l}."
                )

    # Note: because __getattr__ of pydantic does not accept method start with "__", so i just start with "_" but still ends with "__"
    # for increase the level of private.

    def _append__(self, **data):
        data = self.validate_data(data, method="append")
        return {name: getattr(self, name).append(data) for name, data in data.items()}

    def _insert__(self, index: int, **data):
        data = self.validate_data(data, method="insert")
        return {
            name: getattr(self, name).insert(index, data) for name, data in data.items()
        }

    def _extend__(self, **data):
        if not len(data) == len(self.adapters):
            raise ValueError(f"Data for 'extend' method must be given for all lists.")
        ll = len(next(iter(data.values())))
        r_data = {}
        for name, l in data.items():
            assert isinstance(l, list) and len(l) == ll
            r_data[name] = TypeAdapter(
                self.__class__.model_fields[name].annotation
            ).validate_python(l)
        return {name: getattr(self, name).extend(data) for name, data in r_data.items()}

    def _remove__(self, **data):
        return self.__pop(self.__index(data))

    def _pop__(self, index: int):
        return {name: getattr(self, name).pop(index) for name in self.adapters.keys()}

    def _copy__(self):
        return deepcopy(self)

    def _count__(self, **data):
        assert len(data) == 1
        data = self.validate_data(data, length_included=False)
        k, v = next(iter(data.items()))
        return getattr(self, k).count(v)

    def _clear__(self):
        return [getattr(self, name).clear() for name in self.list_names]

    def _index__(self, *, start=0, stop=sys.maxsize, **data):
        assert len(data) == 1
        data = self.validate_data(data, length_included=False)
        k, v = next(iter(data.items()))
        return getattr(self, k).index(v, start, stop)

    def _sort__(self, key=None, reverse: bool = False):
        return [getattr(self, name).sort(key, reverse) for name in self.list_names]

    def _reverse__(self):
        return [getattr(self, name).reverse() for name in self.adaptelist_names]

    @classmethod
    def validate_data(
        cls, data: dict[str, Any], length_included: bool = True, *, method: str = None
    ):
        if length_included:
            if not len(data) == len(cls.adapters):
                raise ValueError(
                    f"Data for {f"'{method}'" if method else ""} method must be given for all lists."
                )
        return {
            name: cls.adapters[name].validate_python(data)
            for name, data in data.items()
        }

    @property
    def list_names(self):
        return list(self.adapters.keys())

    def call_sync(
        self,
        *method_args,
        method_kwargs: dict[str, Any] = None,
        list_method: str,
        **data,
    ) -> list[Any]:
        method_kwargs = method_kwargs or {}
        with self.lock:
            return getattr(self, "_" + list_method + "__")(
                *method_args, **method_kwargs, **data
            )

    def __getattr__(self, item):
        if callable(getattr(list, item, None)):
            return functools.partial(self.call_sync, list_method=item)
        else:
            return super().__getattr__(item)

    def __getitem__(self, item) -> tuple[...]:
        with self.lock:
            return tuple(getattr(self, l)[item] for l in self.list_names)

    def __setitem__(self, key, value):
        data = self.validate_data(value)
        with self.lock:
            for name, v in data.items():
                getattr(self, name)[key] = v
