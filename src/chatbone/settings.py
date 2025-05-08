from typing import Any, Self

from dotenv import find_dotenv
from pydantic import BaseModel, Field, model_validator, field_validator
from pydantic_settings import SettingsConfigDict
from redis.asyncio import Redis

from utilities.settings import Settings, Config


class RedisConfig(Config):
	decode_responses:bool = True

class RedisSettings(BaseModel):
	host:str ="localhost"
	port:int = 6379
	db:int = 0
	username:str|None=None
	password:str|None=None
	config: RedisConfig


class ChatboneSettings(Settings):
	model_config = SettingsConfigDict(env_prefix='chatbone_', env_file=find_dotenv('.env.chatbone'), arbitrary_types_allowed=True)
	service_name = 'chatbone'

	redis: RedisSettings
	redis_client: Redis|None = Field(None,exclude=True)

	@model_validator(mode="after")
	def init_redis_client(self)->Self:
		if not isinstance(self.redis_client,Redis):
			self.redis_client = Redis(**self.redis.model_dump(exclude={'config'}), **self.redis.config.model_dump(exclude={"config_file"}))
		return self

chatbone_settings =  ChatboneSettings()
REDIS: Redis = chatbone_settings.redis_client