import asyncio
from abc import ABC
from contextlib import asynccontextmanager, AbstractAsyncContextManager, AsyncExitStack
from datetime import datetime
from typing import Literal, Self, Awaitable, Any, Sequence, ClassVar, get_origin, get_args
from uuid import UUID

from pydantic import Field, AnyUrl, PrivateAttr, BaseModel, ConfigDict
from redis import WatchError
from redis.asyncio import Redis
from redis.asyncio.client import Pipeline

from chatbone.settings import REDIS, CONFIG, SECRET_KEY
from utilities.func import encrypt, decrypt
from utilities.logger import logger

LOCK_POSTFIX="<LOCK>"


# noinspection PyPropertyDefinition
class ChatboneData(BaseModel,ABC):
	"""This class for data work with Redis.
	All Redis keys must be defined as property and return string. See the 'all_rkeys' method.
	The main key must be 'rkey', all other keys will have the lifetime synced with this key.

	Notes:
		1. Data is got through attributes of this class, require refresh manually to get updated data.
		2. Only support modify first level attributes. Nested attributes are not allowed to modify, they must be modified using the submodel.
			So that if there are any modifiable values, it needs to wrap with BaseModel subclass.
		3. Model does not own a redis key must be set embedding = True (default), if not, it cannot modify data, or unbehavior things would happen.
	"""

	# This value is True by default for accidentally create new key in the server because of using an embedding model without set it to True.
	embedding:ClassVar[bool] = True
	"""Embedding class will not persist and manage any redis key/object."""
	redis:ClassVar[Redis] = REDIS
	model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)

	id: UUID


	_jsonpath:str = PrivateAttr("$.")
	"""This path will be used to refresh. Embedding model must be reset this value by model own redis key."""
	_base_rkey:str|None = PrivateAttr(None)
	"""This attribute is used by embedding Model, and created by the model hold redis key."""

	async def refresh(self, exclude:set[str]|None)->Self:
		"""Load all data"""
		exclude = exclude or set()
		fields = [field for field in self.model_fields.items() if field not in exclude]
		async with self._get_transaction_pipeline(lock_modify=True) as pipeline:
			loads = await pipeline.json().get(self.rkey,
			                                 *[f"{self._jsonpath}.{field}" for field in fields])
		new_object = self.model_validate(**{k:v for k,v in zip(fields,loads)})
		if self.embedding:
			new_object.bind__base_rkey(self.rkey,self._jsonpath)
		return new_object

	@classmethod
	@property
	def rkey_prefix(cls):
		return f"{cls.__module__}:{cls.__name__}"

	@property
	def rkey(self)->str:
		"""Main rkey. The embedding class must redefine this class to """
		if self.embedding:
			if self._base_rkey is None:
				raise ValueError("This embedding object haven't bound any base rkey.")
			else:
				return self._base_rkey
		return f"{self.rkey_prefix}:{self.id}"

	def bind__base_rkey(self, rkey:str, _jsonpath:str):
		self._base_rkey = rkey
		self._jsonpath = _jsonpath

	@property
	def all_sub_rkeys(self)->list[str]:
		"""Sub rkeys, always end with '_rkey'."""
		rkeys:list[str] = []
		for name in dir(self):
			if name.endswith('_rkey'):
				attr = getattr(self,name)
				assert isinstance(attr,str)
				rkeys.append(attr)
		return rkeys


	async def expire(self, num_seconds: int, redis_or_pipeline: Redis | None = None):
		"""Expire all keys of this object.
		Args:
			num_seconds:
			redis_or_pipeline:
		"""
		async with self._get_transaction_pipeline(redis_or_pipeline) as pipeline:
			await self.expire_cascade(num_seconds, self.all_sub_rkeys + self.rkey, pipeline)

	async def expire_sync(self, keys: list[str], redis_or_pipeline: Redis | None = None) -> None:
		"""Expire all Models sync with this object's main rkey lifetime (with 'rkey' key)."""
		async with self._get_transaction_pipeline(redis_or_pipeline) as pipeline:
			num_seconds = await pipeline.ttl(self.rkey)
			await self.expire_cascade(num_seconds, keys.append(self), pipeline)

	async def expire_cascade(self, num_seconds: int, keys: list[str], redis_or_pipeline: Redis | None = None):
		"""Expire all keys with the same num_seconds."""
		async with self._get_transaction_pipeline(redis_or_pipeline) as pipeline:
			for k in keys:
				await pipeline.expire(k, num_seconds)

	async def save(self, skip_if_exist:bool=True):
		if self.embedding:
			raise ValueError("Embedding model cannot save redis object.")
		await self.redis.json().set(self.rkey,'.',self.model_dump(mode='json'),nx=skip_if_exist)

	async def delete(self, redis_or_pipeline: Redis | None = None):
		"""Cascading delete for all keys."""
		async with self._get_transaction_pipeline(redis_or_pipeline, lock_modify=True) as pipeline:
			await pipeline.delete(self.rkey, *self.all_sub_rkeys)

	async def append(self, field: str, values: list[Any],redis_or_pipeline: Redis | None = None):
		"""Append to a JSON list.
		Args:
			field: field name of a pydantic model.
			values: list of values that intent to be appended.
			redis_or_pipeline:
		Returns:
		"""
		self._check_list_params(field, values)
		async with self._get_transaction_pipeline(redis_or_pipeline, lock_modify=True) as pipeline:
			coro: Awaitable[list[int | None]] = pipeline.json().arrappend(self.rkey, f"{self._jsonpath}.{field}", *values)
			return await coro

	async def trim(self, field:str, start:int, stop:int,redis_or_pipeline: Redis | None = None):
		self._check_list_params(field)
		async with self._get_transaction_pipeline(redis_or_pipeline, lock_modify=True) as pipeline:
			coro: Awaitable[list[int | None]] = pipeline.json().arrtrim(self.rkey,f"{self._jsonpath}.{field}", start,stop)
			return await coro

	async def set(self, field: str, value: Any,redis_or_pipeline: Redis | None = None):
		self._check_params(field,value)
		async with self._get_transaction_pipeline(redis_or_pipeline, lock_modify=True) as pipeline:
			coro: Awaitable[list[int | None]] = pipeline.json().set(self.rkey,f"{self._jsonpath}.{field}")
			return await coro

	async def clear(self, field: str, value: Any, redis_or_pipeline: Redis | None = None):
		"""Clear container values (arrays/objects) and set numeric values to 0"""
		self._check_params(field,value)
		async with self._get_transaction_pipeline(redis_or_pipeline,lock_modify=True) as pipeline:
			coro: Awaitable[list[int | None]] = pipeline.json().clear(self.rkey,f"{self._jsonpath}.{field}")
			return await coro

	#TODO implement more json operations.

	def _check_params(self,field:str ,value:Any):
		assert field not in ["id","redis","_jsonpath"]
		ann = self.model_fields[field].annotation
		org = get_origin(ann)
		if org is None:
			if not isinstance(value, ann):
				raise ValueError(f"Field '{field}' type is '{ann}' but input value is '{type(value)}'.")
			return
		if issubclass(org,Sequence):
			self._check_list_params(field,value)
		if issubclass(org,dict):
			self._check_dict_params(field,value)
		raise ValueError(f"Type {value} is not supported.")

	def _check_dict_params(self,field:str , values:dict):
		ann = self.model_fields[field].annotation
		org = get_origin(ann)
		kt,vt = get_args(ann)
		if not issubclass(org,dict):
			raise ValueError(f"The field must be a dict. Got {get_origin(ann)}.")
		for k,v in values.items():
			if not isinstance(k,kt) or not isinstance(v,vt):
				raise ValueError(f"KeyType must be {kt} and ValueType must be {vt}.")

	def _check_list_params(self, field:str, values: list[Any]|None=None):
		ann = self.model_fields[field].annotation
		if not issubclass(get_origin(ann), Sequence):
			raise ValueError(f"The field must be a Sequence. Got {get_origin(ann)} .")
		if values is not None:
			if not isinstance(values, get_args(ann)):
				raise ValueError(f"Value to append in this field must be type {get_args(ann)}. Got {get_args(values)} .")


	@asynccontextmanager
	async def _lock_modify(self,timeout:int|None=None, blocking_timeout:int|None=None):
		timeout = timeout or CONFIG.redis_lock_timeout
		blocking_timeout = blocking_timeout or CONFIG.redis_acquire_lock_timeout
		async with self.redis.lock(f"{self.rkey}:{LOCK_POSTFIX}",timeout=timeout,blocking_timeout=blocking_timeout) as lock:
			yield lock

	@asynccontextmanager
	async def _get_transaction_pipeline(self, redis_or_pipeline: Redis | None = None, lock_modify:bool=True, watch:bool=True) -> AbstractAsyncContextManager[Pipeline]:
		"""
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
			assert redis_or_pipeline.is_transaction or redis_or_pipeline.explicit_transaction
			yield redis_or_pipeline  # No execute
		else:
			redis_or_pipeline = redis_or_pipeline or self.redis
			async with AsyncExitStack() as stack:
				if lock_modify:
					await stack.enter_async_context(self._lock_modify())
				pipeline:Pipeline = await stack.enter_async_context(redis_or_pipeline.pipeline(transaction=True))

				# Watch for ensuring key not expire during queue commands. Note that if we do not lock,
				# every command that changes value will make the watch raise an error, so it should be lock and watch when do modifying.
				# That's why they are all default.

				if watch:
					await pipeline.watch(self.rkey)
				if not ( await self.redis.exists(self.rkey)):
					raise KeyError("Rkey is no longer exist. Call 'save' first.")

				pipeline.multi()
				try:
					yield pipeline
					await pipeline.execute()
				except WatchError:
					raise KeyError("Rkey is no longer exist after queue commands.")

class StreamData(BaseModel):
	pass

class Stream[DataType]:
	def __init__(self,stream_key:str, datatype:type[DataType], redis:Redis):
		self.datatype: StreamData = datatype
		self.key = stream_key
		self.redis= redis

	async def send(self, data: DataType, **xadd_kwargs):
		assert isinstance(data,StreamData)

		if not (await self.redis.exists(self.key)):
			raise KeyError("Stream key doesn't exist. You should create stream using 'create' class method.")
		await self.redis.xadd(self.key, data.model_validate(mode='json'),**xadd_kwargs)

	async def receive(self)->DataType:
		pass

	async def clear(self):
		pass

	@classmethod
	@asynccontextmanager
	async def create(cls, stream_key:str, datatype:type[DataType], redis:Redis|None=None)->Self:
		redis = redis or REDIS
		if not isinstance(datatype,StreamData):
			raise ValueError(f"Datatype must be the subclass of 'StreamData' but got {datatype}.")

		if not (await redis.exists(stream_key)):
			await redis.xadd(stream_key,{},maxlen=0)
		assert (await redis.exists(stream_key))

		return cls(stream_key, datatype, redis)

class Message(BaseModel):
	role: Literal['user', 'system', 'assistant']
	content: str

class ChatSessionData(ChatboneData):
	"""
	This class has two modes:
		1. Init value to add to UserData.
		2. After added to UserData and refresh, it will bind with user data, now it can interact with server data.

	"""
	embedding = True

	messages: list[Message] = Field(default_factory=list)
	summaries: list[str] = Field(default_factory=list)
	urls: list[AnyUrl] = Field(default_factory=list,
	                           description="Addition data should be store in object storage and provide url.")

	@property
	def cs2as_stream_rkey(self)->str:
		return f"{self.__module__}:{self.__class__.__name__}:{self.id}:<cs2as_stream>"

	@property
	def as2cs_stream_rkey(self)->str:
		return f"{self.__module__}:{self.__class__.__name__}:{self.id}:<as2cs_stream>"

	@asynccontextmanager
	async def get_stream(self,stream_type:Literal['as2cs','cs2as'], datatype:type[BaseModel], redis:Redis|None=None)->AbstractAsyncContextManager[Stream]:
		assert stream_type in ['as2cs', 'cs2as']
		key = self.cs2as_stream_rkey if stream_type == 'cs2as' else self.as2cs_stream_rkey

		async with self.redis.lock(f"{key}:{LOCK_POSTFIX}"):
			logger.debug(f"Stream '{key}' acquired.")
			try:
				yield await Stream[datatype].create(key, datatype,redis)
			except Exception as e:
				logger.exception(e)
			finally:
				logger.debug(f"Stream '{key}' released.")


class UserNotFoundError(Exception):
	pass
class NoValidTokenError(Exception):
	pass

class Token(BaseModel):
	id:UUID
	created_at:datetime
	expires_at:datetime

class UserData(ChatboneData):
	"""UserData support lazy load ChatSessionData."""
	embedding = False
	username: str
	password: str
	summaries: list[str] = Field(default_factory=list)
	token:Token|None= Field(None,description="Valid token.")
	chat_sessions: dict[UUID,ChatSessionData] = Field(default_factory=list)


	async def get_encrypt_token(self) -> str:
		"""Get hash to return to the user"""
		key = str(self.id)+'@'+self.username+'@'+self.password
		return await asyncio.to_thread(encrypt,key, SECRET_KEY)

	@classmethod
	async def verify_encrypt_token(cls, encrypted_token:str, lazy_load:bool=True) -> Self | None:
		key:str = await asyncio.to_thread(decrypt,encrypted_token,SECRET_KEY)
		uid, username, password = key.split("@")
		userdata = UserData(id=uid,username=username,password=password)

		exclude = set()
		if lazy_load:
			exclude.add('chat_sessions')

		userdata = await userdata.refresh(exclude)
		for cs in userdata.chat_sessions.values():
			cs.bind__base_rkey(userdata.rkey,"$.chat_sessions")
		return userdata

	async def add_chat_session(self,chat_session:ChatSessionData)->ChatSessionData:
		pass

	async def get_chat_sessions(self,session_id:UUID)->ChatSessionData:
		pass





