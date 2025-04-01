from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select, and_, exists

from chatbone.utils import handle_exception, get_expire_date, BaseMethodException, RepoMixin
from .entities.chat import *


class TokenInfoAuthSuccess(BaseModel):
    """
    Model representing the token information upon successful authentication.
    Attributes:
        username (str): The username of the authenticated user.
        id (UUID): The unique identifier of the token.
        created_at (datetime): The creation timestamp of the token.
        expires_at (datetime): The expiration timestamp of the token.
    """
    username:str
    id: UUID
    created_at:datetime
    expires_at:datetime

class UserRepoException(BaseMethodException):
    pass

class UserRepo(RepoMixin):
    """This repository supports basic OAuth2 operations such as user registration, verification,
    and token creation. It only returns the AccessToken.id .
    Direct user access is restricted and should be done through an AccessToken object.
    For admin usage, a new repository should be created.

        Methods:
            create(username: str, hashed_password: str) -> None:
                Create a new user and add it to the session.

            verify(username: str) -> bool:
                Check if a user already exists by username.

            authenticate(username: str, hashed_password: str, token_duration_seconds: int) -> TokenInfoAuthSuccess | None:
                Verify the user and create a token if successful. Return token information or None if verification fails.
    """
    @handle_exception(UserRepoException)
    async def create(self, *,
                     username: str,
                     hashed_password: str) -> None:
        """Create a new user with hashed password.
        Args:
            username (str): The username of the new user.
            hashed_password (str): The hashed password of the new user.
        """
        self._session.add(User(username=username,
                              hashed_password=hashed_password))
        await self.flush()

    @handle_exception(UserRepoException)
    async def verify(self, *, username: str) -> bool:
        """Check if a user already exists by username. Should be called before creating a new user.
        Args:
            username (str): The username to check for existence.
        Returns:
            bool: True if the user exists, False otherwise.
        """
        q = select(exists().where(User.username == username))
        return await self._session.scalar(q)

    @handle_exception(UserRepoException)
    async def authenticate(self, *,
                           username: str,
                           hashed_password: str,
                           token_duration_seconds: int) -> TokenInfoAuthSuccess|None:
        """Verify the user. If successful, create and return token information for JWT creation later.
        Return None if verification fails.

        Args:
            username (str): The username of the user.
            hashed_password (str): The hashed password of the user.
            token_duration_seconds (int): The duration in seconds for which the token is valid.

        Returns: TokenInfoAuthSuccess if credentials is valid or none
        """
        q = select(User).where(and_(User.username == username, User.hashed_password == hashed_password))
        if (user := await self._session.scalar(q)) is None:
            return None
        token = AccessToken(expires_at=get_expire_date(token_duration_seconds))
        user.tokens.append(token)
        await self.flush()
        await self.refresh(token)

        ti= token.as_dict()
        ti.pop('user_id')
        ti['username'] = username

        return TokenInfoAuthSuccess.model_validate(ti)

    @handle_exception(UserRepoException)
    async def flush(self):
        await self._session.flush()

    @handle_exception(UserRepoException)
    async def refresh(self, obj:Any):
        await self._session.flush()


__all__ = ["TokenInfoAuthSuccess","UserRepo","UserRepoException"]