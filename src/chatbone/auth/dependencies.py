from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

from chatbone.settings.dependencies import ChatDBSessionDep
from chatbone.utils import hash_password
from chatbone import handle_http_exception, ServerError
from .schemas import UserCredentials, AuthenticatedToken, UserIn
from .service import AuthenticationService


@handle_http_exception(ServerError)
def get_auth_service(session: ChatDBSessionDep)->AuthenticationService:
    return AuthenticationService(session)

@handle_http_exception(ServerError)
def make_user_credentials_login(form: Annotated[OAuth2PasswordRequestForm,Depends()])->UserCredentials:
    return UserCredentials(username=form.username,hashed_password=hash_password(form.password))

@handle_http_exception(ServerError)
def make_user_credentials_register(user:UserIn):
    return UserCredentials(username=user.username, hashed_password=hash_password(user.password))


AuthServiceDep = Annotated[AuthenticationService, Depends(get_auth_service)]
"""Return the AuthenticationService object."""
Oauth2BearerDep = Annotated[str, Depends(OAuth2PasswordBearer(tokenUrl="token"))]
"""OAuth2PasswordBearer, return the JWT string or go to url 'token' endpoint. """
UserCredentialsLoginDep=Annotated[UserCredentials, Depends(make_user_credentials_login)]
"""Receive OAuth2PasswordRequestForm from bearer create UserCredentials for authenticating."""
UserCredentialsRegisterDep=Annotated[UserCredentials, Depends(make_user_credentials_register)]
"""Receive login from user and create UserCredentials for register."""

async def register(user_cre: UserCredentialsRegisterDep, auth_service: AuthServiceDep)-> AuthenticatedToken:
    await auth_service.register(user_cre)
    return await auth_service.authenticate(user_cre)

async def authenticate(user_cre: UserCredentialsLoginDep, auth_service: AuthServiceDep) -> AuthenticatedToken:
    jwt_token =  await auth_service.authenticate(user_cre)
    return AuthenticatedToken(access_token=jwt_token,token_type="bearer")

async def get_token_id(jwt_token: Oauth2BearerDep, auth_service: AuthServiceDep) -> UUID:
    return await auth_service.decode_jwt_token(jwt_token)


RegisterDep=Annotated[UUID, Depends(register)]
"""Register and login, return AuthenticatedToken object which include "access_token" (JWT) and "type" ("bearer"). """
AuthenticateDep = Annotated[AuthenticatedToken, Depends(authenticate)]
"""Receive OAuth2PasswordRequestForm and return AuthenticatedToken object which include "access_token" (JWT) and "type" ("bearer"). """
TokenIdDep = Annotated[UUID, Depends(get_token_id)]
"""Get token id from jwt (from header or bearer). This dependency should be used to protect endpoint."""

__all__=["RegisterDep", "AuthenticateDep", "TokenIdDep"]



