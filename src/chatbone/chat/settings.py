__all__=["DATASTORE","CONFIG"]
from typing import Literal

from dotenv import find_dotenv
from pydantic import BaseModel, PositiveInt, model_validator, ConfigDict
from pydantic_settings import SettingsConfigDict

from utilities.settings import Config, Settings
from utilities.settings.clients.auth import AuthClient
from utilities.settings.clients.datastore import DatastoreClient


# noinspection PyNestedDecorators
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

class ChatBoneTimeout(BaseModel):
	websocket_send: PositiveInt=5
	cache: PositiveInt=300

class ChatConfig(Config):
	datastore_request_timeout: DatastoreRequestTimeout
	chatbone_timeout: ChatBoneTimeout

	max_sessions: PositiveInt = 5
	max_messages: PositiveInt = 10
	max_user_summaries: PositiveInt = 5
	max_chat_summaries: PositiveInt = 5

	reload_histories_strategy:Literal['after_session','after_n_chats'] = 'after_session'
	reload_after_n_chats: PositiveInt = 5

	update_histories_strategy:Literal['after_session','after_n_chats'] = 'after_session'
	update_after_n_chats: PositiveInt = 5


class ChatSettings(Settings):
	model_config = SettingsConfigDict(env_prefix='chat_', env_file=find_dotenv('.env.chat'))
	service_name = 'chatbone.chat'

	config: ChatConfig
	datastore: DatastoreClient

# noinspection Annotator
chat_settings = ChatSettings()

CONFIG = chat_settings.config
DATASTORE = chat_settings.datastore
# REDIS=DATASTORE.redis
