import asyncio
from abc import ABC
from contextlib import asynccontextmanager, AbstractAsyncContextManager, AsyncExitStack
from datetime import datetime
from inspect import iscoroutine
from typing import Literal, Self, Awaitable, Any, Sequence, ClassVar, get_origin, get_args
from uuid import UUID

from pydantic import Field, AnyUrl, PrivateAttr, BaseModel, ConfigDict
from redis import WatchError
from redis.asyncio import Redis
from redis.asyncio.client import Pipeline

from chatbone.settings import REDIS, CONFIG
from utilities.func import encrypt, decrypt
from utilities.logger import logger

LOCK_POSTFIX="<LOCK>"
NON_EXIST="<NON_EXIST>"
"""Dummy value for free delete, expire, check,..."""


class ChatboneData(BaseModel,ABC):
	"""This class for data work with Redis.
	All Redis keys are very important for cascade deleting or expiring, they must:

		1. Be defined as property, method name ends with '_rkey' and returns string. See the 'all_rkeys' method.
		2. Have its own id, so that each instance has separate rkey.
	    3. All keys need to be static (constant, or bound with the top level key (with id)), dynamic case should raise when not available.
	    4. Ensure all rkey always exist at the time of expiring or deleting.

	static means

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

	_bounded:bool=PrivateAttr(False)

	_jsonpath:str = PrivateAttr("")
	"""This path will be used to refresh. Embedding model must be reset this value by model own redis key."""
	_base_rkey:str|None = PrivateAttr(None)
	"""This attribute is used by embedding Model, and created by the model hold redis key."""
	_refresh_exclude_default:set[str] = PrivateAttr(default_factory=lambda :set())

	async def refresh(self, exclude:set[str]|None=None)->Self:
		"""Load all data"""
		exclude = exclude or self._refresh_exclude_default
		fields = [field for field in self.model_fields.keys() if field not in exclude]

		if (r:= await self.redis.json().get(self.rkey,*[f"{self._jsonpath}.{field}" for field in fields])) is None:
			raise KeyError("User data doesn't exist. Call 'save' first.")
		if len(fields)==1:
			r = {fields[0]: r}
		else:
			r = {k[1:]:v for k,v in r.items()}
		new_object = self.__class__.model_validate(r)
		if self.embedding:
			new_object.bind_rkey_and_json_path(self.rkey,self._jsonpath)
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


	def bind_rkey_and_json_path(self, rkey:str, jsonpath:str):
		if not self.embedding:
			raise Exception("Can not bind the instance not belong to embedded class.")
		if not jsonpath.startswith("."):
			raise ValueError("Json path must start with '.' .")
		self._base_rkey = rkey
		self._jsonpath = jsonpath
		self._bounded=True


	def get_all_sub_rkeys(self)->list[str]:
		"""Get sub rkeys, which is the property method with name end with '_rkey' and return string.
		Notes:
			This attribute will block cpu.
		"""
		rkeys:list[str] = []
		fields = self.model_fields

		for name in dir(self):
			if 	name.startswith('__') or name in ['rkey','all_sub_rkeys','get_all_sub_rkeys']:
				continue

			f = fields.get(name)
			if not isinstance(getattr(self.__class__, name,None), property) and f is None:
				# if not a property or a field
				continue

			# Field case: Field exist, and a field value type must be ChatboneData,
			# list[ChatBoneData], Tuple[ChatBoneData,...] and dict[Any, ChatBoneData]
			if isinstance(attr:=getattr(self, name),(ChatboneData, list,dict,tuple) ) and f is not None :
				org = get_origin(f.annotation)

				if org is None:
					# Not any container or implicit container typehint case. We have to detect that because when implicit,
					# We do not know what exactly it stores, can be ChatboneData or not. Missing will lead to leak redis keys.
					try:
						assert isinstance(attr, ChatboneData)
					except AssertionError:
						raise SyntaxError(f"Type hint of all container in pydantic model must be explicit. "
						                  f"Ex: list[str], dict[str,str] not list or dict."
						                  f" Got {f.annotation}.")
					rkeys.extend(attr.get_all_sub_rkeys())

				elif issubclass(org,list) and issubclass(get_args(f.annotation)[0],ChatboneData):
					assert isinstance(attr,list)
					for cbd in attr:
						assert isinstance(cbd,ChatboneData)
						rkeys.extend(cbd.get_all_sub_rkeys())
				elif issubclass(org,tuple):
					assert isinstance(attr,tuple)
					try:
						cbd:ChatboneData = attr[attr.index(ChatboneData)]
						rkeys.extend(cbd.get_all_sub_rkeys())
					except ValueError:
						continue
				elif issubclass(org,dict):
					assert isinstance(attr,dict)
					for cbd in attr.values():
						assert isinstance(cbd,ChatboneData)
						rkeys.extend(cbd.get_all_sub_rkeys())

			# Property case exists only name is not in field case.
			elif (iscoroutine(attr) or callable(attr)) or (not name.endswith('_rkey')):
				# Filter properties or field.
				continue

			else:
				try:
					assert isinstance(attr,str)
					rkeys.append(attr)
				except AssertionError:
					raise SyntaxError(f"rkey property method must return value type string, got {type(attr)}")

		return rkeys

	@property
	async def all_sub_rkeys(self)->list[str]:
		return await asyncio.to_thread(self.get_all_sub_rkeys)

	async def expire(self, num_seconds: int, redis_or_pipeline: Redis | None = None):
		"""Expire all keys of this object.
		Args:
			num_seconds:
			redis_or_pipeline:
		"""
		async with self._get_transaction_pipeline(redis_or_pipeline) as pipeline:
			await self.expire_cascade(num_seconds, (await self.all_sub_rkeys) + [self.rkey], pipeline)

	async def expire_sync(self, keys: list[str], redis_or_pipeline: Redis | None = None) -> None:
		"""Expire all Models sync with this object's main rkey lifetime (with 'rkey' key)."""
		async with self._get_transaction_pipeline(redis_or_pipeline) as pipeline:
			num_seconds = await self.redis.ttl(self.rkey)
			keys.append(self.rkey)
			await self.expire_cascade(num_seconds, keys, pipeline)

	async def expire_cascade(self, num_seconds: int, keys: list[str], redis_or_pipeline: Redis | None = None):
		"""Expire all keys with the same num_seconds. Negative value means persist (Note that in raw redis, negative means delete)."""
		assert isinstance(num_seconds,int)
		async with self._get_transaction_pipeline(redis_or_pipeline) as pipeline:
			if num_seconds>0:
				for k in keys:
					await pipeline.expire(k, num_seconds)
			else:
				for k in keys:
					await pipeline.persist(k)

	async def save(self,expire_seconds:int|None=None)->bool|None:
		"""Save data with self.rkey. Skip if exist. If you want to save a new one, 'delete' first.
		Args:
			expire_seconds: None means do nothing. Negative means persist.
		Returns:
			True if a new value is created, None if no new value is created.
		"""
		# TODO: support skip and update in save ?, careful handle cascade keys.
		if self.embedding:
			raise ValueError("Embedding model cannot save redis object.")
		rs =  await self.redis.json().set(self.rkey,'.',self.model_dump(mode='json'),nx=True)
		if expire_seconds is not None:
			await self.expire(expire_seconds)
		return rs

	async def delete(self)->int:
		"""Cascading delete for all redis keys. Note again that this method deletes all redis keys, not the JSON keys.
		Returns:
			Number of keys were removed.
		"""
		if self.embedding:
			raise ValueError("Embedding model cannot delete redis object.")
		return await self.redis.delete(self.rkey, *(await self.all_sub_rkeys))

	async def append(self, field: str, values: list[Any],redis_or_pipeline: Redis | None = None):
		"""Append to a JSON list.
		Args:
			field: field name of a pydantic model.
			values: list of values that intent to be appended.
			redis_or_pipeline:
		Returns:
		"""
		# TODO, append to instance also ? not only on server. or let the client do refresh ?
		await asyncio.to_thread(self._check_list_params,field, values)
		async with self._get_transaction_pipeline(redis_or_pipeline, lock_modify=False,watch=False, execute=False) as pipeline:
			coro: Awaitable[list[int | None]] = pipeline.json().arrappend(self.rkey, f"{self._jsonpath}.{field}", *values)
			await coro
			if not redis_or_pipeline:
				return (await pipeline.execute())[0]
		return None

	async def trim(self, field:str, start:int, stop:int,redis_or_pipeline: Redis | None = None) ->int:
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
		await asyncio.to_thread(self._check_list_params(field))
		async with self._get_transaction_pipeline(redis_or_pipeline, lock_modify=False,watch=False, execute=False) as pipeline:
			coro: Awaitable[list[int | None]] = pipeline.json().arrtrim(self.rkey,f"{self._jsonpath}.{field}", start,stop)
			await coro
			if not redis_or_pipeline:
				return (await pipeline.execute())[0]
		return None

	async def update(self, field:str, values:dict[Any,Any],redis_or_pipeline: Redis | None = None):
		"""Update the dict with keys and values.
		Args:
			field:
			values:
			redis_or_pipeline
		Returns:
		"""
		await asyncio.to_thread(self._check_dict_params(field,values))
		async with self._get_transaction_pipeline(redis_or_pipeline ,lock_modify=False,watch=False, execute=False) as pipeline:
			coros:list[Awaitable[list[int | None]]] = []
			for k,v in values.items():
				coros.append(pipeline.json().set(self.rkey, f"{self._jsonpath}.{field}.{k}",v) )
			return await asyncio.gather(*coros)

	async def set(self, field: str, value: Any,redis_or_pipeline: Redis | None = None):
		""" Override the attributes to entirely new one.
		Args:
			field:
			value:
			redis_or_pipeline:
		Returns:
		"""
		await asyncio.to_thread(self._check_params(field,value))
		async with self._get_transaction_pipeline(redis_or_pipeline, lock_modify=True) as pipeline:
			coro: Awaitable[list[int | None]] = pipeline.json().set(self.rkey,f"{self._jsonpath}.{field}")
			return await coro

	async def clear(self, field: str, value: Any, redis_or_pipeline: Redis | None = None):
		"""Clear container values (arrays/objects) and set numeric values to 0"""
		self._check_params(field,value)
		async with self._get_transaction_pipeline(redis_or_pipeline,lock_modify=True) as pipeline:
			coro: Awaitable[list[int | None]] = pipeline.json().clear(self.rkey,f"{self._jsonpath}.{field}")
			return await coro

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
			for v in values:
				if not isinstance(v, get_args(ann)[0]):
					raise ValueError(f"Value to append in this field must be type {get_args(ann)[0]}. Got {type(values)} .")


	@asynccontextmanager
	async def _lock_modify(self,timeout:int|None=None, blocking_timeout:int|None=None):
		timeout = timeout or CONFIG.redis_lock_timeout
		blocking_timeout = blocking_timeout or CONFIG.redis_acquire_lock_timeout
		async with self.redis.lock(f"{self.rkey}:{LOCK_POSTFIX}",timeout=timeout,blocking_timeout=blocking_timeout) as lock:
			yield lock

	@asynccontextmanager
	async def _get_transaction_pipeline(self, redis_or_pipeline: Redis | None = None, *,
	                                    lock_modify:bool=False,
	                                    watch:bool=False,
	                                    execute:bool=True) -> AbstractAsyncContextManager[Pipeline]:
		"""
		Get the transaction pipeline while providing options to ensure that key is exist during execute pipe..

		TODO: How about check exist first, save ttl then persist, execute and expire later depend on the saved value ?

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

				if watch:
					await pipeline.watch(self.rkey)
				if not ( await self.redis.exists(self.rkey)):
					raise KeyError("Rkey is no longer exist. Call 'save' first.")

				pipeline.multi()
				try:
					yield pipeline
					if execute:
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
	# TODO NOW
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
		return f"{self.rkey_prefix}:{self.id}:<cs2as_stream>"

	@property
	def as2cs_stream_rkey(self)->str:
		return f"{self.rkey_prefix}:{self.id}:<as2cs_stream>"

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

class EncryptedTokenError(Exception):
	pass

class AuthToken(BaseModel):
	id:UUID
	created_at:datetime
	expires_at:datetime

class UserData(ChatboneData):
	"""UserData support lazy load ChatSessionData.
	There are two ways to retrieve data:
	1. Create new instance of this class with username, password, then call refresh.
	2. Through verify_encrypted_token method.
	"""
	embedding = False
	username: str
	password: str
	summaries: list[str] = Field(default_factory=list)
	chat_sessions: dict[UUID,ChatSessionData] = Field(default_factory=dict)

	encrypted_secret_token:str=Field(NON_EXIST, description="Value of this json key will be the redis key for secret (also be the token returned to user).")

	@property
	def encrypted_secret_rkey(self):
		return f"{self.rkey_prefix}:<encrypted_token>:{self.encrypted_secret_token}"

	@property
	def auth_token_rkey(self):
		return f"{self.rkey_prefix}:{self.id}:<auth_token>"

	async def get_encrypted_token(self, skip_if_exist:bool=True) -> str:
		"""Get an encrypted token and return to the user.
		Notes:
			The data must be saved before this method.
		Raises
			KeyError: If data is not available or be expired during operations.
		"""
		if (r := await self.redis.json().get(self.rkey, f"{self._jsonpath}.encrypted_secret_token")) is None:
			raise KeyError("User data doesn't exist. Call 'save' first.")
		else:
			assert isinstance(r, str)
			if r != NON_EXIST:
				if skip_if_exist:
					self.encrypted_secret_token = r
					logger.debug("Return old token.")
					return self.encrypted_secret_token
				else:
					d = await self.redis.delete(self.encrypted_secret_rkey)
					assert d==1

		key = str(self.id)+'@'+self.username+'@'+self.password
		secret_key, token = await asyncio.to_thread(encrypt,key )
		self.encrypted_secret_token=token # this must be set first for self.encrypted_secret_rkey

		async with self._get_transaction_pipeline() as pipeline:
			await pipeline.set(self.encrypted_secret_rkey,secret_key)

			# UserData need to know the key for retrieve it by this method instead of always create new one.
			# Note: Not use self.set but instead pipeline.json().set() because it not in class fields.
			await pipeline.json().set(self.rkey,f"{self._jsonpath}.encrypted_secret_token", token)
			await self.expire_sync([self.encrypted_secret_rkey],pipeline)
		logger.debug("Create new token.")

		return self.encrypted_secret_token

	@classmethod
	async def verify_encrypted_token(cls, encrypted_token:str, lazy_load:bool=True) -> Self | None:
		"""Redis memory:
		token: secret_key
		user_key: {key:secret_key}

		1. Query a secret key using a token.
		2. Use secret key to extract token.
		3. Use that extracted information to get user data.
		"""
		if (secret_key:= await cls.redis.get(f"{cls.rkey_prefix}:<encrypted_token>:{encrypted_token}")) is None:
			raise EncryptedTokenError("No Encrypted token exist, if user data is not expired, use 'get_encrypted_token' first.")

		assert isinstance(secret_key,str)
		key:str = await asyncio.to_thread(decrypt,encrypted_token,secret_key)

		uid, username, password = key.split("@")
		userdata = UserData(id=uid,username=username,password=password)

		exclude = set()
		if lazy_load:
			exclude.add('chat_sessions')

		userdata = await userdata.refresh(exclude)
		await asyncio.to_thread(userdata._bound_cs,userdata.chat_sessions)

		userdata.encrypted_secret_token = encrypted_token

		return userdata

	async def add_chat_sessions(self,chat_sessions:list[ChatSessionData])->None:
		async with self._get_transaction_pipeline() as pipeline:
			cs_dict = {cs.id:cs for cs in chat_sessions}
			await self.update('chat_sessions',cs_dict,pipeline)

	async def get_chat_sessions(self,session_ids: list[UUID])->dict[UUID,ChatSessionData]:
		cs_dict:dict = await self.redis.json().get(self.rkey,*[f"{self._jsonpath}.chat_sessions.{uid}" for uid in session_ids ])
		if len(session_ids)==1:
			cs_dict = {f"{self._jsonpath}.chat_sessions.{session_ids[0]}":cs_dict}
		return await asyncio.to_thread(self._process_cs, cs_dict)

	def _process_cs(self, cs_dict: dict) -> list[ChatSessionData]:
		cs_dict = {UUID(k.rsplit(".", 1)[-1]): ChatSessionData.model_validate(v) for k, v in cs_dict.items()}
		self._bound_cs(cs_dict)
		self.chat_sessions.update(cs_dict)
		return cs_dict

	def _bound_cs(self, cs_dict: dict[UUID, ChatSessionData]):
		for cs in cs_dict.values():
			cs.bind_rkey_and_json_path(self.rkey, f"{self._jsonpath}.chat_sessions.{cs.id}")





