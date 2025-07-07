from typing import Callable

from dotenv import find_dotenv
from pydantic import PositiveInt
from pydantic_settings import SettingsConfigDict
from redis.asyncio import Redis

from utilities.settings import Settings, Config
from utilities.settings.objest_storage import ObjectStorageSettings
from utilities.settings.redis_wrapper import RedisWrapperClient


# class RedisConfig(Config):
# 	decode_responses: bool = True
#

# class RedisSettings(BaseModel):
# 	host: str = "localhost"
# 	port: int = 6379
# 	db: int = 0
# 	username: str | None = None
# 	password: str | None = None
# 	config: RedisConfig

env_file = find_dotenv('.env.chatbone')
class ChatboneConfig(Config):
	redis_lock_timeout: PositiveInt|None=10
	redis_acquire_lock_timeout:PositiveInt|None = 10
	thread_acquire_lock_timeout: int = 10

	request_user_input_timeout: int=100 # <=0 for wait forever.

class ChatboneSettings(Settings):
	model_config = SettingsConfigDict(env_prefix='chatbone_', env_file=env_file,
                                      arbitrary_types_allowed=True)
	service_name = 'chatbone'

	# redis: RedisSettings
	redis: RedisWrapperClient |None = None
	object_storage: ObjectStorageSettings|None=None
	config: ChatboneConfig|None = None


chatbone_settings = ChatboneSettings(env_file=env_file)
get_redis: Callable[...,Redis] = chatbone_settings.redis.new
REDIS: Redis = get_redis()
CONFIG = chatbone_settings.config
OBJ_STORAGE = chatbone_settings.object_storage

if __name__ =="__main__":
	import asyncio
	async def main():
		await OBJ_STORAGE.verify_bucket()
		print(await OBJ_STORAGE.get_upload_url("test-object"))
		# print(await OBJ_STORAGE.get_download_url("test-object"))

	asyncio.run(main())