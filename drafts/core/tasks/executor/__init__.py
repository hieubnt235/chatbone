from utilities import logger
from .executor import ExecutorConfig, executor_init

cfg = ExecutorConfig.load('executor.toml')

executor = executor_init(cfg)
logger.info(f"The executor is initialized with  config:\n"
            f"{executor.model_dump_json(indent=4)}")
