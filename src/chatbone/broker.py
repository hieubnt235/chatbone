__all__ = ["UserData", "ChatSessionData"]
import asyncio
import json
from abc import ABC
from contextlib import asynccontextmanager, AbstractAsyncContextManager, AsyncExitStack
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from inspect import iscoroutine
from typing import (Literal, Self, Awaitable, Any, Sequence, ClassVar, get_origin, get_args, AsyncIterator, )
from uuid import UUID

from cloudpickle import cloudpickle
from pydantic import Field, PrivateAttr, BaseModel, ConfigDict
from redis import WatchError
from redis.asyncio import Redis
from redis.asyncio.client import Pipeline
from redis.exceptions import LockError
from redis.typing import FieldT, EncodableT

from chatbone.settings import REDIS, CONFIG, get_redis
from utilities.func import encrypt, decrypt, dump_base_models
from utilities.logger import logger

LOCK_POSTFIX = "<LOCK>"
NULL = "null"


# noinspection PyTypeChecker
class ChatboneData(BaseModel, ABC):
    """This class for data work with Redis.
    All Redis keys are very important for cascade deleting or expiring, they must:

        1. Be defined as property, method name ends with '_rkey' and returns string. See the 'all_rkeys' method.
        2. Have its own id, so that each instance has separate rkey.
        3. All keys need to be static (constant, or bound with the top level key (with id)), dynamic case should raise when not available.
        4. Ensure all rkey always exist at the time of expiring or deleting.


    Notes:
            1. Data is got through attributes of this class, require refresh manually to get updated data.
            2. Only support modify first level attributes. Nested attributes are not allowed to modify, they must be modified using the submodel.
                    So that if there are any modifiable values, it needs to wrap with BaseModel subclass.
            3. Model does not own a redis key must be set embedding = True (default), if not, it cannot modify data, or unbehavior things would happen.
    """

    # This value is True by default for accidentally create new key in the server because of using an embedding model without set it to True.
    embedding: ClassVar[bool] = True
    """Embedding class will not persist and manage any redis key/object."""
    redis: ClassVar[Redis] = REDIS
    model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)

    id: UUID

    _bounded: bool = PrivateAttr(False)

    _jsonpath: str = PrivateAttr("")
    """This path will be used to refresh. Embedding model must be reset this value by model own redis key."""
    _base_rkey: str | None = PrivateAttr(None)
    """This attribute is used by embedding Model, and created by the model hold redis key."""
    _refresh_include_default: set[str] = PrivateAttr(default_factory=set)

    async def refresh(
        self, exclude: set[str] | None = None, include: set[str] | None = None
    ) -> Self:
        """Refresh fields. If both 'exclude' and 'include' are None, refresh the default,
        typically information for resolving dynamic redis keys.

        This method should be called when ever create a new object and access to rkey (delete, expire, ...) without do save.
        'Save' method calls refresh itself.

        Args:
                exclude: Refresh field includes all available fields that not this set. Set this blank set to refresh all.
                include: Refresh field includes all available fields that in this set.

        Returns:
                New refreshed object of this class.
        """

        def resolve_fields(
            exclude: set[str] | None, include: set[str] | None
        ) -> set[str]:
            if include is not None and exclude is not None:
                raise ValueError(
                    "Cannot set both exclude and include argument at the same time."
                )
            if exclude is not None:
                fields = {
                    field for field in self.model_fields.keys() if field not in exclude
                }
            elif include is not None:
                fields = {
                    field for field in self.model_fields.keys() if field in include
                }
            else:
                fields = deepcopy(self._refresh_include_default)
            return fields

        fields: set[str] = await asyncio.to_thread(resolve_fields, exclude, include)
        if len(fields) == 0:
            return self

        r = await self.redis.json().get(
            self.rkey, *[f"{self._jsonpath}.{field}" for field in fields]
        )
        # There are two scenarios make r is None are rkey not found, or value is null when get only one path.
        if r is None:
            if not await self.redis.exists(self.rkey):
                raise KeyError("User data doesn't exist. Call 'save' first.")
            r = NULL
        if len(fields) == 1:
            r = {fields.pop(): r}
        else:
            r = {k[1:]: v for k, v in r.items()}
        assert isinstance(r, dict)

        logger.debug(f"Update attributes with dict:\n {json.dumps(r, indent=4)}")
        obj_dict = self.model_dump()
        obj_dict.update(r)  # Note: swallow update is intentional.
        new_object = self.__class__.model_validate(obj_dict)

        if self.embedding:
            new_object.bind_rkey_and_json_path(self.rkey, self._jsonpath)
        return new_object

    @classmethod
    def _rkey_prefix(cls):
        return f"{cls.__module__}:{cls.__name__}"

    @property
    def rkey_prefix(self):
        return self._rkey_prefix()

    @property
    def rkey(self) -> str:
        """Main rkey. The embedding class must redefine this class to"""
        if self.embedding:
            if self._base_rkey is None:
                raise ValueError("This embedding object haven't bound any base rkey.")
            else:
                return self._base_rkey
        return f"{self.rkey_prefix}:{self.id}"

    def bind_rkey_and_json_path(self, rkey: str, jsonpath: str):
        if not self.embedding:
            raise Exception("Can not bind the instance not belong to embedded class.")
        if not jsonpath.startswith("."):
            raise ValueError("Json path must start with '.' .")
        self._base_rkey = rkey
        self._jsonpath = jsonpath
        self._bounded = True

    def get_all_sub_rkeys(self) -> list[str]:
        """Get sub rkeys, which is the property method with name end with '_rkey' and return string.
        Notes:
                This attribute will block cpu.
        """
        rkeys: list[str] = []
        fields = self.model_fields

        for name in dir(self):
            if name.startswith("__") or name in [
                "rkey",
                "all_sub_rkeys",
                "get_all_sub_rkeys",
                "is_bounded",
            ]:
                continue

            f = fields.get(name)
            if (
                not isinstance(getattr(self.__class__, name, None), property)
                and f is None
            ):
                # if not a property or a field
                continue

            attr = getattr(self, name)

            # Field case: Field exist, and a field value type must be ChatboneData,
            # list[ChatBoneData], Tuple[ChatBoneData,...] and dict[Any, ChatBoneData]
            if isinstance(attr, (ChatboneData, list, dict, tuple)) and f is not None:
                org = get_origin(f.annotation)

                if org is None:
                    # Not any container or implicit container typehint case. We have to detect that because when implicit,
                    # We do not know what exactly it stores, can be ChatboneData or not. Missing will lead to leak redis keys.
                    try:
                        assert isinstance(attr, ChatboneData)
                    except AssertionError:
                        raise SyntaxError(
                            f"Type hint of all container in pydantic model must be explicit. "
                            f"Ex: list[str], dict[str,str] not list or dict."
                            f" Got {f.annotation}."
                        )
                    rkeys.extend(attr.get_all_sub_rkeys())

                elif issubclass(org, list) and issubclass(
                    get_args(f.annotation)[0], ChatboneData
                ):
                    assert isinstance(attr, list)
                    for cbd in attr:
                        assert isinstance(cbd, ChatboneData)
                        rkeys.extend(cbd.get_all_sub_rkeys())
                elif issubclass(org, tuple):
                    assert isinstance(attr, tuple)
                    try:
                        cbd: ChatboneData = attr[attr.index(ChatboneData)]
                        rkeys.extend(cbd.get_all_sub_rkeys())
                    except ValueError:
                        continue
                elif issubclass(org, dict):
                    assert isinstance(attr, dict)
                    for cbd in attr.values():
                        assert isinstance(cbd, ChatboneData)
                        rkeys.extend(cbd.get_all_sub_rkeys())

            # Property case exists only name is not in field case.
            elif (iscoroutine(attr) or callable(attr)) or (not name.endswith("_rkey")):
                # Filter properties or field.
                continue
            elif attr is None or attr == NULL:
                continue  # see Userdata.encrypted_secret_rkey for example of this case

            else:
                try:
                    assert isinstance(attr, str)
                    rkeys.append(attr)
                except AssertionError:
                    raise SyntaxError(
                        f"rkey property method {name} must return value type string, got {type(attr)}"
                    )

        return rkeys

    @property
    def is_bounded(self) -> bool:
        if not self.embedding:
            raise ValueError("Non-embedding-model cannot access to this property.")
        return self._bounded

    @property
    async def all_sub_rkeys(self) -> list[str]:
        return await asyncio.to_thread(self.get_all_sub_rkeys)

    async def expire(
        self, num_seconds: int | timedelta, redis_or_pipeline: Redis | None = None
    ):
        """Expire all keys of this object. Note that this method doesn't watch for existing of keys during expiring.
        Args:
                num_seconds:
                redis_or_pipeline:
        """
        if self.embedding:
            raise ValueError("Embedding model cannot do this operation .")
        async with self._get_transaction_pipeline(redis_or_pipeline) as pipeline:
            await self.expire_cascade(
                num_seconds, (await self.all_sub_rkeys) + [self.rkey], pipeline
            )

    async def expire_sync(
        self, keys: list[str], redis_or_pipeline: Redis | None = None
    ) -> None:
        """Expire all Models sync with this object's main rkey lifetime (with 'rkey' key)."""
        async with self._get_transaction_pipeline(redis_or_pipeline) as pipeline:
            num_seconds = await self.redis.ttl(self.rkey)
            keys = deepcopy(keys)
            keys.append(self.rkey)
            await self.expire_cascade(num_seconds, keys, pipeline)

    async def expire_cascade(
        self,
        num_seconds: int | timedelta,
        keys: list[str],
        redis_or_pipeline: Redis | None = None,
    ):
        """Expire all keys with the same num_seconds. Negative value means persist (Note that in raw redis, negative means delete).
        This is not use any attributes of an object (self...), but not a class method to limit the usage outside.
        """
        assert isinstance(num_seconds, (float, int))
        async with self._get_transaction_pipeline(redis_or_pipeline) as pipeline:
            if num_seconds > 0:
                for k in keys:
                    await pipeline.expire(k, num_seconds)
            else:
                for k in keys:
                    await pipeline.persist(k)

    async def save(
        self, expire_seconds: int | None = None, refresh: bool = True
    ) -> bool | None | Self:
        """Save data with self.rkey. Skip if existed. If you want to save a new one, 'delete' first.
        Args:
                expire_seconds: None means do nothing. Negative means persist.
                refresh: Whether to refresh or not.
        Returns:
                True if a refreshed object.
        """
        if self.embedding:
            raise ValueError("Embedding model cannot do this operation .")
        _ = await self.redis.json().set(
            self.rkey, ".", self.model_dump(mode="json"), nx=True
        )
        obj = (await self.refresh()) if refresh else self
        if expire_seconds is not None:
            await obj.expire(expire_seconds)
        logger.info(f"Saved userdata: {repr(obj)}")
        return obj

    async def delete(self) -> int:
        """Cascading delete for all redis keys. Note again that this method deletes all redis keys, not the JSON keys.
        Returns:
                Number of keys were removed.
        """
        if self.embedding:
            raise ValueError("Embedding model cannot do this operation .")
        return await self.redis.delete(self.rkey, *(await self.all_sub_rkeys))

    async def append(
        self, field: str, values: list[Any], redis_or_pipeline: Redis | None = None
    ):
        """Append to a JSON list.
        Args:
                field: field name of a pydantic model.
                values: list of values that intent to be appended.
                redis_or_pipeline:
        Returns:
                If JSON list exists, return len of the entire list.
                If the pipeline is given, return None.
        """
        await asyncio.to_thread(self._check_list_params, field, values)
        if len(values) == 0:
            logger.info(f"Skip append with no value.")
            return
        data = await asyncio.to_thread(dump_base_models, values, "json")
        async with self._get_transaction_pipeline(
            redis_or_pipeline, execute=False
        ) as pipeline:
            coro: Awaitable[list[int | None]] = pipeline.json().arrappend(
                self.rkey,
                f"{self._jsonpath}.{field}",
                **data,
            )
            await coro
            if not redis_or_pipeline:
                return (await pipeline.execute())[0]
        return None

    async def trim(
        self, field: str, start: int, stop: int, redis_or_pipeline: Redis | None = None
    ) -> int:
        """
        Keep the range of value
        Args:
                field:
                start:
                stop:
                redis_or_pipeline:

        Returns:
                Number of values remain.
        """
        await asyncio.to_thread(self._check_list_params, field)
        async with self._get_transaction_pipeline(
            redis_or_pipeline, execute=False
        ) as pipeline:
            coro: Awaitable[list[int | None]] = pipeline.json().arrtrim(
                self.rkey, f"{self._jsonpath}.{field}", start, stop
            )
            await coro
            if not redis_or_pipeline:
                return (await pipeline.execute())[0]
        return None

    async def update(
        self, field: str, values: dict[Any, Any], redis_or_pipeline: Redis | None = None
    ):
        """Update the dict with keys and values.
        Args:
                field: typehint of field must be a dict[Any,Any]
                values: must be type dict that match the field.
                redis_or_pipeline:
        Returns:
        """
        await asyncio.to_thread(self._check_dict_params, field, values)
        async with self._get_transaction_pipeline(redis_or_pipeline) as pipeline:
            coros: list[Awaitable[list[int | None]]] = []
            for k, v in values.items():
                if isinstance(v,BaseModel):
                    v=v.model_dump(mode="json")
                coros.append(
                    pipeline.json().set(self.rkey, f"{self._jsonpath}.{field}.{k}", v)
                )
            return await asyncio.gather(*coros)

    async def set(self, field: str, value: Any, redis_or_pipeline: Redis | None = None):
        """Override the attributes to entirely new one.
        Args:
                field:
                value:
                redis_or_pipeline:
        Returns:
        """
        await asyncio.to_thread(self._check_params, field, value)
        async with self._get_transaction_pipeline(redis_or_pipeline) as pipeline:
            if isinstance(value, BaseModel):
                value = value.model_dump(mode="json")
            coro: Awaitable[list[int | None]] = pipeline.json().set(
                self.rkey, f"{self._jsonpath}.{field}", value
            )
            return await coro

    async def clear(
        self, field: str, value: Any, redis_or_pipeline: Redis | None = None
    ):
        """Clear container values (arrays/objects) and set numeric values to 0"""
        await asyncio.to_thread(self._check_params, field, value)
        async with self._get_transaction_pipeline(redis_or_pipeline) as pipeline:
            coro: Awaitable[list[int | None]] = pipeline.json().clear(
                self.rkey, f"{self._jsonpath}.{field}"
            )
            return await coro

    def _check_params(self, field: str, value: Any):
        assert field not in ["id", "redis", "_jsonpath"]
        ann = self.model_fields[field].annotation
        org = get_origin(ann)
        if org is None:
            if not isinstance(value, ann):
                raise ValueError(
                    f"Field '{field}' type is '{ann}' but input value is '{type(value)}'."
                )
            return
        if issubclass(org, Sequence):
            self._check_list_params(field, value)
        if issubclass(org, dict):
            self._check_dict_params(field, value)
        raise ValueError(f"Type {value} is not supported.")

    def _check_dict_params(self, field: str, values: dict):
        ann = self.model_fields[field].annotation
        org = get_origin(ann)
        kt, vt = get_args(ann)
        if not issubclass(org, dict):
            raise ValueError(f"The field must be a dict. Got {get_origin(ann)}.")
        for k, v in values.items():
            if not isinstance(k, kt) or not isinstance(v, vt):
                raise ValueError(f"KeyType must be {kt} and ValueType must be {vt}.")

    def _check_list_params(self, field: str, values: list[Any] | None = None):
        ann = self.model_fields[field].annotation
        if not issubclass(get_origin(ann), Sequence):
            raise ValueError(f"The field must be a Sequence. Got {get_origin(ann)} .")
        if values is not None:
            for v in values:
                if not isinstance(v, get_args(ann)[0]):
                    raise ValueError(
                        f"Value to append in this field must be type {get_args(ann)[0]}. Got {type(values)} ."
                    )

    @asynccontextmanager
    async def _lock_modify(
        self, key: str, timeout: int | None = None, blocking_timeout: int | None = None
    ):
        timeout = timeout or CONFIG.redis_lock_timeout
        blocking_timeout = blocking_timeout or CONFIG.redis_acquire_lock_timeout
        async with self.redis.lock(
            key, timeout=timeout, blocking_timeout=blocking_timeout
        ) as lock:
            yield lock

    @asynccontextmanager
    async def _get_transaction_pipeline(
        self,
        redis_or_pipeline: Redis | None = None,
        *,
        lock_modify: str | Literal["rkey"] | None = None,
        execute: bool = True,
    ) -> AbstractAsyncContextManager[Pipeline]:
        """
        Get the transaction pipeline while providing options to ensure that a key exists during executing the pipe.
        Args:
                redis_or_pipeline: Can be Redis, Pipeline or None:
                        - If it's None, a new transaction pipeline will be created with Meta.database yield and executed at the last.
                        - If it's a Redis instance, the same as 'None case' but using passed Redis instead of Meta.database.
                        - If it's a Pipeline instance, there must be a transaction Pipeline.
        Returns:
                Async contextmanager of transaction Pipeline instance.
        Raises:
                KeyError: Redis key doesn't exist.

        """
        if isinstance(redis_or_pipeline, Pipeline):
            assert (
                redis_or_pipeline.is_transaction
                or redis_or_pipeline.explicit_transaction
            )
            yield redis_or_pipeline  # No execute
        else:
            redis_or_pipeline = redis_or_pipeline or self.redis
            async with AsyncExitStack() as stack:
                if lock_modify is not None:
                    lock_modify = (
                        f"{self.rkey}:{LOCK_POSTFIX}"
                        if lock_modify == "rkey"
                        else lock_modify
                    )
                    await stack.enter_async_context(self._lock_modify(lock_modify))
                pipeline: Pipeline = await stack.enter_async_context(
                    redis_or_pipeline.pipeline(transaction=True)
                )
                yield pipeline
                if execute:
                    await pipeline.execute()

# Stream Data

EncodedStreamData = dict[FieldT, EncodableT]

class StreamData(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _encode(self) -> EncodedStreamData:
        return {f"{StreamData}": cloudpickle.dumps(self)}

    @classmethod
    def _decode(cls, data: EncodedStreamData) -> Self:
        data = cloudpickle.loads(data[f"{cls}".encode()])
        assert isinstance(data, StreamData)
        return data

    async def encode(self) -> EncodedStreamData:
        return await asyncio.to_thread(self._encode)

    @classmethod
    async def decode(cls, data: EncodedStreamData) -> Self:
        return await asyncio.to_thread(cls._decode, data)


class Stream:

    def __init__(self, stream_key: str):
        self.key = stream_key

    @classmethod
    async def _create(cls, stream_key: str) -> Self:
        assert await get_redis().exists(stream_key)
        return cls(stream_key)


class WriteStream(Stream):

    async def write(
        self,
        data: StreamData,
        maxlen: int | None = None,
        approximate: bool = True,
        limit: int | None = None,
    ) -> str:
        """Write to the stream and optionally trim stream after adding.
        Args:
                data:
                maxlen: maximum len we expect that the stream should be after added.
                approximate: if True, means keeping the stream len AT LEAST the maxlen, so maybe len is tens longer.
                limit: Maximum values to remove after adding.
        Returns:
                Stream id
        Notes:
                See more about parameter in 'XADD' and 'XTRIM'.
                Trim feature should be used by chat service, not by assistant. Assistant instances just give only data.
        """
        assert isinstance(data, StreamData)
        flag = await get_redis().xadd(
            self.key,
            await data.encode(),
            maxlen=maxlen,
            nomkstream=True,
            approximate=approximate,
            limit=limit,
        )
        if flag is None:
            raise KeyError(
                "Stream key doesn't exist. You should create stream using 'create' class method."
            )
        return flag


class ReadStream(Stream):
    """Stateful object stream, it stores state to know what to retrieve next.
    Default setting make async for is blocked and wait for the newest data coming.
            Examples:
                    async for data in read_stream.bind(new_checkpoint, ):
                            if data.state =="done":
                                    ...

                    async for data in read_stream: # default
                            if data.state=="done":

    """

    def __init__(self, stream_key: str):
        super().__init__(stream_key)

        self._checkpoint_id: str = (
            "$"  # get new data coming after the moment of blocking.
        )
        self._count: int|None = 1
        self._save_checkpoint: bool = False

    def bind(
        self,
        checkpoint: str | None = None,
        count: int | Literal["DEFAULT",None] = "DEFAULT",
        save_checkpoint: bool | None = None,
    ) -> Self:
        """Create a new object with new state. Use current states if they are not provided.
        None arg means hold the current settings except count..
        Args:
                checkpoint:
                count:
                save_checkpoint:
        Returns:
                New object of ReadStream.
        """
        new_obj = self.__class__(self.key)
        new_obj._checkpoint_id = checkpoint if checkpoint is not None else self._checkpoint_id
        new_obj._count = count if count!="DEFAULT" else self._count
        
        new_obj._save_checkpoint = save_checkpoint if save_checkpoint is not None else self._save_checkpoint
        return new_obj

    async def read(
        self,
        checkpoint: str | None = None,
        count: int | None = None,
        *,
        block: int | None = None,
    ) -> list[StreamData]:
        """
        Args:
                checkpoint:
                block:
                count:
        Returns:
                list of data
        Notes:
                read method does not check if the stream key exists. So either does not exist or exist with blank data will return [] or {}.
        """
        """
		Raw encodable data from redis stream has the form like this:
			protocol 2
			[['test_stream', [('1747389494281-0', {'user_input': '', 'addition_info': 'null', 'data': '{"id":"068270c0-14f2-700c-8000-22a71d11823c","created_at":"2025-05-16T09:57:21.309097Z","dump":"abc"}'}), ('1747389494418-0', {'user_input': '', 'addition_info': 'null', 'data': '{"id":"068270c0-14f2-700c-8000-22a71d11823c","created_at":"2025-05-16T09:57:21.309097Z","dump":"def"}'})]]]' 
			So data extract be like: data[0][1][:][1], with : is data. (protocol 2)
			
			or 
			
			protocol 3
			{'test_stream': [ [('1749050499833-0', {'abc': '123'}),('1749050622319-0', {'abc': '123'}), ('1749050817070-0', {'abc': '123'})]] }
		With non encodable data, just return byte stream, so the stream key is also byte type.
		"""
        checkpoint = checkpoint if checkpoint is not None else self._checkpoint_id
        count = count if count!="DEFAULT" else self._count

        data = await get_redis(decode_responses=False, protocol=3).xread(
            {self.key: checkpoint}, count, block
        )
        logger.debug(f"Redis read with checkpoint {checkpoint}")
        if data:
            data = data[self.key.encode()][0]
            decoded_data = []
            for d in data:
                decoded_data.append(await StreamData.decode(d[1]))
                
            if self._save_checkpoint:
                ckpt = data[-1][0]
                assert isinstance(ckpt,bytes)
                new_ckpt = ckpt.decode()
                self._checkpoint_id = new_ckpt
                logger.debug(f"Change checkpoint of read stream to {new_ckpt}")
            return decoded_data
        else:
            assert data == {}
            return []
    
    async def capture(self, from_latest:bool = True, count:int|None=None)->list[StreamData]:
        redis = get_redis(decode_responses=False, protocol=3)
        if from_latest:
            data = await redis.xrevrange(self.key,count=count)
        else:
            data = await redis.xrange(self.key,count=count)
        if data:
            return [await StreamData.decode(d[1]) for d in data]
        return []
        

        
    
    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> list[StreamData]:
        return await self.read(block=0)  # block forever.

class StreamPair(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    write_stream: WriteStream | None = None
    read_stream: ReadStream | None = None

class ChatStreams(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    as2cs: StreamPair = Field(default_factory=StreamPair)
    cs2as: StreamPair = Field(default_factory=StreamPair)

# Cache Data Model

class DisplayableMessage(BaseModel):
    role: Literal["assistant", "user", None] = None
    type: Literal["markdown", "html"] = "markdown"
    sender: str|None=None
    
    content: str
    
    # format_attrs: set[str] = Field(default_factory=set)

class DisplayMessage:

    async def get_display_message(self)-> DisplayableMessage | None:
        try:
            m = await self._compose_displayable_data()
            # attr_values = {}
            # for attr in m.format_attrs:
            #     try:
            #         value = getattr(self, attr)
            #         if isawaitable(value):
            #             attr_values[attr] = await value
            #         elif iscoroutinefunction(value):
            #             attr_values[attr] = (
            #                 await value()
            #             )  # Only for none parameters functions
            #         elif callable(value):
            #             attr_values[attr] = await asyncio.to_thread(value)
            #         else:
            #             attr_values[attr] = value
            #     except Exception as e:
            #         attr_values[attr] = e
            #     await asyncio.sleep(0.1)  # Prevent for blocking.
            #
            # m.content.format(**attr_values)
        except NotImplementedError:
            return None
            
        return m

    async def _compose_displayable_data(self)->DisplayableMessage:
        raise NotImplementedError


class DataSegment(BaseModel):
    """User can make subclass of this class to custom any data to cache and storage. Such as context,...
    This class will be used to collect the context.
    Note: instance of this class MUST BE PICKLEABLE.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)
    messages: list[DisplayMessage] = Field(default_factory=list)
    """List of message to display to chat dialog in the order."""
    
    def encode(self)->str:
        return cloudpickle.dumps(self)
    
    @classmethod
    def decode(cls, v: bytes )->Self:
        return cloudpickle.loads(v)

class ChatSessionData(ChatboneData):
    """
    This class has two modes:
            1. Init value to add to UserData.
            2. After added to UserData and refresh, it will bind with user data, now it can interact with server data.
    """
    embedding = True
    data_segments: list[DataSegment] = Field(default_factory=list)
    
    # noinspection PyTypeChecker
    @asynccontextmanager
    async def get_streams(
        self,
        *,
        write_only: bool = False,
        read_only: bool = False,
        write_streams_acquire_timeout: int | None = None,
        raise_on_write_streams_acquire_fail: bool = True,
    ) -> AsyncIterator[ChatStreams]:
        """
        Args:
                write_only:
                read_only:
                write_streams_acquire_timeout:
                raise_on_write_streams_acquire_fail
        Returns:
            ChatStreams
        Raises:
                LockError: Timeout because the others are using the 'write' role of the stream.
        Examples:

                async with cs.get_streams() as streams:
                        assert isinstance(streams['as2cs'][0],WriteStream) and isinstance(streams['as2cs'][1],ReadStream)
        """
        assert not (write_only and read_only)
        await self.init_stream_keys()
        get_all = not write_only and not read_only
        keys = [self.cs2as_stream_rkey, self.as2cs_stream_rkey]

        locked: bool = False  # for debug purpose.

        ret_streams = ChatStreams()

        async def _append_streams(stream_cls: WriteStream | ReadStream | None):
            if stream_cls is None:
                return
            if stream_cls == WriteStream:
                ret_streams.as2cs.write_stream = await stream_cls._create(
                    self.as2cs_stream_rkey
                )
                ret_streams.cs2as.write_stream = await stream_cls._create(
                    self.cs2as_stream_rkey
                )
            elif stream_cls == ReadStream:
                ret_streams.as2cs.read_stream = await stream_cls._create(
                    self.as2cs_stream_rkey
                )
                ret_streams.cs2as.read_stream = await stream_cls._create(
                    self.cs2as_stream_rkey
                )

        async with AsyncExitStack() as stack:
            try:
                # Get write streams
                if write_only or get_all:
                    try:
                        acquire_timeout = (
                            write_streams_acquire_timeout
                            or CONFIG.redis_acquire_lock_timeout
                        )
                        _ = [
                            await stack.enter_async_context(
                                self.redis.lock(
                                    f"{key}:{LOCK_POSTFIX}",
                                    blocking_timeout=acquire_timeout,
                                )
                            )
                            for key in keys
                        ]
                        locked = True
                        logger.debug(
                            f"Write streams pair of chat session '{self.id}' were acquired."
                        )
                        ret_streams.as2cs.write_stream = await WriteStream._create(
                            self.as2cs_stream_rkey
                        )
                        ret_streams.cs2as.write_stream = await WriteStream._create(
                            self.cs2as_stream_rkey
                        )

                    except LockError:
                        logger.debug(
                            f"Chat session '{self.id}' write stream acquired locks fail after trying for {acquire_timeout} seconds."
                        )
                        if raise_on_write_streams_acquire_fail:
                            raise

                # Get read streams, will be skiped if the getting write streams fail.
                if read_only or get_all:
                    ret_streams.as2cs.read_stream = await ReadStream._create(
                        self.as2cs_stream_rkey
                    )
                    ret_streams.cs2as.read_stream = await ReadStream._create(
                        self.cs2as_stream_rkey
                    )

                yield ret_streams

            except Exception as e:
                logger.exception(e)
                raise e
            finally:
                if locked:
                    logger.info(
                        f"Write streams of chat session '{self.id}' were released."
                    )

    async def init_stream_keys(
        self, raise_if_only_one_key_exists: bool = True, max_retry: int = 3
    ):
        """Create and expire a stream key if it does not exist.
        Args:
                raise_if_only_one_key_exists:
                max_retry
        Returns:
        """
        keys = [self.cs2as_stream_rkey, self.as2cs_stream_rkey]
        trial_time = 0

        while trial_time < max_retry:
            try:
                async with self._get_transaction_pipeline() as pipeline:
                    await pipeline.watch(*keys)
                    e0, e1 = [await pipeline.exists(k) for k in keys]
                    pipeline.multi()
                    if e0 and e1:
                        logger.debug(f"Stream keys pair {keys} already created.")
                        return
                    elif not e0 and not e1:
                        await self._init_stream_keys(keys, pipeline)
                        logger.debug(f"Stream keys pair {keys} initialized.")
                        return
                    else:
                        key_not_exist = keys[0] if not e0 else keys[1]
                        error = f"Unexpected behavior in runtime. Expect both stream keys pair exist at the same time, but key '{key_not_exist} not exists.'"
                        if raise_if_only_one_key_exists:
                            raise RuntimeError(error)
                        logger.error(
                            error
                            + f"Not raise exception, try to recover not-existed stream key instead."
                        )
                        await self._init_stream_keys([key_not_exist], pipeline)
                        logger.debug(f"Stream keys pair [{key_not_exist}] initialized.")
                        return
            except WatchError:
                trial_time += 1
                logger.debug(f"Watch error occur during 'init_stream_keys', retry.")
        raise RuntimeError(
            f"'init_stream_key' fail after {max_retry} times retry. This error must not be occur, trace the code again carefully."
        )

    async def _init_stream_keys(self, keys: list[str], pipeline: Pipeline):
        assert pipeline.is_transaction or pipeline.explicit_transaction
        [
            await pipeline.xadd(
                k, {"__init__stream_key": "__init__stream_key"}, maxlen=0
            )
            for k in keys
        ]
        await self.expire_sync(keys, pipeline)

    @property
    def cs2as_stream_rkey(self) -> str:
        return f"{self.rkey_prefix}:{self.id}:<cs2as_stream>"

    @property
    def as2cs_stream_rkey(self) -> str:
        return f"{self.rkey_prefix}:{self.id}:<as2cs_stream>"


class UserNotFoundError(Exception):
    pass


class NoValidTokenError(Exception):
    pass


class EncryptedTokenError(Exception):
    pass


class RedisKeyError(KeyError):
    pass


class UserToken(BaseModel):
    """Oauth2 bearer token"""

    id: UUID
    created_at: datetime
    expires_at: datetime


MIN_DATATIME = datetime.min.replace(tzinfo=timezone.utc)
MIN_UUID = UUID(int=0)


def default_user_token_factory():
    return UserToken(id=MIN_UUID, created_at=MIN_DATATIME, expires_at=MIN_DATATIME)


class UserData(ChatboneData):
    """UserData support lazy load ChatSessionData.
    There are two ways to retrieve data:
    1. Create new instance of this class with username, password, then call refresh.
    2. Through verify_encrypted_token method.
    """

    embedding = False
    username: str
    password: str
    user_token: UserToken = Field(
        default_factory=default_user_token_factory,
        description="Token for access datastore. Be got by authentication process",
    )

    summaries: list[str] = Field(default_factory=list)
    chat_sessions: dict[UUID, ChatSessionData] = Field(default_factory=dict)

    # for dynamic keys.
    encrypted_secret_token: str | None = Field(
        None,
        description="Value of this json key will be the redis key for secret (also be the token returned to user).",
    )

    _refresh_include_default: set[str] = PrivateAttr(
        default_factory=lambda: {"encrypted_secret_token"}
    )
    """Attributes in this set will be refresh by default when call 'refresh'. These Attributes must not be passed as init."""

    @property
    def encrypted_secret_rkey(self):
        if self.encrypted_secret_token is None:
            raise RedisKeyError(
                "Cannot resolve 'encrypted_secret_rkey', you must 'refresh' default mode to load dynamic rkeys first."
            )
        if self.encrypted_secret_token == NULL:
            # logger.warning(
            #     f"encrypted_secret_token in Redis server is null (not string) value but still exist."
            # )
            return None  # get_all_rkey will ignore this
        return f"{self.rkey_prefix}:<encrypted_token>:{self.encrypted_secret_token}"

    async def get_encrypted_token(self, skip_if_exist: bool = True) -> str:
        """Get an encrypted token and return to the user.
        Notes:
                The data must be saved before this method.
        """
        r = await self.redis.json().get(
            self.rkey, f"{self._jsonpath}.encrypted_secret_token"
        )
        if r is None:
            if not await self.redis.exists(self.rkey):
                raise UserNotFoundError("User data doesn't exist. Call 'save' first.")
            r = NULL  # None type is used for check if refreshed state, and NULL  for the real null in redis server.
        else:
            self.encrypted_secret_token = r
            if r != NULL:  # None is saved and load as 'null'
                if skip_if_exist:
                    logger.debug("Return old token.")
                    return self.encrypted_secret_token
                else:
                    d = await self.redis.delete(self.encrypted_secret_rkey)
                    assert d == 1

        key = (
            str(self.id) + "@" + self.username + "@" + self.password
        )  # all components of key are required
        secret_key, token = await asyncio.to_thread(encrypt, key)
        self.encrypted_secret_token = (
            token  # this must be set first for self.encrypted_secret_rkey
        )

        async with self._get_transaction_pipeline() as pipeline:
            await pipeline.set(self.encrypted_secret_rkey, secret_key)

            # UserData need to know the key for retrieve it by this method instead of always create new one.
            # Note: Not use self.set but instead pipeline.json().set() because it not in class fields.
            await pipeline.json().set(
                self.rkey, f"{self._jsonpath}.encrypted_secret_token", token
            )
            await self.expire_sync([self.encrypted_secret_rkey], pipeline)
        logger.debug("Create new token.")

        return self.encrypted_secret_token

    @classmethod
    async def verify_encrypted_token(
        cls, encrypted_token: str, lazy_load_chat_sessions: bool = True
    ) -> Self | None:
        """Redis memory:
        token: secret_key
        user_key: {key:secret_key}

        Raises:
                EncryptedTokenError

        1. Query a secret key using a token.
        2. Use secret key to extract token.
        3. Use that extracted information to get user data.
        """
        if (
            secret_key := await cls.redis.get(
                f"{cls._rkey_prefix()}:<encrypted_token>:{encrypted_token}"
            )
        ) is None:
            raise EncryptedTokenError(
                "No Encrypted token exist, if user data is not expired, use 'get_encrypted_token' first."
            )

        assert isinstance(secret_key, str)
        key: str = await asyncio.to_thread(decrypt, encrypted_token, secret_key)

        uid, username, password = key.split("@")
        userdata = UserData(id=uid, username=username, password=password)

        exclude = set()
        if lazy_load_chat_sessions:
            exclude.add("chat_sessions")

        userdata = await userdata.refresh(exclude)
        await asyncio.to_thread(userdata._bound_cs, userdata.chat_sessions)

        userdata.encrypted_secret_token = encrypted_token

        return userdata

    async def heartbeat(
        self,
        expire_seconds: int | timedelta,
        sleep_ratio: float | None = None,
        sleep_seconds: float | None = None,
    ):
        """
        Args:
                expire_seconds:
                sleep_ratio: Amount time of sleeping that is the ratio of expire_seconds.
                sleep_seconds: Exactly expire seconds, this will be overwritten by sleep_ratio
        """
        assert not (sleep_ratio is None and sleep_seconds is None)
        ss = sleep_ratio * expire_seconds if sleep_ratio else sleep_seconds
        try:
            while True:
                async with self._get_transaction_pipeline() as pipeline:
                    await pipeline.watch(self.rkey)
                    if not (await self.redis.exists(self.rkey)):
                        raise UserNotFoundError
                    pipeline.multi()
                    await self.expire(expire_seconds, pipeline)
                await asyncio.sleep(ss)
        except WatchError:
            raise UserNotFoundError

    async def get_chat_sessions(
        self, session_ids: list[UUID]
    ) -> dict[UUID, ChatSessionData]:
        """For lazy get chat_sessions. This method always gets from redis.
        Args:
                session_ids:
        Returns:
        """
        cs_dict: dict = await self.redis.json().get(
            self.rkey, *[f"{self._jsonpath}.chat_sessions.{uid}" for uid in session_ids]
        )
        if len(session_ids) == 1:
            cs_dict = {f"{self._jsonpath}.chat_sessions.{session_ids[0]}": cs_dict}
        return await asyncio.to_thread(self._process_cs, cs_dict)

    def _process_cs(self, cs_dict: dict) -> dict[UUID, ChatSessionData]:
        cs_dict = {
            UUID(k.rsplit(".", 1)[-1]): ChatSessionData.model_validate(v)
            for k, v in cs_dict.items()
        }

        self._bound_cs(cs_dict)
        self.chat_sessions.update(cs_dict)
        return cs_dict

    def _bound_cs(self, cs_dict: dict[UUID, ChatSessionData]):
        for cs in cs_dict.values():
            cs.bind_rkey_and_json_path(
                self.rkey, f"{self._jsonpath}.chat_sessions.{cs.id}"
            )
