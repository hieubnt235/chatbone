from contextlib import asynccontextmanager, AbstractAsyncContextManager
from typing import Literal, Self, Awaitable
from uuid import UUID

from aredis_om import JsonModel, Field as OMField, Migrator, RedisModel
from pydantic import Field, AnyUrl
from redis.asyncio import Redis
from redis.asyncio.client import Pipeline

from chatbone.settings import REDIS
from utilities.logger import logger


class ChatBoneJsonModel(JsonModel):
	class Meta:
		global_key_prefix = "chatbone"
		module_key_prefix = ""
		primary_key_pattern = "pk@{pk}"
		database: Redis = REDIS


class ChatBoneJsonEmbeddedModel(ChatBoneJsonModel):
	class Meta:
		embedded = True


class Message(ChatBoneJsonEmbeddedModel):
	role: Literal['user', 'system', 'assistant']
	content: str


class ChatSessionData(ChatBoneJsonModel):
	id: UUID = OMField(index=True, primary_key=True)
	username: str = Field(index=True)

	messages: list[Message] = Field(default_factory=list)
	summaries: list[str] = Field(default_factory=list)
	urls: list[AnyUrl] = Field(default_factory=list,
	                           description="Addition data should be store in object storage and provide url.")


class Token(ChatBoneJsonModel):
	id: UUID = OMField(index=True)


class UserData(ChatBoneJsonModel):
	id: UUID = OMField(index=True, primary_key=True)
	username: str = OMField(index=True)
	password: str

	token_key: str
	chat_session_keys: set[str] = Field(default_factory=set)

	async def get_hash(self) -> str:
		"""Get hash to return to user"""
		pass

	@classmethod
	async def verify_hash(cls, hash: str) -> Self | None:
		pass

	async def add_chat_sessions(self, chat_sessions: list[ChatSessionData], redis_or_pipeline: Redis | None = None):
		async with self._get_transaction_pipeline(redis_or_pipeline) as pipeline:
			for cs in chat_sessions:
				await cs.save(pipeline)
			await self.expire_sync(chat_sessions, pipeline)

			# For typehint
			coro: Awaitable[list | int | None] = pipeline.json().arrappend(self.key(), ".chat_session_keys",
			                                                               *[cs.key() for c in chat_sessions])
			await coro

	async def update_chat_sessions(self, chat_sessions: list[ChatSessionData]):
		"""Check if chat session exists, then merge attributes"""

	async def expire_sync(self, models: list[RedisModel | str], redis_or_pipeline: Redis | None = None) -> None:
		"""Expire all Models sync with this object's current lifetime."""
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
	async def _expire_one(self, num_seconds: int, m: RedisModel | str, pipeline: Pipeline):
		if isinstance(m, RedisModel):
			await m.expire(num_seconds, pipeline)  # await db.expire(self.key(), num_seconds)
		elif isinstance(m, str):
			await pipeline.expire(m, num_seconds)
		else:
			raise ValueError

	@asynccontextmanager
	async def _get_transaction_pipeline(self, redis_or_pipeline: Redis | None = None) -> AbstractAsyncContextManager[
		Pipeline]:
		# If the pipeline is passed as the argument, do not execute. Pipeline passed must be in transaction and executed by the one who passed.
		if isinstance(redis_or_pipeline, Pipeline):
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
