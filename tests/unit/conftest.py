import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from utilities.logger import logger
import pytest
from utilities.settings import chatbone_settings

def pytest_collection_modifyitems(config, items) -> None:
    assert isinstance(config,type(config)) #dump used
    ids = []
    for item in items:
        if "unit/" in item.nodeid:
            item.add_marker(pytest.mark.unit)
            ids.append(item.nodeid)
    logger.debug(f"\nMarked \'unit\' for {len(ids)} items:\n"
                 f"{"\n".join(ids)}")


@pytest_asyncio.fixture(scope="module",loop_scope="session")
async def chat_db_session():
    """Manage the beginning and the end of transaction.
    Session should be used without commit, this manager will roll back everything at the end.
    """
    session:AsyncSession|None=None
    async with chatbone_settings.chat_db.session() as session:
        try:
            yield session
        except Exception as e:
            logger.exception(e)
        finally:
            assert session is not None
            await session.rollback()
            logger.debug(f"Chat db session rolled back after tests.")
