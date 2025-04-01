from abc import ABC, abstractmethod
from typing import Type

from pydantic import Field

from src.chatbone import BaseConfig


class BaseExecutor(ABC):
    """
    Executor wrapper to provide unify interfaces for all taskqueue frameworks.
    """
    def __init__(self,*,real_executor: any):
        """
        Args:
            real_executor: The real executor of the framework.
        """
        self._executor= real_executor
    @abstractmethod
    def __call__(self,*args,**kwargs):
        """Send task message to Worker server. Using concrete self._executor.
        This method should not block the process for a long time.
        """
        pass

    @property
    def logger(self,*args,**kwargs)-> any:
        """Return executor logger for logging"""
        raise NotImplementedError

class BaseExecutorFactory(BaseConfig):
    """
    Derive class has to declare type:Literal['anything'].
    It will be used for discriminator.
    """
    type:str
    n_threads:int
    n_processes:int

    broker_config: dict=Field(default_factory=dict)
    default_executor_params: dict=Field(default_factory=dict)


    @staticmethod
    def key() -> str:
        return "executor"

    @abstractmethod
    def setup(self,*args, **kwargs)->None:
        """Set up the framework and store all parameters were used for setting."""

    @abstractmethod
    def make_real_executor(self,*args,**kwargs)->any:
        """Create a real executor of the framework and setting up."""

    @property
    @abstractmethod
    def executor_cls(self)->Type[BaseExecutor]:
        """Executor class"""

    def __call__(self, *args, **kwargs)->BaseExecutor:
        """Decorator of normal function to make it an executor."""
        params = (self.default_executor_params.copy())
        params.update(**kwargs)

        real_exe = self.make_real_executor(*args,**params)
        return self.executor_cls(real_executor=real_exe)



from .dramatiq import DramatiqExecutorFactory
from .celery import CeleryExecutorFactory
class ExecutorConfig(BaseConfig):
    """Executor config discriminator (factory)"""

    factory :DramatiqExecutorFactory|CeleryExecutorFactory = Field(discriminator='type')

    def __init__(self,**kwargs):
        super().__init__(factory=kwargs)

    @staticmethod
    def key() -> str:
        return "executor"



def executor_init(config:ExecutorConfig,
                  *args,
                  **kwargs) -> BaseExecutorFactory:
    """
    Setup framework and return the BaseExecutorFactory whose __call__() method is
    the decorator which will be used to decorate the functions(tasks).

    Args:
        config:
        *args: passed to factory.setup()
        **kwargs: passed to factory.setup()
    Returns:
        Derived class of BaseExecutorFactory.
    """
    config.factory.setup(*args,**kwargs)

    return config.factory
