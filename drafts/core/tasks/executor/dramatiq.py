from typing import Literal, Type

import dramatiq as dmt
from dramatiq.brokers.rabbitmq import RabbitmqBroker
from dramatiq.brokers.redis import RedisBroker

from .executor import BaseExecutor, BaseExecutorFactory
from chatbone.settings import settings


# from  dramatiq.middleware import default_middleware
# from dramatiq.cli import

class DramatiqExecutorFactory(BaseExecutorFactory):
    type: Literal['dramatiq']


    def setup(self,
              middleware: list[dmt.Middleware] =None,
              **kwargs) -> None:

        broker_kwargs = {k: v for k, v in settings.broker.dict().items()
                         if v is not None}
        broker_kwargs.update(kwargs)
        self.broker_config.update(broker_kwargs)

        t = broker_kwargs.pop('type')
        if t == 'redis':
            broker = RedisBroker(middleware=middleware, **broker_kwargs)
        elif t == 'rabbitmq':
            broker = RabbitmqBroker(middleware=middleware, **broker_kwargs)
        else:
            raise ValueError(f"Dramatiq only support rabbitmq or redis broker, but get {t}.")
        dmt.set_broker(broker)

        # Storing middleware info to broker_config
        if middleware is None:
            middleware =[m.__name__ for m in dmt.middleware.default_middleware]
        else:
            middleware=[m.__class__.__name__ for m in middleware]

        self.broker_config['middleware'] = middleware



    def make_real_executor(self, *args, **kwargs) -> any:
        return dmt.actor(*args,**kwargs)

    @property
    def executor_cls(self) -> Type[BaseExecutor]:
        return DramatiqExecutor


class DramatiqExecutor(BaseExecutor):
    def __call__(self, *args, **kwargs):
        self._executor.send(*args,**kwargs)

    @property
    def logger(self, *args, **kwargs) -> any:
        return self._executor.logger


