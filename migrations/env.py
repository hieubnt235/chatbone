import asyncio
from logging.config import fileConfig
import logging
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

from chatbone.settings import chatbone_settings
from chatbone.repositories.entities.chat import Base as ChatBase
from chatbone.repositories.entities.storage import Base as DocumentBase

config = context.config
# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


logger = logging.getLogger('alembic')
# Custom#########
db_metadata = dict(
    chat_db=ChatBase.metadata,
    document_db=DocumentBase.metadata
)

db_name = config.config_ini_section
try:
    config.set_main_option("sqlalchemy.url",
                           getattr(chatbone_settings, db_name)
                           .engine.url
                           .render_as_string(hide_password=False))
except Exception as e:
    logger.error(e)
    raise

target_metadata = db_metadata[db_name]
################


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


run_migrations_online()
