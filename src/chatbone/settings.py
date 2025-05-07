from dotenv import find_dotenv
from pydantic_settings import SettingsConfigDict

from utilities.settings import Settings
from utilities.settings.clients.redis_wrapper import RedisWrapperClient


class ChatboneSettings(Settings):
	model_config = SettingsConfigDict(env_prefix='chatbone_', env_file=find_dotenv('.env.chatbone'))
	service_name = 'chatbone'

	redis:RedisWrapperClient

chatbone_settings =  ChatboneSettings()
REDIS = chatbone_settings.redis