import asyncio
import functools
import sys
import threading
from contextlib import asynccontextmanager, contextmanager, ExitStack
from copy import deepcopy
from typing import Mapping, ClassVar, Any, get_origin, get_args, Self, Literal, Iterable
from utilities.logger import logger
from pydantic import (
    BaseModel,
    ConfigDict,
    TypeAdapter,
    model_validator,
    PrivateAttr,
)
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

    async def aacqurie(self, blocking: bool = True, timeout: float = -1):
        return await asyncio.to_thread(self._tlock.acquire, blocking, timeout)

    async def arelease(self):
        return await asyncio.to_thread(self._tlock.release)

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

    def acqurie(self, blocking: bool = True, timeout: float = -1):
        return self._tlock.acquire(blocking, timeout)

    def release(self):
        return self._tlock.release()


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


class SyncListObject[T](BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)

    adapter: ClassVar[TypeAdapter] = None
    """List object adapter. Must provide when define class."""

    object: T
    list_attr: str

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        assert isinstance(cls.adapter, TypeAdapter)

    @property
    def list(self):
        return getattr(self.object, self.list_attr)

    @model_validator(mode="after")
    def _check_list(self) -> Self:
        assert isinstance(getattr(self.object, self.list_attr), list)
        try:
            # noinspection PyTypeHints
            _ = TypeAdapter(list[self.adapter._type],config=ConfigDict(arbitrary_types_allowed=True)).validate_python(self.list)
        except Exception as e:
            logger.warning(e) # for adapter with defer rebuild.
            [self.adapter.validate_python(e) for e in self.list]

        return self


class SyncList(BaseModel):
    """Helper class to sync all lists. Used when others want to trace lists in this class, and these lists must be sync to other lists.
    Support sync object list, given typehint  as tuple[ObjectType, str, TypeAdapter].

    Examples:
            from pydantic import TypeAdapter

            from utilities.misc import SyncList, SyncListObject
            import time

            class A:
                    def __init__(self):
                            self.mylist:list = []

            class SyncListObjectA(SyncListObject):
                    adapter = TypeAdapter(bool)

            start = time.time()
            class MySyncList(SyncList):
                    a: list[int]
                    b: list[str]
                    c: SyncListObjectA[A]

            a = A()
            a.mylist= [True,True,True]

            l  =MySyncList(a = [1,2,3], b = ["abc","xyz","3"], c= SyncListObjectA(object=a, list_attr="mylist"))


            l.append(a=5,b="sss", c=False)
            print(l)

            print(l[0])
            l[0] = dict(a=5,b="new")
            print(l)

            l.insert(3,a=5,b="insert value",c=False)
            print(l)
            print(time.time()-start)

            print(a.mylist)
    """

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_default=True,
        validate_assignment=True,
    )
    adapters: ClassVar[dict[str, TypeAdapter]] = {}

    _lock: UniversalLock = PrivateAttr(default_factory=UniversalLock)

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        fields = cls.model_fields

        default: PydanticUndefinedType | int = None

        def _check_default(v):
            assert isinstance(v, list | PydanticUndefinedType)
            if isinstance(default, PydanticUndefinedType):
                assert v == default
            elif isinstance(default, int):
                assert len(v) == default
            elif default is None:
                default == v if isinstance(v, PydanticUndefinedType) else len(v)
            else:
                raise ValueError(
                    f"All lists must have equal length or be all None as default. Diff: {v} and {default}."
                )

        for name, field in fields.items():
            if issubclass(ann := field.annotation, SyncListObject):
                cls.adapters[name] = ann.adapter
                _check_default(field.default)

            elif get_origin(field.annotation) == list:
                cls.adapters[name] = TypeAdapter(
                    get_args(field.annotation)[0],
                    config=ConfigDict(arbitrary_types_allowed=True, defer_build=True),
                )
                _check_default(field.default)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        ref_l = len(self.get_list(self.list_names[0]))
        for name in self.list_names:
            if (ll := len(self.get_list(name))) != ref_l:
                raise ValueError(
                    f"All lists must have equal length at init. Got {ll} and {ref_l}."
                )

    # Note: Pydantic __getattr__ does not regconisze like __append..., only __append__, but it can be override
    # the predefine method like deepcopy, __index__,...use _append_ to avoid of that.

    def _append_(self, **data):
        data = self.validate_data(data, method="append")
        return {name: self.get_list(name).append(data) for name, data in data.items()}

    def _insert_(self, index: int, **data):
        data = self.validate_data(data, method="insert")
        return {
            name: self.get_list(name).insert(index, data) for name, data in data.items()
        }

    def _extend_(self, **data):
        if not len(data) == len(self.adapters):
            raise ValueError(f"Data for 'extend' method must be given for all lists.")
        ll = len(next(iter(data.values())))
        r_data = {}
        for name, l in data.items():
            assert isinstance(l, list) and len(l) == ll
            r_data[name] = TypeAdapter(
                self.__class__.model_fields[name].annotation
            ).validate_python(l)
        return {name: self.get_list(name).extend(data) for name, data in r_data.items()}

    def _remove_(self, **data):
        return self._pop_(self._index_(**data))

    def _pop_(self, index: int):
        return {name: self.get_list(name).pop(index) for name in self.adapters.keys()}

    def _count_(self, **data):
        assert len(data) == 1
        data = self.validate_data(data, length_included=False)
        k, v = next(iter(data.items()))
        return self.get_list(k).count(v)

    def _clear_(self):
        return [self.get_list(name).clear() for name in self.list_names]

    def _index_(self, *, start=0, stop=sys.maxsize, **data):
        assert len(data) == 1
        data = self.validate_data(data, length_included=False)
        k, v = next(iter(data.items()))
        return self.get_list(k).index(v, start, stop)

    def _sort_(self, key=None, reverse: bool = False):
        return [self.get_list(name).sort(key, reverse) for name in self.list_names]

    def _reverse_(self):
        return [self.get_list(name).reverse() for name in self.adaptelist_names]

    @classmethod
    def validate_data(
        cls, data: dict[str, Any], length_included: bool = True, *, method: str = None
    ):
        if length_included:
            if not len(data) == len(cls.adapters):
                raise ValueError(
                    f"Data for {f"'{method}'" if method else ""} method must equal to number of lists. "
                    f"Got data keys {list(data.keys())} and list keys {list(cls.adapters.keys())}"
                )
        return {
            name: cls.adapters[name].validate_python(data)
            for name, data in data.items()
        }

    @property
    def list_keys(self):
        return self.adapters.keys()

    @property
    def list_names(self):
        return list(self.list_keys)

    def get_list(self, name) -> list[Any]:
        if isinstance(o := getattr(self, name), list):
            return o
        elif isinstance(o, SyncListObject):
            return o.list
        else:
            raise ValueError(f"There is no list name '{name}'.")

    def get_all_lists(
        self, mode: Literal["list", "tuple", "dict"] = "list"
    ) -> list | dict | tuple:
        match mode:
            case "list":
                return [self.get_list(name) for name in self.list_keys]
            case "tuple":
                return (self.get_list(name) for name in self.list_keys)
            case "dict":
                return {name: self.get_list(name) for name in self.list_keys}
        raise ValueError(mode)

    def iter_lists_elements(self, list_names: list[str]):
        lists = [self.get_list(name) for name in list_names]
        for item in zip(*lists):
            yield item

    @property
    def zipped_lists(self):
        lists = [self.get_list(name) for name in self.list_keys]
        return zip(*lists)

    def get_values_by_index(
        self, index: int, lists: Iterable[str] = None, *, _lock: bool = True
    ) -> dict[str, Any]:
        """
        Get all value of given index for all lists
        Args:
                lists: the lists to get value
                index: the index of values to get
                _lock: private, should not set outside this class.
        Returns: dict with keys are list name
        """
        with ExitStack() as stack:
            if _lock:
                stack.enter_context(self._lock)
            keys = lists or self.list_keys
            return {ln: self.get_list(ln)[index] for ln in keys}

    def get_values_by_value(
        self, list_name: str, value: str, lists: Iterable[str] = None
    ):
        """
        Get all values for all lists given the values of one list.
        Args:
                list_name:
                value:
                lists: the lists to get value
        Returns:
        """
        with self._lock:
            keys = lists or self.list_keys
            index = self.get_list(list_name).index(value)
            return self.get_values_by_index(index, keys, _lock=False)

    def call_sync(
        self,
        *method_args,
        method_kwargs: dict[str, Any] = None,
        list_method: str,
        **data,
    ) -> list[Any]:
        method_kwargs = method_kwargs or {}
        with self._lock:
            return getattr(self, "_" + list_method + "_")(
                *method_args, **method_kwargs, **data
            )

    def __getattr__(self, item):
        if callable(getattr(list, item, None)):
            return functools.partial(self.call_sync, list_method=item)
        else:
            return super().__getattr__(item)

    def __getitem__(self, item) -> dict[str, Any]:
        with self._lock:
            return {ln: self.get_list(ln)[item] for ln in self.list_names}

    def __setitem__(self, key, value):
        data = self.validate_data(
            value, length_included=False
        )  # data aren't provided will be hold the old.
        with self._lock:
            for name, v in data.items():
                self.get_list(name)[key] = v

    def __len__(self):
        return len(self.get_list(next(iter(self.list_keys))))

    def __str__(self):
        s = ""
        for k, v in self.get_all_lists(mode="dict").items():
            s += f"{k}={v}\n"
        return s
