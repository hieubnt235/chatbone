from dotenv import find_dotenv
from pydantic import BaseModel, PositiveInt, model_validator, ConfigDict
from pydantic_settings import SettingsConfigDict

from utilities.settings.clients.datastore import DatastoreClient
from utilities.settings import Config, Settings


class DatastoreRequestTimeout(BaseModel):
	default: PositiveInt
	session_create: PositiveInt
	session_delete: PositiveInt
	message_create: PositiveInt
	message_get_latest: PositiveInt
	message_delete_old: PositiveInt
	summary_create: PositiveInt
	summary_get_latest: PositiveInt
	summary_delete_old: PositiveInt

	model_config = ConfigDict(validate_assignment=True, validate_default=True)

	# noinspection PyUnresolvedReferences
	@model_validator(mode='before')
	@classmethod
	def init_default(cls, data: dict) -> dict:
		for k, v in cls.model_fields.items():
			data[k] = data['default'] if data.get(k) is None else data[k]
		return data

class ChatAssistantTimeout(BaseModel):
	websocket_send: PositiveInt=5

class ChatboneConfig(Config):
	datastore_request_timeout: DatastoreRequestTimeout
	chat_assistant_timeout: ChatAssistantTimeout
	max_sessions: PositiveInt = 5
	max_messages: PositiveInt = 10
	max_user_summaries: PositiveInt = 5
	max_chat_summaries: PositiveInt = 5


class ChatboneSettings(Settings):
	model_config = SettingsConfigDict(env_prefix='chat_', env_file=find_dotenv('.env.chat'))
	service_name = 'chatbone'

	config: ChatboneConfig
	datastore: DatastoreClient


# noinspection Annotator
chat_settings = ChatboneSettings()
