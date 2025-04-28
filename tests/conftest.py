from utilities import logger
import pytest
import uvloop
from uuid_extensions import uuid7
from auth import UserIn

@pytest.fixture(scope="session")
def event_loop_policy():
    return uvloop.EventLoopPolicy()

@pytest.fixture(scope='module')
def random_user()->UserIn:
    username = str(uuid7())[:30]
    password = str(uuid7())[:32]
    user = UserIn(username=username,password=password )
    logger.debug(f"\nNew test user created:\n"
                f"username={username}\n"
                f"password={password}")
    return user

