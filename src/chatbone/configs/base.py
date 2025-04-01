import tomllib
from abc import abstractmethod, ABC
from copy import deepcopy
from typing import Self

from pydantic import BaseModel, ConfigDict, FilePath

from chatbone.settings import chatbone_settings
from chatbone.utils.exception import handle_exception, BaseMethodException

configs_dir = chatbone_settings.dir.configs


class ConfigException(BaseMethodException):
    pass

def valid_config_file(file:FilePath)->FilePath:
    file = configs_dir / file
    if not file.is_file():
        raise FileNotFoundError("Config file not found.")
    if not file.suffix.lower() == ".toml":
        raise ValueError("Only support TOML config file.")
    return file

class BaseConfig(BaseModel, ABC):
    """Base class for configuration models. """
    model_config = ConfigDict(extra="forbid",
                              validate_assignment=True,
                              validate_default=True,
                              arbitrary_types_allowed=True)

    @staticmethod
    @abstractmethod
    def key() -> str:
        """Method to get the table key in the config file."""
        pass

    @classmethod
    @handle_exception(ConfigException, message="Invalid configuration.")
    def load(cls, file: FilePath="configs.toml", _r:bool=False) -> Self|dict:
        """Class method to recursively load the configuration from a TOML file.
        All config files should have the same parent directory `chatbone_settings.dir.configs`.

        Args:
            file (FilePath): The path to the configuration file.
            _r (bool): Internal flag for recursive loading. Should not be used by caller.

        Raises:
            FileNotFoundError: If the config file is not found.
            ValueError: If the file is not a TOML file.

        Returns:
            Self | dict: An instance of the configuration class populated with data from the file, or a dictionary if called recursively.

        Examples:
            # /configs/configs.toml

            [key]

            file="/other/other_conf.toml"

            a=5 # b is 8

            # /configs/other/other_conf.toml

            [key]

            a=3

            b=8

        """
        file = valid_config_file(file)
        with open(file, "rb") as f:
            config = tomllib.load(f).get(cls.key(),{})

            #recursive load
            for k in deepcopy(config).keys():
                if k == "file":
                    f = config.pop(k)
                    sub_conf = cls.load(f,_r=True)
                    sub_conf.update(config) # override the sub_conf with new values.
                    config=sub_conf
            if _r:
                return config
            # noinspection PyArgumentList
            return cls(**config)

