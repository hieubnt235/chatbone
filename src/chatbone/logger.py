# from redis.commands.cluster import ClusterMultiKeyCommands
#
# from chatbone.config import BaseConfig
# from chatbone.settings import settings
#
#
# def check_sink(value: str) -> str | TextIO:
#     """
#     If value is file name, store file in settings.paths.logs/value.
#
#     If value is a special str such as stdout, convert to the object.
#
#     If it's needed to change folder of logfile, change environment variable.
#     Args:
#         value:
#     """
#     if value == "stdout":
#         value = sys.stdout
#     elif '/' not in value and '\\' not in value:
#         value = str(settings.paths.logs / value)
#     else:
#         raise ValidationError(f"The sink {value} is not the valid one.")
#     return value
#
# class LoggerHandler(BaseModel):
#     sink: Annotated[str | TextIO, AfterValidator(check_sink)]
#     level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]
#     add_kwargs: dict = dict()
#
#     model_config = ConfigDict(arbitrary_types_allowed=True)
#
#
# class LoggerConfig(BaseConfig):
#     handlers: list[LoggerHandler]
#
#     @staticmethod
#     def key() -> str:
#         return "logger"
#
# def logger_init(config:LoggerConfig,lger:type(loguru.logger) = loguru.logger ):
#     lger.remove()
#     log_configs=[]
#     for handler in config.handlers:
#         lger.add(handler.sink,
#                  level=handler.level,
#                  **handler.add_kwargs)
#         if not isinstance(handler.sink,str):
#             handler.sink=str(handler.sink)
#         log_configs.append(handler.model_dump_json(indent=1))
#     log_configs = "\n".join(log_configs)
#     lger.info(f"Logger is initialized with sinks:\n"
#                   f"{log_configs}")
#     return lger
#
#
#
# cfg = LoggerConfig.load("logger.toml")
# logger = logger_init(cfg)
#
from loguru import logger
import logging
import sys
# logger = logging.getLogger(__name__)
# def get_name():
#     print(f"logger name {__name__}")


# class InterceptHandler(logging.Handler):
#     def emit(self, record):
#         # Get corresponding Loguru level if it exists.
#         try:
#             level = logger.level(record.levelname).name
#         except ValueError:
#             level = record.levelno
#
#         # Find caller from where originated the logged message.
#         frame, depth = sys._getframe(6), 6
#         while frame and frame.f_code.co_filename == logging.__file__:
#             frame = frame.f_back
#             depth += 1
#
#         logger.opt(depth=depth, exception=record.exc_info).log(
#             level, record.getMessage()
#         )
#
# logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)


# logger.remove()
# logger.add(
#     sys.stdout,
#     level='DEBUG',
# )

__all__ = ["logger"]
