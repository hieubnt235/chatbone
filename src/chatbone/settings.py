from typing import Callable

from dotenv import find_dotenv
from pydantic import Field, PositiveInt
from pydantic_settings import SettingsConfigDict
from redis.asyncio import Redis

from utilities.settings import Settings, Config
from utilities.settings.clients.redis_wrapper import RedisWrapperClient


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

class ChatboneConfig(Config):
	redis_lock_timeout: PositiveInt|None=10
	redis_acquire_lock_timeout:PositiveInt|None = 10
	thread_acquire_lock_timeout: int = 10

class ChatboneSettings(Settings):
	model_config = SettingsConfigDict(env_prefix='chatbone_', env_file=find_dotenv('.env.chatbone'),
	                                  arbitrary_types_allowed=True)
	service_name = 'chatbone'

	# redis: RedisSettings
	redis: RedisWrapperClient

	config: ChatboneConfig

	user_secret_key:str = Field("abcxyz", description= "Used for encrypt.")

	# This is for redis_client is redis.asyncio.Redis type directly. But now use wrapper.
	# @model_validator(mode="after")
	# def init_redis_client(self) -> Self:
	# 	if not isinstance(self.redis_client, Redis):
	# 		self.redis_client = Redis(**self.redis.model_dump(exclude={'config'}),
	# 		                          **self.redis.config.model_dump(exclude={"config_file"}))
	# 	return self


chatbone_settings = ChatboneSettings()
get_redis: Callable[...,Redis] = chatbone_settings.redis.new
REDIS: Redis = get_redis()
CONFIG = chatbone_settings.config
SECRET_KEY= chatbone_settings.user_secret_key