import pytest

from datastore.repo import UserRepo, TokenInfoAuthSuccess


pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture(scope="module")
def user_repo(chat_db_session):
    return UserRepo(chat_db_session)

async def test_create_user(random_user,user_repo):
    """Verify user existent before and after create."""

    assert (await user_repo.verify(username=random_user.username)) is False
    await user_repo.create(username=random_user.username, hashed_password=random_user.password)
    assert await user_repo.verify(username=random_user.username)

async def test_authenticate_user(random_user,user_repo):
    token_info = await user_repo.authenticate(username=random_user.username,
                                              hashed_password=random_user.password,
                                              token_duration_seconds=1000)
    assert isinstance(token_info, TokenInfoAuthSuccess)

    assert (await user_repo.authenticate(username="Nothing",
                                         hashed_password="nothing too",
                                         token_duration_seconds=1000)) is None


