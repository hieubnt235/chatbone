from uuid import UUID
import pytest
from fastapi import HTTPException

from chatbone.auth.dependencies import make_user_credentials_register
from chatbone.auth.schemas import  UserCredentials
from chatbone.auth.service import AuthenticationService
from chatbone import UsernameNotFoundError, AuthenticationError, AlreadyRegisterError, TokenError

pytestmark = pytest.mark.asyncio(loop_scope="session")

async def test_auth_service(chat_db_session, random_user):
    auth_service = AuthenticationService(chat_db_session)
    user_cre = make_user_credentials_register(random_user)

    # test register
    await auth_service.register(user_cre)
    with pytest.raises(HTTPException) as e:
        await auth_service.register(user_cre) # register duplicate
    assert e.value==AlreadyRegisterError

    # test authenticate
    token_info = await auth_service.authenticate(user_cre)
    assert token_info is not None

    with pytest.raises(HTTPException) as e:
        await auth_service.authenticate(UserCredentials(username="xyz",
                                                        hashed_password=user_cre.hashed_password))
    assert e.value==UsernameNotFoundError

    with pytest.raises(HTTPException) as e:
        await auth_service.authenticate(UserCredentials(username=user_cre.username,
                                                        hashed_password="stuff"))
    assert e.value==AuthenticationError

    # test decode
    token_id = await auth_service.decode_jwt_token(token_info)
    assert isinstance(token_id,UUID)

    with pytest.raises(HTTPException) as e:
        await auth_service.decode_jwt_token("this is not jwt access token.")
    assert e.value==TokenError

