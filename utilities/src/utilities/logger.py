from __future__ import annotations
import inspect
import logging
import os
import sys

import loguru
from loguru import logger


# copy from https://loguru.readthedocs.io/en/stable/overview.html
class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        # Get corresponding Loguru level if it exists.
        level: str | int
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = inspect.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, "\n" + record.getMessage()
        )


logger_info_set = ["uvicorn", "starlette", "flet", "ray"]
logger_debug_set = []


def is_info_logger(name: str):
    for l in logger_info_set:
        if l in name:
            return True
    return False


def is_debug_logger(name: str):
    for l in logger_debug_set:
        if l in name:
            return True
    return False

__setup__=False

def setup_loguru_logging(level=None):
    # for handler in logging.root.handlers[:]:
    #     logging.root.removeHandler(handler)
    # logging.root.addHandler(InterceptHandler())
    # logging.root.setLevel(logging.NOTSET)  # Capture all levels at the root
    #
    # # Iterate over all existing standard loggers (e.g., uvicorn, flet, starlette, etc.)
    # # and ensure they propagate their messages to the root logger and have no other handlers.
    # for name in logging.Logger.manager.loggerDict.keys():
    #     current_logger = logging.getLogger(name)
    #     if isinstance(current_logger, logging.Logger):
    #         # Remove any handlers directly attached to these loggers
    #         for handler in current_logger.handlers[:]:
    #             current_logger.removeHandler(handler)
    #         # Ensure messages propagate up to the root logger
    #         current_logger.propagate = True
    #         # Set their minimum level to NOTSET so they don't filter out messages too early
    #         current_logger.setLevel(logging.NOTSET)
    global __setup__
    if __setup__:
        return
    
    if not (level:=os.getenv("CHATBONE_LOG_LEVEL")):
        return
    
    logging.basicConfig(handlers=[InterceptHandler()], level=logging.NOTSET, force=True)
    logger.remove()

    def log_filter(record: loguru.Record) -> bool:
        name = record.get("name")
        level_no = record["level"].no
        # print(f"Log filter: name={name}, level={level_no}")
        if name:
            if is_info_logger(name):
                return level_no >= logger.level("INFO").no

            if is_debug_logger(name):
                return level_no >= logger.level("DEBUG").no

        # Does not have a name, or name is not prespecified

        return level_no >= logger.level("WARNING").no

    logger.add(sys.stderr, level=level, filter=log_filter)
    # print(f"Log level={level}")
    __setup__ = True

setup_loguru_logging()
