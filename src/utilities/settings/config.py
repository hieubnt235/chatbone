import tomllib

from pydantic import BaseModel, ConfigDict, FilePath, model_validator, Field
from utilities.logger import logger
from utilities.exception import handle_exception, BaseMethodException


class ConfigException(BaseMethodException):
    pass

def valid_config_file(file:FilePath)->FilePath:
    # file = configs_dir / file
    file = FilePath(file)
    if not file.is_file():
        raise FileNotFoundError(f"Config file \'{file}\'not found.")
    if not file.suffix.lower() == ".toml":
        raise ValueError("Only support TOML config file (*.toml) .")

    return file.resolve()


# noinspection PyNestedDecorators
class Config(BaseModel):
    """Base class for configuration models. """
    model_config = ConfigDict(extra="forbid",
                              validate_assignment=True,
                              validate_default=True,
                              arbitrary_types_allowed=True,

                              )
    config_file: FilePath|None = Field(None,alias='file',
                                       description= "If config file is provide, file is first loaded, then update the input parameters.")

    @model_validator(mode='before')
    @classmethod
    @handle_exception(ConfigException, message="Invalid configuration.")
    def init_config(cls,data:dict)->dict:
        config = {}
        if data.get('file') is not None:
            file = valid_config_file(data['file'])
            with open(file,'rb') as f:
                config = tomllib.load(f)
                data['file'] = file
        config.update(data)
        # logger.debug(config)
        return config
