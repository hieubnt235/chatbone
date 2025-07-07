# logger_config_loguru.py
import inspect
import logging
import sys

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
            level, "\n"+record.getMessage()
        )


logger_info_set = ["uvicorn", "starlette", "flet", "ray"]
logger_debug_set = []


def is_info_logger(name: str):
    for l in logger_info_set:
        if name.startswith(l):
            return True
    return False


def is_debug_logger(name: str):
    for l in logger_debug_set:
        if name.startswith(l):
            return True
    return False


def setup_loguru_logging():
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    logging.root.addHandler(InterceptHandler())
    logging.root.setLevel(logging.NOTSET)  # Capture all levels at the root

    # Iterate over all existing standard loggers (e.g., uvicorn, flet, starlette, etc.)
    # and ensure they propagate their messages to the root logger and have no other handlers.
    for name in logging.Logger.manager.loggerDict.keys():
        current_logger = logging.getLogger(name)
        if isinstance(current_logger, logging.Logger):
            # Remove any handlers directly attached to these loggers
            for handler in current_logger.handlers[:]:
                current_logger.removeHandler(handler)
            # Ensure messages propagate up to the root logger
            current_logger.propagate = True
            # Set their minimum level to NOTSET so they don't filter out messages too early
            current_logger.setLevel(logging.NOTSET)

    logger.remove()
    logger.add(
        sys.stderr,
        level="DEBUG",
        filter=lambda record: (
            record["name"]
            and is_info_logger(record["name"])
            and record["level"].no >= logger.level("INFO").no
        )
        or (
            record["name"]
            and is_debug_logger(record["name"])
            and record["level"].no >= logger.level("DEBUG").no
        )
        or (not record["name"] and record["level"].no >= logger.level("WARNING").no),
    )
