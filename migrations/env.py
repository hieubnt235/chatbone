import asyncio
import json
from logging.config import fileConfig
import logging
from sqlalchemy import pool, URL
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

# from chatbone_utils.settings import chatbone_settings
from datastore.entities import Base as DatastoreBase

# from datastore.entities import Base as DocumentBase

config = context.config
# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
	fileConfig(config.config_file_name)

logger = logging.getLogger('alembic')

#######START CUSTOM SECTION#########

# Mapping between table in alembic.ini (config_ini_section) to metadata
db_metadata = dict(datastore_db=DatastoreBase.metadata,  # document_db=DocumentBase.metadata
                   )
# Get db_name through table name ( using -n)
db_name = config.config_ini_section

# Get config dict through table name.
cfg_dict = config.get_section(db_name)
logger.info(f"\nLoaded section {db_name} from alembic.ini:\n"
            f"{json.dumps(cfg_dict, indent=4)}")

# Create sqlalchemy.url and set it at main option for future usage.
try:
	url_params = [cfg_dict.get(var) for var in ['drivername', 'username', 'password', 'host', 'port', 'database']]
	url_params[4]= int(url_params[4])
	url = URL.create(*url_params).render_as_string(hide_password=False)
	config.set_main_option("sqlalchemy.url", url)
	logger.info(f"\'sqlalchemy.url\' is set as \'{url}\'")
except Exception as e:
	logger.error(e)
	raise

# Get metadata
target_metadata = db_metadata[db_name]

""" Run with:
alembic -n chat_db revision --autogenerate -m "First migration"
alembic -n chat_db upgrade head
"""
#######END CUSTOM SECTION#########

def do_run_migrations(connection: Connection) -> None:
	context.configure(connection=connection, target_metadata=target_metadata)

	with context.begin_transaction():
		context.run_migrations()


async def run_async_migrations() -> None:
	"""In this scenario we need to create an Engine
	and associate a connection with the context.

	"""

	connectable = async_engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.",
	                                       poolclass=pool.NullPool, )

	async with connectable.connect() as connection:
		await connection.run_sync(do_run_migrations)

	await connectable.dispose()


def run_migrations_online() -> None:
	"""Run migrations in 'online' mode."""

	asyncio.run(run_async_migrations())


run_migrations_online()
