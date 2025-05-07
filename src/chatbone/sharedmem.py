import time

from purse import RedisHash, RedisList
from typing import Literal
from aredis_om import JsonModel, EmbeddedJsonModel
from redis.asyncio import Redis

from utilities.settings.clients.datastore import *

class Message(EmbeddedJsonModel):
	role: Literal['user', 'system', 'assistant']
	content: str

class ChatSessionData(EmbeddedJsonModel):
	messages: list[Message] = Field(default_factory=list)
	summaries: list[str]
	urls: list[AnyUrl] = Field(default_factory=list,description="Addition data should be store in object storage and provide url.")

class UserData(JsonModel):
	username:str
	password:str
	token: UUID
	chat_sessions: list[ChatSessionData] = Field(default_factory=list)


class UserDataCache:
	"""Each instance of this class bind with one ticket as a redis name.
	Also bind to the token name "ticket:token" as the hashkey. So that there are two TTLs to manage.
	"""
	def __init__(self, redis: Redis, ticket:str):
		self.ticket = ticket

		self.redis_handlers = dict(
			session= RedisHash(redis,self._ticket_join(SESSION_KEY),ChatSessionData),
			summaries = RedisList(redis,self._ticket_join(SUMMARIES_KEY),'str'),
			meta = RedisHash(redis,self._ticket_join(META_KEY),UserMeta),
			token = Redis self._ticket_join(TOKEN_KEY)
		)

		self.session_hash = RedisHash(redis,self.session_key, ChatSessionData)
		self.meta_hash = RedisHash(redis,self.meta_key, UserMeta)


		self.redis = redis # for custom hash.
		self.ticket= ticket
		self.token_rkey = ":".join(ticket,TOKEN_KEY)

	def _ticket_join(self,key)->str:
		return ":".join(self.ticket,key)

	async def set_meta(self, user_meta: UserMeta):
		"""Set or update metadata. All the none fields of the input will be ignored, no update current fields to None."""
		m = user_meta.model_dump(mode='json',exclude_none=True)
		return await self.redis.hset(self.ticket,META_KEY, mapping=m)

	async def get_meta(self)->UserMeta:
		return await self.meta_hash.get(META_KEY)

	async def set_session(self,session_id: UUID, session_data: ChatSessionData):
		return await self.session_hash.set(str(session_id), session_data)

	async def get_data(self)->UserData:
		data= await self.get(DATA_KEY)
		return data

	async def set_token(self, token:UUID):
		return await self.redis.hset(self.ticket, TOKEN_KEY, str(token))

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
