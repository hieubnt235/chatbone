from abc import abstractmethod, ABC
from contextlib import asynccontextmanager, contextmanager
from typing import Literal, Generator, AsyncGenerator

from pydantic import model_validator, BaseModel, ConfigDict, Field
from sqlalchemy import URL, NullPool
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from chatbone.utils.exception import BaseMethodException, handle_exception
from chatbone.logger import logger
from chatbone.utils.typing import *


class SQLDBSettingsException(BaseMethodException):
    pass

class SQLDBSettings(BaseModel, ABC):
    drivername: Literal['postgresql+asyncpg', 'sqlite+aiosqlite']
    username: str | None = None
    password: str | None = None
    host: str | None = None
    port: int | None = None
    database: str | None = None
    url: str | URL = Field(...,exclude=False)

    model_config = ConfigDict(validate_default=True,
                              validate_assignment=True,
                              arbitrary_types_allowed=True
                              )

    engine: ENGINE|None = Field(default=None,exclude=True)
    session_maker: SESSION_MAKER|None = Field(default=None, exclude=True)

    @model_validator(mode='before')
    @classmethod
    @handle_exception(SQLDBSettingsException)
    def init_db(cls, env_vars: dict):
        try:
            if env_vars.get('url') is None:
                env_vars['url'] = \
                URL.create(*[env_vars.get(var)
                             for var in ['drivername', 'username', 'password',
                                         'host', 'port', 'database']])
            if env_vars.get('engine') or env_vars.get('session_maker') is None:
                env_vars['engine'] = cls._create_engine(env_vars['url'])
                env_vars['session_maker'] = cls._create_sessionmaker(env_vars['engine'])

            env_vars['url'] = str(env_vars['url']) # hide password
            env_vars['password'] = '*'*len(env_vars['password'])

        except Exception as e:
            logger.exception(e)
            raise
        return env_vars




    @classmethod
    @abstractmethod
    def _create_engine(cls,url:str|URL) -> ENGINE:
        pass

    @classmethod
    @abstractmethod
    def _create_sessionmaker(cls,engine: ENGINE) -> SESSION_MAKER:
        pass

    def _get_session(self) -> Generator[Session, ..., ...]:
        """Intent to use for dependency."""
        raise NotImplementedError

    async def _get_async_session(self)->AsyncGenerator[AsyncSession, ...]:
        """Intent to use for dependency."""
        raise NotImplementedError

    @property
    @handle_exception(SQLDBSettingsException)
    def session(self) -> SESSION_CONTEXTMANAGER:
        """Wrap self.get_session or self.get_async_session to contextmanager and return.
        """
        if self.__class__.__name__=="AsyncSQLDBSettings":
            return asynccontextmanager(self._get_async_session)
        else:
            return contextmanager(self._get_session)


class AsyncSQLDBSettings(SQLDBSettings):

    @classmethod
    @handle_exception(SQLDBSettingsException)
    def _create_engine(cls, url: str | URL) -> ENGINE:
        return create_async_engine(url,
                                   # poolclass=NullPool

                                   # echo=True,echo_pool=True
                                   )
    @classmethod
    @handle_exception(SQLDBSettingsException)
    def _create_sessionmaker(cls, engine: ENGINE) -> SESSION_MAKER:
        return async_sessionmaker(engine,autocommit=False,autoflush=False)


    async def _get_async_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Get session begun. According unit of work pattern.
        Session should be created and committed at the beginning and the end of request.

        Note: This method does not raise its own exception but just reraise.
        """
        session = None
        try:
            async with self.session_maker.begin() as session: # globally handle commit, rollback, and close.
                logger.debug(f"Session has begun.")
                yield session
            logger.debug(f"Session committed.")

        except Exception as e:
            logger.error(e)
            if not session:
                logger.debug("Session begin failed.")
            else:
                logger.debug("Session rolled back.")
            raise
        finally:
            if session:
                logger.debug("Session closed.\n")



class SyncSQLDBSettings(SQLDBSettings):
    @classmethod
    def _create_engine(cls, url: str | URL) -> ENGINE:
        pass

    @classmethod
    def _create_sessionmaker(cls, engine: ENGINE) -> SESSION_MAKER:
        pass

    def _get_session(self) -> Generator[Session, ..., ...]:
        pass
