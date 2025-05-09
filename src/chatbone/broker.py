import time
from contextlib import asynccontextmanager, AbstractAsyncContextManager, AsyncExitStack
from datetime import datetime
from typing import Literal, Self, Awaitable, Any
from uuid import UUID

from aredis_om import JsonModel, Field as OMField, Migrator, RedisModel
from pydantic import Field, AnyUrl, PrivateAttr
from redis import asyncio
from redis.asyncio import Redis
from redis.asyncio.client import Pipeline

from chatbone.settings import REDIS, CONFIG, SECRET_KEY
from utilities.func import utc_now, encrypt, decrypt
from utilities.logger import logger
from utilities.misc import LockContextManager


class ChatBoneJsonModel(JsonModel):
	class Meta:
		global_key_prefix = "chatbone"
		module_key_prefix = ""
		primary_key_pattern = "pk@{pk}"
		database: Redis = REDIS

	@classmethod
	def global_lock_modify_key(cls) -> str:
		""" This attribute is used as a lock key for all modify operations for all instances created by the class in Redis server.
		"""
		return cls.__name__ + "LockModifyKey"

	@classmethod
	def global_lock_read_key(cls) -> str:
		return cls.__name__ + "LockReadKey"


class ChatBoneJsonEmbeddedModel(ChatBoneJsonModel):
	class Meta:
		embedded = True


class Message(ChatBoneJsonEmbeddedModel):
	role: Literal['user', 'system', 'assistant']
	content: str


class ChatSessionData(ChatBoneJsonModel):
	id: UUID = OMField(index=True, primary_key=True)

	messages: list[Message] = Field(default_factory=list)
	summaries: list[str] = Field(default_factory=list)
	urls: list[AnyUrl] = Field(default_factory=list,
	                           description="Addition data should be store in object storage and provide url.")


class UserToken(ChatBoneJsonModel):
	id: UUID = OMField(index=True)
	created_at:datetime
	expires_at:datetime

# Note: These locks only handle lock in one thread (including async tasks), not process.
_cs_key_lock = LockContextManager()
_tkn_key_lock = LockContextManager()

class UserNotFoundError(Exception):
	pass
class NoValidTokenError(Exception):
	pass

class UserData(ChatBoneJsonModel):
	"""This class's methods are app-driven, not the low-level query database. """
	id: UUID = OMField(index=True, primary_key=True)
	username: str = OMField(index=True)
	password: str

	summaries: list[str] = Field(default_factory=list)
	token_id: str
	chat_session_ids: list[UUID] = Field(default_factory=set)

	_cs_key_lock = PrivateAttr(_cs_key_lock)
	_tkn_key_lock = PrivateAttr(_tkn_key_lock)

	async def get_encrypt_token(self) -> str:
		"""Get hash to return to the user"""
		if (userdata:= await UserData.get(self.id)) is None: # refresh
			raise UserNotFoundError
		key = str(userdata.id)+'@'+userdata.username
		return await asyncio.to_thread(encrypt,key, SECRET_KEY)

	@classmethod
	async def verify_encrypt_token(cls, encrypted_token:str) -> Self | None:
		key:str = await asyncio.to_thread(decrypt,encrypted_token,SECRET_KEY)
		uid, username = key.split("@")
		if (userdata:=await UserData.get(uid) )is None:
			raise UserNotFoundError
		assert userdata.username==username
		return userdata

	async def update_token(self, token: UserToken,redis_or_pipeline: Redis | None = None,
	                       *, refresh:bool=True, execute:bool=True, safe: bool = True)->UserToken:
		"""Delete old token (no matter it exists or not) and create new one with expiry date equal to min(Token.expires_at, Redis.ttl(self)).
		Args:
			token: UserToken object that must have 'expires_at' attribute > utc_now().
			redis_or_pipeline: Can be Redis, Pipeline or None, see '_get_transaction_pipeline' for details.
			execute: Whether to execute the pipeline. If the pipeline is not the one given by 'redis_or_pipeline'(given None or Redis), always execute.
			refresh: Reload this object. This will override the 'execute' parameter.
			safe: Threadsafe (blocking) during operation or not, protect others from modify operations in the chat sessions (allow read operations).

		Returns: UserToken object.
		"""

		async with AsyncExitStack() as stack:
			if safe:
				_ = await stack.enter_async_context(self._modify_safe(UserToken))
			pipeline = await stack.enter_async_context(self._get_transaction_pipeline(redis_or_pipeline))

			# Delete, save
			await UserToken.delete(self.token_id,pipeline)
			await token.save(pipeline)

			if (delta:= (token.expires_at - utc_now()).total_seconds() ) <0:
				raise ValueError("Token already expired.")

			# Not wait for the pipeline, expire intermediately.
			await token.expire(min(await self.db().ttl(self.key()), delta))

			# Store keys
			coro: Awaitable[None] = pipeline.json().set(self.key(),".token_id",token.id)
			await coro

			# Post process
			if refresh:
				await pipeline.execute()
				return await UserToken.get(self.token_id)
			elif execute and isinstance(redis_or_pipeline,Pipeline):
				# Be Pipeline means that it will execute from outside but force to execute.
				# If not Pipeline, it will execute by self._get_transaction_pipeline, so no need to execute more.
				await pipeline.execute()
		return token

	async def verify_valid_user(self, timeout: int=15, sleep:int=1)->UserToken:
		"""
		User is considered valid when:
			1. User exists in server.
			2. User has the non-expired token.
		If (1) fails, raise the error for the app to shut down. If (2) fail, wait until timeout the token exist, raise when timeout.
		Returns:
			valid UserToken object.
		Raises:
			UserNotFoundError, NoValidTokenError
		"""
		assert timeout>sleep
		start = time.time()

		while (time.time()-start) < timeout:
			if (user:=await UserData.get(self.id)) is None:
				raise UserNotFoundError(f"No user with id '{self.id}' exists in server.")
			if (token:= await UserToken.get(user.token_id)) is not None:
				return token
			await asyncio.sleep(sleep)

		raise NoValidTokenError(f"There is no valid token for user with id {self.id}. Timeout for {timeout} seconds.")

	async def update_chat_sessions(self, chat_sessions: list[ChatSessionData], redis_or_pipeline: Redis | None = None,
	                               *, refresh:bool=True, execute:bool=True, safe: bool = True)->Self:
		"""If a chat session already exists (the same id), try to update by update each element by concat, else, create a new one.
		This method is different from 'update_chat_session' because of partial updating, not overriding.

		This method will create new chat sessions first, then update available ones.

		Args:
			chat_sessions: list of chat sessions.
			redis_or_pipeline: Can be Redis, Pipeline or None, see '_get_transaction_pipeline' for details.
			execute: Whether to execute the pipeline. If the pipeline is not the one given by 'redis_or_pipeline'(given None or Redis), always execute.
			refresh: Reload this object. This will override the 'execute' parameter.
			safe: Threadsafe (blocking) during operation or not, protect others from modify operations in the chat sessions (allow read operations).
		Returns:
			New refreshed object or self.
		"""
		# Separate
		create_cs: list[ChatSessionData] = []
		update_cs: list[ChatSessionData] = []
		for cs in chat_sessions:
			if cs.id in self.chat_session_ids:
				assert (await self.db().exists(cs.key()) == 1) # If key is stored, the ChatSessionData must exist in the server.
				update_cs.append(cs)
			else:
				create_cs.append(cs)

		async with AsyncExitStack() as stack:
			if safe:
				_ = await stack.enter_async_context(self._modify_safe(ChatSessionData))
			pipeline = await stack.enter_async_context(self._get_transaction_pipeline(redis_or_pipeline))

			# Create new
			_ = await self.add_chat_sessions(create_cs, pipeline, safe=False,refresh=False,execute=False)  # Return self.

			# Update
			for cs in update_cs:
				await self._update_one_chat_session(cs,pipeline)

			if refresh:
				await pipeline.execute()
				return await UserData.get(self.id)
			elif execute and isinstance(redis_or_pipeline, Pipeline):
				# Be Pipeline means that it will execute from outside but force to execute.
				# If not Pipeline, it will execute by self._get_transaction_pipeline, so no need to execute more.
				await pipeline.execute()
		return self

	async def _update_one_chat_session(self, new_cs: ChatSessionData, redis_or_pipeline: Redis | None = None):
		assert new_cs.id in self.chat_session_ids
		async with self._get_transaction_pipeline(redis_or_pipeline) as pipeline:
			coro1: Awaitable[list[int | None]] = pipeline.json().arrappend(new_cs.key(), ".messages",
			                                                                *[m.model_dump() for m in new_cs.messages])
			coro2: Awaitable[list[int | None]] = pipeline.json().arrappend(new_cs.key(), ".summaries",*new_cs.summaries)
			coro3: Awaitable[list[int | None]] = pipeline.json().arrappend(new_cs.key(), ".urls",*[str(u) for u in new_cs.urls])

		await asyncio.gather(coro1,coro2,coro3)

	async def add_chat_sessions(self, chat_sessions: list[ChatSessionData], redis_or_pipeline: Redis | None = None,
	                            *, refresh: bool = True, execute: bool = True, safe: bool = True) -> Self:
		"""Save and sync all chat session lifetime with user data lifetime. If the chat session is available, it will be overridden.

		Args:
			chat_sessions: list of chat sessions.
			redis_or_pipeline: Can be Redis, Pipeline or None, see '_get_transaction_pipeline' for details.
			execute: Whether to execute the pipeline. If the pipeline is not the one given by 'redis_or_pipeline'(given None or Redis), always execute.
			refresh: Reload this object. This will override the 'execute' parameter.
			safe: Threadsafe (blocking) during operation or not, protect others from modify operations in the chat sessions (allow read operations).

		"""

		async with AsyncExitStack() as stack:
			if safe:
				_ = await stack.enter_async_context(self._modify_safe(ChatSessionData))
			pipeline = await stack.enter_async_context(self._get_transaction_pipeline(redis_or_pipeline))

			# Save and expire
			chat_sessions = [await cs.save(pipeline) for cs in chat_sessions]
			await self.expire_sync(chat_sessions.append(self), pipeline)

			# Store keys
			coro: Awaitable[list[int | None]] = pipeline.json().arrappend(self.key(), ".chat_session_ids",*[cs.id for cs in chat_sessions])
			await coro

			# Post process
			if refresh:
				await pipeline.execute()
				return await UserData.get(self.id)
			elif execute and isinstance(redis_or_pipeline,Pipeline):
				# Be Pipeline means that it will execute from outside but force to execute.
				# If not Pipeline, it will execute by self._get_transaction_pipeline, so no need to execute more.
				await pipeline.execute()
		return self

	async def get_chat_session(self, session_id: UUID, *, safe:bool=True) -> ChatSessionData|None:
		"""
		Get chat session base on session_id safety.
		Args:
			session_id:
			safe:
		Returns:
			ChatSessionData or None if not exist
		Raises:
			RuntimeError: When user data and ChatSessionData in redis server is not sync.
		"""
		# Need to check session_id exist BOTH in user data attribute and in redis server, so need safe here.
		async with AsyncExitStack() as stack:
			if safe:
				await stack.enter_async_context(self._modify_safe(ChatSessionData))
			if session_id in self.chat_session_ids:
				if (cs:= await ChatSessionData.get(session_id)) is not None:
					return cs
				else:
					# This error should never raise in real runtime, only raise for debug.
					raise RuntimeError(f"Data has session id \'{session_id}\' exist in \'userdata.chat_session_ids\' but do not have object.")
		return None

	async def delete_chat_session(self, session_id: UUID,*,safe:bool=True):
		async with AsyncExitStack() as stack:
			if safe:
				await stack.enter_async_context(self._modify_safe(ChatSessionData))
			await ChatSessionData.delete(session_id)
			self.chat_session_ids.remove(session_id)


	@asynccontextmanager
	async def _modify_safe(self,model_type: type[ChatBoneJsonModel],
	                       *,
	                       redis_lock_timeout:int|None=None,
	                       redis_acquire_lock_timeout:int|None=None,
	                       thread_acquire_lock_timeout:int|None=None
	                       )->AbstractAsyncContextManager[Any]:
		"""Lock both UserToken instance on redis server and the keys stored in this class.
		this should be used when we need to check data in multiple sources atomically."""
		redis_lock_timeout = redis_lock_timeout or CONFIG.redis_lock_timeout
		redis_acquire_lock_timeout= redis_acquire_lock_timeout or CONFIG.redis_acquire_lock_timeout
		thread_acquire_lock_timeout= thread_acquire_lock_timeout or CONFIG.thread_acquire_lock_timeout

		async with AsyncExitStack() as stack:
			a = await stack.enter_async_context( self.db().lock(model_type.global_lock_modify_key(),
			                                                    timeout=redis_lock_timeout,
			                                                    blocking_timeout=redis_acquire_lock_timeout))  # this will raise if timeout
			ny = await stack.enter_async_context(self._tkn_key_lock.alock(timeout=thread_acquire_lock_timeout))  # raise also
			yield a, ny

	async def expire_user(self, num_seconds: int, redis_or_pipeline: Redis | None = None):
		"""Expire this object, cascade expires all chat sessions and reset the expiry for UserToken with min(num_seconds, UserToken.expires_at)
		Args:
			num_seconds:
			redis_or_pipeline:
		"""
		if (token :=await UserToken.get(self.token_id)) is not None:
			# Expire intermediately.
			await token.expire(min(num_seconds, (token.expires_at-utc_now()).total_seconds() ))

		session_keys = [ChatSessionData.make_primary_key(pk) for pk in self.chat_session_ids]
		await self.expire_cascade(num_seconds, session_keys,redis_or_pipeline)

	async def expire_sync(self, models: list[RedisModel | str], redis_or_pipeline: Redis | None = None) -> None:
		"""Expire all Models sync with this object's current lifetime.
		Args:
			models:RedisModel or key (Redis key, not primary key)
			redis_or_pipeline:
		"""

		async with self._get_transaction_pipeline(redis_or_pipeline) as pipeline:
			num_seconds = await pipeline.ttl(self.key())
			await self.expire_cascade(num_seconds, models.append(self), pipeline)

	async def expire_cascade(self, num_seconds: int, models: list[RedisModel | str],
	                          redis_or_pipeline: Redis | None = None):
		"""Expire all models with the same num_seconds"""
		async with self._get_transaction_pipeline(redis_or_pipeline) as pipeline:
			for m in models:
				await self._expire_one(num_seconds, m, pipeline)

	# noinspection PyMethodMayBeStatic
	async def _expire_one(self, num_seconds: int, m: RedisModel | str, redis_or_pipeline: Redis | None = None):
		async with self._get_transaction_pipeline(redis_or_pipeline) as pipeline:
			if isinstance(m, RedisModel):
				await m.expire(num_seconds, pipeline)  # await db.expire(self.key(), num_seconds)
			elif isinstance(m, str):
				await pipeline.expire(m, num_seconds)
			else:
				raise ValueError

	@asynccontextmanager
	async def _get_transaction_pipeline(self, redis_or_pipeline: Redis | None = None) -> AbstractAsyncContextManager[
		Pipeline]:
		"""
		Args:
			redis_or_pipeline: Can be Redis, Pipeline or None:

				- If it's None, a new transaction pipeline will be created with Meta.database yield and executed at the last.
				- If it's a Redis instance, the same as 'None case' but using passed Redis instead of Meta.database.
				- If it's a Pipeline instance, there must be a transaction Pipeline.

		Returns:
			Async contextmanager of transaction Pipeline instance.
		"""
		if isinstance(redis_or_pipeline, Pipeline):
			assert redis_or_pipeline.is_transaction or redis_or_pipeline.explicit_transaction
			yield redis_or_pipeline  # No execute
		else:
			redis_or_pipeline = redis_or_pipeline or self.db()
			async with redis_or_pipeline.pipeline(transaction=True) as pipeline:
				yield pipeline
				await pipeline.execute()



# async def get_chat_session(chat_session_id:UUID, username:str)->ChatSessionData

MIGRATION = "migrated_flag"


async def migration(raise_if_already_migration: bool = False):
	if await REDIS.get(MIGRATION) is None:
		async with REDIS.lock(MIGRATION + "lock", timeout=10):
			if await REDIS.get(MIGRATION) is None:
				await Migrator().run()
				await REDIS.set(MIGRATION, "Done")
				logger.info("Successfully migrated redis om.")
	if raise_if_already_migration:
		raise RuntimeError("Migration already setup.")


if __name__ == "__main__":
	from uuid_extensions import uuid7
	import asyncio


	async def main():
		await migration()
		userdata = UserData(id=uuid7(), username="abc", password="xyz", token_key="token_key_1")
		await userdata.save()


	asyncio.run(main())

# class Broker:
# 	"""This will bind with only one Redis client and one main key, should be used for sequencial program,
# 	 parallel program must have separated Broker with separate Redis."""
#
# 	def __init__(self,redis:Redis, meta_key:str):
#
# 		self.meta_key = META.format(meta_key=meta_key)
#
# 		self.all_keys_handler = RedisSet(ALL_KEYS.format(meta_key=meta_key))
#
# 		self.token_key = TOKEN.format(meta_key=meta_key)
# 		self.user_summaries_key = TOKEN.format(meta_key=meta_key)
#
# 		self.meta_handler = RedisKeySpace(redis,self.meta_key, UserMeta)
# 		self.all_keys
#
# 		self.token_handler = RedisHash(redis, self.token_key, Token)
#
# 		self.redis=redis
#
# 	async def set_meta(self, usermeta:UserMeta|None=None, expire:int|None = None, )->str:
# 		"""
# 		Set meta info or/and lifetime for everything.
# 		Args:
# 			usermeta: if is instance UserMeta, set it.
# 			expire: <0 means persist, None mean don't do anything, 0 mean delete.
# 		Returns:
# 			The hash key of user meta.
# 		"""
# 		if expire == 0:
# 			return await self.usermeta_handler.clear()
#
# 		if usermeta is not None:
# 			await self.usermeta_handler.set(usermeta.key, usermeta)
#
# 		if expire <0:
#
#
#
# 		await self.usermeta_handler
#
# 	async def get_meta(self,hashed_key:str)->str:
# 		"""
# 		Args:
# 			hashed_key:
#
# 		Returns: Meta key.
# 		"""
#
# 	async def delete_main(self):
#
#
#
# 	async def get_token(self,timeout:float= 30, pooling_freq:float=1 )->UUID:
# 		"""Wait until there is active_token_id.
# 		Args:
# 		    pooling_freq: pooling redis frequency, in second.
# 			timeout: in second.
# 		Raises:
# 			TimeoutError
# 		Returns: active token id.
# 		"""
# 		assert timeout >= pooling_freq > 0
#
# 		end = time.time()+timeout
# 		while time.time()<end:
# 			if (token:= await self.redis.hget(self.ticket,TOKEN_KEY)) is not None:
# 				return UUID(token)
# 			await asyncio.sleep(pooling_freq)
#
# 		raise TimeoutError
