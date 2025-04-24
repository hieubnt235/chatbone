# from dotenv import find_dotenv
from typing import ClassVar
from uuid import UUID

from dotenv import load_dotenv
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from uuid_extensions import uuid7

from chatbone_utils.exception import handle_exception, BaseMethodException
from chatbone_utils.logger import logger
from .config import Config


class SettingsException(BaseMethodException):
	pass


class Settings(BaseSettings):
	"""
	Base setting for all services. Subclass can set env_file and env_prefix in model_config,
	and must set service_name.
	"""
	model_config = SettingsConfigDict(# env_file=find_dotenv(), # subclass will set
		# env_prefix="chatbone_", # subclass will set
		env_file_encoding='utf-8', extra='ignore', validate_assignment=True, validate_default=True,
		arbitrary_types_allowed=True, nested_model_default_partial_update=True, env_nested_delimiter='__', )

	service_name: ClassVar[str]
	"""Name to be realizable between service. This will be used in conjunction with service_id."""
	service_id: UUID = uuid7()

	config: None = None

	@model_validator(mode='before')
	@classmethod
	@handle_exception(SettingsException)
	def init_setting(cls,data:dict)->dict:
		#If field contain config, it must be type Config and \'file\' must be provided through environment.
		cfg_cls = cls.model_fields['config'].annotation
		if not issubclass(cfg_cls,type(None)) :
			if issubclass(cfg_cls, Config):
				data['config'] = cfg_cls(file=data['config']['file'])
			else:
				raise ValueError(f'Config attribute must be declare as subclass of BaseConfig. Got {cfg_cls.__name__}.')
		return data

	@handle_exception(SettingsException)
	def __init__(self, *args, **kwargs):
		load_dotenv(self.model_config.get('env_file'))
		super().__init__(*args, **kwargs)
		logger.info(f"\'{self.service_name}\' SERVICE SETTINGS:\n"
		            f"{self.model_dump_json(indent=4)}")
