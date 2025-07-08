# from dotenv import find_dotenv
import inspect
import os
import time
from pathlib import Path
from typing import ClassVar, get_args, Sequence
from uuid import UUID

from dotenv import load_dotenv, find_dotenv
from pydantic import model_validator
from pydantic.fields import FieldInfo, Field
from pydantic_core import PydanticUndefined
from pydantic_settings import BaseSettings, SettingsConfigDict
from uuid_extensions import uuid7

from utilities.exception import handle_exception, BaseMethodException
from utilities.logger import logger
from .config import Config
from ..func import solve_relative_paths_recursively


class SettingsException(BaseMethodException):
    pass


# noinspection PyNestedDecorators
class Settings(BaseSettings):
    """
    Base setting for all services. Subclass can set env_file and env_prefix in model_config
    and must set service_name.

    All fields that end with "file","path","dir", and is relative (start with '.') will be resolve relatively with
    service_root, which is default the directory contain setting file.
    """

    model_config = SettingsConfigDict(  # env_file=find_dotenv(), # subclass will set
        # env_prefix="chatbone_", # subclass will set
        env_file_encoding="utf-8",
        extra="allow",
        validate_assignment=True,
        validate_default=True,
        arbitrary_types_allowed=True,
        nested_model_default_partial_update=True,
        env_nested_delimiter="__",
        frozen=True,
    )

    env_file:str

    service_name: ClassVar[str]
    """Name to be realizable between service. This will be used in conjunction with service_id."""
    service_id: UUID = uuid7()

    service_root: str|None
    """Absolute root directory of service, if not provide, it will be directory contain file own Settings subclass."""

    config: None = None

    @model_validator(mode="before")
    @classmethod
    @handle_exception(SettingsException)
    def init_setting(cls, data: dict) -> dict:
        # If the field contains config, it must be as type Config and \'file\' must be provided through environment.
        if data.get("service_root") is None:
            logger.debug(f"Service_root not given.")
            env_file = data.get("env_file","")
            logger.debug(f"env_file: {env_file}")
            if env_file !="":
                data["service_root"] = Path(env_file).parent.as_posix()
                logger.debug(f"Use directory of env_file as service root.")
            else:
                data["service_root"] = Path(inspect.getfile(cls)).parent.as_posix()
                logger.debug("Env_file also not found, use settings directory as service root.")

        logger.debug(f"Service root: {data["service_root"]}")
        # Resolve relative paths recursively
        solve_relative_paths_recursively(data, Path(data["service_root"]))

        cfg_field: FieldInfo = cls.model_fields["config"]
        ann = cfg_field.annotation
        args = get_args(ann)
        cfg_cls = None
        
        load_config = False
        if len(args)==0 and issubclass(ann, Config):
            load_config = True
            cfg_cls = ann
        elif len(args)>0  :
            for arg in args:
                if issubclass(arg, Config):
                    load_config = True
                    cfg_cls = arg
                    break
            
        logger.debug(f"ann={ann}, args={args}, load_config={load_config}, cfg_cls={cfg_cls}")
        if load_config:
            try:
                file: str = data["config"]["file"]
                data["config"] = cfg_cls(file=file)
            except (KeyError, TypeError):
                logger.debug(f"Settings {cls.__name__} has Config type attributes but does not find any config file. Let it be default value.")
                # If not have default, load Config default with file = None.
                if cfg_field.default == PydanticUndefined:
                    file: None = None
                    data["config"] = cfg_cls(file=file)
        else:
            raise ValueError(
                f"Config attribute must be declare as subclass of BaseConfig. Got {cfg_cls.__name__}."
            )
        return data

    @handle_exception(SettingsException)
    def __init__(self, *args, **kwargs):
        start = time.time()
        load_dotenv(self.model_config.get("env_file"))
        super().__init__(*args, **kwargs)

        logger.debug(
            f"'{self.service_name}' service settings created in {time.time()-start} seconds:\n"
            f"{self.model_dump_json(indent=4)}"
        )
