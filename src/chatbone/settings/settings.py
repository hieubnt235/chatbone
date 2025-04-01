
from dotenv import find_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict
from chatbone.utils.exception import handle_exception, BaseMethodException
from chatbone.logger import logger

from .dir import DirSettings
from .sql_db import AsyncSQLDBSettings


class ChatBoneSettingsException(BaseMethodException):
    pass

class ChatBoneSettings(BaseSettings):
    """
    Base setting for all settings.
    """
    model_config = SettingsConfigDict(env_file= find_dotenv(),
                                      env_file_encoding='utf-8',
                                      extra='ignore',
                                      validate_assignment=True,
                                      validate_default=True,
                                      nested_model_default_partial_update=True,
                                      env_nested_delimiter='__'
                                      )

    chat_db: AsyncSQLDBSettings
    document_db: AsyncSQLDBSettings
    dir: DirSettings

    auth_secret_key:str=""

# noinspection PyArgumentList
@handle_exception(ChatBoneSettingsException)
def init_chatbone_settings()-> ChatBoneSettings:
    chatbone_settings = ChatBoneSettings()
    logger.info(f"\nSETTINGS:\n"
                f"{chatbone_settings.model_dump_json(indent=4)}")
    return chatbone_settings

chatbone_settings = init_chatbone_settings()