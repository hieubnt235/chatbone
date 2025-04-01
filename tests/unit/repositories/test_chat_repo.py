from uuid import UUID

from uuid_extensions import uuid7

from chatbone.repositories import UserRepo, ChatRepo, TokenInfoAuthSuccess

import pytest
import random

pytestmark = pytest.mark.asyncio(loop_scope="session")

@pytest.fixture(scope="module")
def chat_repo(chat_db_session):
    return ChatRepo(chat_db_session)

@pytest.fixture(scope="module")
def token_id()->list:
    return []

@pytest.fixture(scope="module")
def chat_ids()-> list:
    return []

@pytest.fixture(scope="module")
def messages()->list:
    return []

async def test_create_token_id(random_user, chat_db_session,token_id) :
    user_repo = UserRepo(chat_db_session)  # This is already tested in test_user_repo.py
    # Create user and token id
    await user_repo.create(username=random_user.username, hashed_password=random_user.password)
    token_info = await user_repo.authenticate(username=random_user.username,
                                              hashed_password=random_user.password,
                                              token_duration_seconds=1000)
    assert isinstance(token_info, TokenInfoAuthSuccess)
    token_id.append(token_info.id)


async def test_create_chat_sessions(chat_repo,token_id,chat_ids):
    assert (await chat_repo.verify_token(token_id[0]))

    # Create 5 chat sessions
    chat_ids.extend([await chat_repo.create_chat_session(token_id=token_id[0]) for _ in range(5)])
    assert all(isinstance(i, UUID) for i in chat_ids)

    # Reload chat ids from backend and check.
    assert chat_ids == await chat_repo.list_chat_sessions(token_id=token_id[0])


async def test_delete_sessions(chat_repo,chat_ids,token_id):
    # Delete 3 sessions
    await chat_repo.delete_chat_sessions(chat_ids=chat_ids[3:])
    remain_session_ids = await chat_repo.list_chat_sessions(token_id=token_id[0])
    assert remain_session_ids== chat_ids[:3]

# Auxiliaries
def _fake_messages(n):
    return [dict(role=random.choice(["system", "user", "assistant"]),
                 content=str(uuid7()))
            for _ in range(n)]

async def test_create_and_get_messages(chat_repo, chat_ids,messages):
    n = 50  # number of created messages
    l = 10  # number of gotten latest messages

    # Get blank messages
    assert await chat_repo.get_messages(chat_id=chat_ids[0]) == []

    # Create message
    fm = _fake_messages(n)
    for m in fm:
        messages.append(await chat_repo.create_message(chat_id=chat_ids[0], **m))

    # Get l latest messages
    messages_get = await chat_repo.get_messages(chat_id=chat_ids[0], limit=l)
    assert messages_get == messages[:-(l+1):-1]


# Auxiliaries
def _sample_idx(n, l):
    assert n < l
    return random.sample(list(range(l)), n)

async def test_delete_messages(token_id,chat_ids, chat_repo,messages):
    d = 25  # Number of deleted messages

    delete_ids = _sample_idx(d, len(messages))
    remain_ms = [messages[i] for i in range(len(messages)) if i not in delete_ids]

    # delete
    await chat_repo.delete_messages(message_ids=[messages[i].id for i in delete_ids])

    # get
    messages_remain_getr = await chat_repo.get_messages(chat_id=chat_ids[0], limit=-1)
    assert messages_remain_getr == remain_ms[::-1]
