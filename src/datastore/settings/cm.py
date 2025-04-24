from chatbone_utils.typing import SESSION_CONTEXTMANAGER
from .settings import datastore_settings


def get_session() -> SESSION_CONTEXTMANAGER:
	return datastore_settings.db.session()

