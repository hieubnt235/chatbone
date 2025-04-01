from typing import Self

from chatbone.logger import logger
from .auth import AuthConfig
from .base import BaseConfig, valid_config_file
from .chat import ChatConfig
from chatbone.utils import BaseMethodException, handle_exception


class ChatBoneConfigException(BaseMethodException):
    pass

class ChatBoneConfig(BaseConfig):
    auth_config: AuthConfig
    chat_config: ChatConfig

    @staticmethod
    def key() -> str:
        return "configs"

    @classmethod
    def load_all_configs(cls)->Self:
        """ load config for all components. File must be "chatbone_settings.dir.configs/configs.toml". """
        file = valid_config_file("configs.toml")
        configs= dict()
        for k,v in cls.model_fields.items(): # search for all declarative configs.
            if issubclass(v.annotation,BaseConfig):
                configs[k] = v.annotation.load(file)

        app_config = cls.load(file, _r=True) # return dict
        configs.update(app_config)
        return cls(**configs)

@handle_exception(ChatBoneConfigException)
def init_chatbone_configs():
    chatbone_config = ChatBoneConfig.load_all_configs()
    logger.info(f"\nCONFIGURATIONS:\n"
                f"{chatbone_config.model_dump_json(indent=4)}")
    return chatbone_config

chatbone_configs = init_chatbone_configs()