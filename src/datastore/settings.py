from dotenv import find_dotenv
from pydantic_settings import SettingsConfigDict

from utilities.settings import AsyncSQLDBSettings, Settings, Config


class DatastoreConfig(Config):
	pass


class DatastoreSettings(Settings):
	"""
	Base setting for all datastore settings.
	"""
	model_config = SettingsConfigDict(env_prefix='datastore_', env_file=find_dotenv('.env.datastore'))
	service_name = 'datastore'

	db: AsyncSQLDBSettings

	config: DatastoreConfig


datastore_settings = DatastoreSettings()
