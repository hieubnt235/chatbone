import time
from datetime import datetime
from uuid import UUID

from jsonrpcclient.id_generators import uuid
from purse import RedisHash, RedisList, RedisKeySpace, RedisSet
from pydantic import BaseModel, Field, AnyUrl
from typing import Literal, ClassVar, Any
from redis.asyncio import Redis
from uuid_extensions import uuid7

class IndexData(BaseModel):
	meta_key:str
	key:str

class Message(BaseModel):
	role: Literal['user', 'system', 'assistant']
	content: str

# Data for search directly

class UserMeta(IndexData):
	key:str|None=None

	username:str
	password:str
	cascade_keys:list[str] = Field(default_factory=list, description="When meta is delete, all keys in this list also deleted.")

class Token(IndexData):
	created_at: datetime
	expires_at: datetime

class ChatSessionData(IndexData):
	messages: list[Message] = Field(default_factory=list)
	summaries: list[str]=  Field(default_factory=list)
	urls: list[AnyUrl] = Field(default_factory=list,description="Addition data should be store in object storage and provide url.")

# All cache keys
STRATEGY="""An storage should be in separated key if:
1. Has independent expire strategy.
2. Can search directly.
3. Can do operations like add, remove ,... 
Strategy is noted in docstring with <{number}>
"""


META="{meta_key}"
"""<1> 

- Entry key, set by service that do auth, then service if the key already exist, then do expire or create one.

- Store user information to later self verify DIRECTLY to datastore if token is not valid anymore when disconnect.
Also for simple information (not container) that common for all chat sessions.

Examples:
	Check token valid -> Call Agent -> Get result -> Stream result ->Token expired at persisting result phase -> Do verify using meta.

Notes:
	- This key represent for ONLY ONE user, so it must be unique for each user at the time, maybe user_id or username or unique some mapping.
	- This key is the entry point of all key space, if this key is deleted, all key MUST be deleted.
	"""

ALL_KEYS = META+":all_keys"

TOKEN=META+":token"
"""<1> Key for remain service (one that do not do auth). Token is the entry point to interact with datastore service, so
if it's expire, service will set timeout and wait for exist, frontend must be pool this key to re verify user."""

USER_SUMMARIES = META+":summaries"
"""<2,3> Key store list of user summaries"""

CHAT_SESSIONS = META+":{session_id}"
"""<2>"""
MESSAGES=CHAT_SESSIONS+":messages"
"""<3>"""
SUMMARIES= CHAT_SESSIONS+ ":summaries"
"""<3>"""
URLS=CHAT_SESSIONS+":urls"
"""<3>"""


class Broker:
	"""This will bind with only one Redis client and one main key, should be used for sequencial program,
	 parallel program must have separated Broker with separate Redis."""

	def __init__(self,redis:Redis, meta_key:str):

		self.meta_key = META.format(meta_key=meta_key)

		self.all_keys_handler = RedisSet(ALL_KEYS.format(meta_key=meta_key))

		self.token_key = TOKEN.format(meta_key=meta_key)
		self.user_summaries_key = TOKEN.format(meta_key=meta_key)

		self.meta_handler = RedisKeySpace(redis,self.meta_key, UserMeta)
		self.all_keys

		self.token_handler = RedisHash(redis, self.token_key, Token)

		self.redis=redis

	async def set_meta(self, usermeta:UserMeta|None=None, expire:int|None = None, )->str:
		"""
		Set meta info or/and lifetime for everything.
		Args:
			usermeta: if is instance UserMeta, set it.
			expire: <0 means persist, None mean don't do anything, 0 mean delete.
		Returns:
			The hash key of user meta.
		"""
		if expire == 0:
			return await self.usermeta_handler.clear()

		if usermeta is not None:
			await self.usermeta_handler.set(usermeta.key, usermeta)

		if expire <0:



		await self.usermeta_handler

	async def get_meta(self,hashed_key:str)->str:
		"""
		Args:
			hashed_key:

		Returns: Meta key.
		"""

	async def delete_main(self):



	async def get_token(self,timeout:float= 30, pooling_freq:float=1 )->UUID:
		"""Wait until there is active_token_id.
		Args:
		    pooling_freq: pooling redis frequency, in second.
			timeout: in second.
		Raises:
			TimeoutError
		Returns: active token id.
		"""
		assert timeout >= pooling_freq > 0

		end = time.time()+timeout
		while time.time()<end:
			if (token:= await self.redis.hget(self.ticket,TOKEN_KEY)) is not None:
				return UUID(token)
			await asyncio.sleep(pooling_freq)

		raise TimeoutError
