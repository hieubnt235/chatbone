from dotenv import find_dotenv
from pydantic import BaseModel, PositiveInt
from pydantic_settings import SettingsConfigDict

from utilities.settings import Settings, Config
from utilities.settings.clients.datastore import DatastoreClient


class DatastoreRequestTimeout(BaseModel):
	"""All in second."""
	create: PositiveInt = 30
	verify: PositiveInt = 30
	get: PositiveInt = 30
	delete: PositiveInt = 30
	delete_tokens: PositiveInt = 30


class AuthConfig(Config):
	token_duration_seconds: int = 86400
	jwt_encode_algorithm: str | None = None
	auth_secret_key: str = 'auth_secret_key'
	datastore_request_timeout: DatastoreRequestTimeout

	max_valid_tokens: int = 1  # NO USE RIGHT NOW.
	"""Maximum number of valid tokens exist at the same time."""


class AuthSettings(Settings):
	"""
	Base setting for all auth settings.
	"""
	model_config = SettingsConfigDict(env_prefix='auth_', env_file=find_dotenv('.env.auth'))
	service_name = 'auth'

	datastore: DatastoreClient
	config: AuthConfig


auth_settings = AuthSettings()
