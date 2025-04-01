from typing import Literal

from .executor import BaseExecutor, BaseExecutorFactory


class CeleryExecutorFactory(BaseExecutorFactory):
    type: Literal['celery']

    def setup(self, *args, **kwargs) -> None:
        pass

    def make_real_executor(self, *args, **kwargs) -> any:
        pass

    @property
    def executor_cls(self) -> type[BaseExecutor]:
        pass


class CeleryExecutor(BaseExecutor):

    def __init__(self, executor: any):
        pass

    def run(self, *args, **kwargs):
        pass