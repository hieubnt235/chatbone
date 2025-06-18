import logging
import sys
import os
from loguru import logger

# LOG_LEVEL = os.getenv("CHATBONE_LOG_LEVEL") or "DEBUG"
LOG_LEVEL = "INFO"
# LOG_LEVEL = "DEBUG"

logger.remove()

logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level=LOG_LEVEL,  # Set the level Loguru itself will handle
)


class InterceptHandler(logging.Handler):
    def emit(self, record):
        # Get corresponding Loguru level if it exists.
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message.
        frame, depth = sys._getframe(6), 6
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)


# for logger_name in ["uvicorn", "uvicorn.access","uvicorn.error", "fastapi", "asyncio","starlette"]:
#     _logger = logging.getLogger(logger_name)
#     _logger.propagate = False
#     _logger.handlers = [InterceptHandler()]


__all__ = ["logger"]
