from typing import AsyncContextManager, ContextManager, Generator, AsyncGenerator, Callable, Coroutine

from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import sessionmaker, Session

ENGINE = Engine | AsyncEngine
SESSION_MAKER = async_sessionmaker | sessionmaker
SESSION = Session|AsyncSession

SESSION_CONTEXTMANAGER = ContextManager[Session] | AsyncContextManager[AsyncSession]
SESSION_GENERATOR = Generator[Session, ..., ...]|AsyncGenerator[AsyncSession, ...]
FUNCTYPE = Callable| Callable[..., Coroutine]


__all__=['ENGINE',
         'SESSION_MAKER',
         'SESSION_GENERATOR',
         'SESSION',
         'SESSION_CONTEXTMANAGER',
         'SESSION_GENERATOR',
         'FUNCTYPE']