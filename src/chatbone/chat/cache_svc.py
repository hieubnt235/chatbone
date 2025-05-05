from datetime import datetime
from threading import Lock, Thread
from typing import Literal
from uuid import UUID

import uvloop
from pydantic import BaseModel, Field, PositiveInt, AnyUrl
from utilities.func import utc_now, get_expire_date
from utilities.schemas.auth import UserAuthenticate
from utilities.schemas.datastore import UserInfoReturn, MessagesReturn, ChatSummariesReturn, UserSummariesReturn
from uuid_extensions import uuid7

from .settings import REDIS, CONFIG


class ChatSessionData(BaseModel):
	messages: MessagesReturn
	summaries: ChatSummariesReturn
	urls: list[AnyUrl]|None = Field(None,description="Addition data should be store in object storage and provide url.")

class UserData(BaseModel):
	chat_sessions:dict[UUID,ChatSessionData] = Field(description="dict with keys are chat_session_id.")
	summaries: UserSummariesReturn

class UserCacheData(BaseModel):
	# Auth cache
	user_info: UserInfoReturn
	auth: UserAuthenticate = Field(description="This is used for the situation that when update database at the disconnecting, the token is expired.")

	# Data cache
	old: UserData|None=None
	new: UserData|None = None

	def save_cache(self)->UUID:
		REDIS

class Cache(BaseModel):
	created_at: datetime = utc_now()
	expired_at: datetime = get_expire_date(CONFIG.cache_svc_timeout.wait)

	connections:PositiveInt=0
	data: UserCacheData

	def connect(self):
		self.connections+=1
		self.expired_at = get_expire_date(CONFIG.cache_svc_timeout.wait)

	def disconnect(self):
		self.connections+=1

	@property
	def is_expired(self)->bool:
		return utc_now()>= self.expired_at and self.connections==0

# TODO: Implement data update endpoint, for update data intermedialy.
class CacheSVC(Thread):
	"""
	Manage data stored in cache, load database, update database, ...
	"""
	def __init__(self):
		super().__init__()
		self._caches:list[UUID] = []
		self._lock = Lock()
		self.start()

	async def _delete_expire_threadsafe(self,c_id:UUID):
		with self._lock:
			c = await REDIS.hgetall(str(c_id))
			if utc_now() >= datetime(c['expired_at']) and c['connections'] == 0:
				await REDIS.delete(str(c_id))
				self._caches.remove(c_id)

	def run(self):
		async def _run():
			while True:
				for c_id in self._caches:
					await self._delete_expire_threadsafe(c_id)

		uvloop.run(_run())

	async def create_data(self, data:UserCacheData)-> UUID:
		cache = Cache(data=data)
		data_id =uuid7()
		with self._lock:
			await REDIS.hset(str(data_id),mapping=cache.model_dump())
			self._caches.append(data_id)
			return data_id

	async def get(self, data_id: UUID) -> UserCacheData|None:
		with self._lock:
			if data_id not in self._caches:
				return None

			cache = await REDIS.hgetall(str(data_id))

			await REDIS.hset(str(data_id))


	async def commit(self):
		pass

cache_svc = CacheSVC()


if __name__ == "__main__":
	pass