from abc import ABC
from uuid import UUID

from sqlalchemy import select, and_, delete, exists

from chatbone.utils import handle_exception, BaseMethodException, RepoMixin, utc_now
from .entities.chat import AccessToken, User


class TokenRepoException(BaseMethodException):
    pass    

class _TokenRepo(RepoMixin, ABC):
    """Abstract base class for token repository operations.

    - Supports manipulating AccessToken and User objects, which are the entry points to access the real resources.
    - All repositories excluding UserRepo should inherit this class.
    - Method of this class should not be used directly.
    """

    @handle_exception(TokenRepoException)
    async def verify_token(self, token_id:UUID)-> bool:
        """
        Returns: True if token is valid, otherwise return False.
        """

        return await self._session.scalar(select(exists().where(AccessToken.id==token_id)))

    @handle_exception(TokenRepoException)
    async def _get_token(self, token_id: UUID) -> AccessToken | None:
        """Retrieve a token if it exists hasn't expired.

        Args:
            token_id (UUID): The ID of the token to retrieve.

        Returns:
            AccessToken | None: The token if it exists and hasn't expired, otherwise None.
        """
        q = select(AccessToken).where(and_(AccessToken.id == token_id,
                                           AccessToken.expires_at>utc_now()))
        return await self._session.scalar(q)

    @handle_exception(TokenRepoException)
    async def _get_user(self, token_id:UUID)-> User|None:
        """Retrieve a User if the token is valid and the user is available.
        Args:
            token_id (UUID): The ID of the token to validate.

        Returns:
            User | None: The user associated with the token if valid, otherwise None.
        """
        if (token := await self._get_token(token_id)) is None:
            return None
        else:
            q = select(User).where(User.id==token.user_id)
            return await self._session.scalar(q)

    @handle_exception(TokenRepoException)
    async def _delete_expired(self):
        """Delete all tokens that expired"""
        q = delete(AccessToken).where(AccessToken.expires_at<utc_now())
        await self._session.execute(q)
        await self._session.flush()


    @handle_exception(TokenRepoException)
    async def _delete(self, token_id: UUID):
        """Delete one token"""
        token = await self._get_token(token_id)
        if token is not None:
            await self._session.delete(token)
            await self.flush()
