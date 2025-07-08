__all__ = ["DATASTORE", "CONFIG"]

from dotenv import find_dotenv
from pydantic import (
    BaseModel,
    PositiveInt,
    model_validator,
    ConfigDict,
    Field,
    field_validator,
)
from pydantic_settings import SettingsConfigDict

from utilities.settings import Config, Settings
from utilities.settings.auth import AuthClient
from utilities.settings.datastore import DatastoreClient


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
    @model_validator(mode="before")
    @classmethod
    def init_default(cls, data: dict) -> dict:
        for k, v in cls.model_fields.items():
            data[k] = data["default"] if data.get(k) is None else data[k]
        return data


class ChatBoneTimeout(BaseModel):
    websocket_send: PositiveInt = 5
    cache: PositiveInt = 300


class ViewParams(BaseModel):
    route: str
    params: dict[str, str | int | None | float] = Field(default_factory=dict)

    # noinspection PyNestedDecorators
    @field_validator("route", mode="before")
    @classmethod
    def check_route(cls, value: str):
        assert value.startswith("/")
        return value


class Views(BaseModel):
    home: ViewParams = ViewParams(route="/")
    login: ViewParams = ViewParams(route="/login")
    signup: ViewParams = ViewParams(route="/signup")
    app: ViewParams = ViewParams(route="/app")


class ChatConfig(Config):
    datastore_request_timeout: DatastoreRequestTimeout
    chatbone_timeout: ChatBoneTimeout

    max_sessions: PositiveInt = 5
    max_messages: PositiveInt = 10
    max_user_summaries: PositiveInt = 5
    max_chat_summaries: PositiveInt = 5

    userdata_expire_seconds: PositiveInt = 59
    """For expire userdata cache."""

    write_streams_acquire_timeout: PositiveInt = 5
    """Time for acquire write stream lock."""

    views: Views = Views()


env_file = find_dotenv(".env.chatbone")


class ChatSettings(Settings):
    model_config = SettingsConfigDict(env_prefix="chatbone_app_", env_file=env_file)
    service_name = "chatbone_app"

    config: ChatConfig
    datastore: DatastoreClient
    auth: AuthClient


# noinspection Annotator
chat_settings = ChatSettings(env_file=env_file)

CONFIG = chat_settings.config
DATASTORE = chat_settings.datastore  # REDIS=DATASTORE.redis
AUTH = chat_settings.auth
