from datetime import datetime
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import select, and_, delete

from datastore.entities import AccessToken, User
from utilities.exception import handle_exception, BaseMethodException
from utilities.func import utc_now
from utilities.mixin import RepoMixin


class TokenRepoException(BaseMethodException):
	pass


class TokenRepo(RepoMixin):

	@handle_exception(TokenRepoException)
	async def create(self, user: User, expires_at: datetime) -> AccessToken:
		"""
		Create new access token and return. DO NOT CHECK THE expires_at. Client have to do it.
		Args:
		 expires_at:
			user: Can be gotten by using UserRepo.get_verify or UserRepo.create
		Returns:
			New AccessToken object
		"""
		await self._session.refresh(user)
		self._session.add(user)

		token = AccessToken(expires_at=expires_at)
		user.tokens.append(token)

		await self.flush()
		await self.refresh(token)
		return token

	@handle_exception(TokenRepoException)
	async def get_verify(self, token_id: UUID) -> AccessToken | None:
		"""Retrieve a token if it exists and hasn't expired. All service should use this to verify token
		and get User through AccessToken.user .
		Args:
			token_id (UUID): The ID of the token to retrieve.

		Returns:
			AccessToken | None: The token if it exists and hasn't expired, otherwise None.
		"""
		q = select(AccessToken).where(and_(AccessToken.id == token_id, AccessToken.expires_at > utc_now()))
		token = await self._session.scalar(q)
		await self._session.refresh(token.user)
		return token

	@handle_exception(TokenRepoException)
	async def delete(self, user: User, token_ids: list[UUID]):
		"""Delete tokens if user own this. THIS METHOD JUST DELETE AND DON'T CHECK WHOSE TOKEN IS. SERVICE HAS TO CHECK IT.
		Args:
		 user:
		 token_ids:
		"""
		q = delete(AccessToken).where(and_(AccessToken.id.in_(token_ids), AccessToken.user_id == user.id))
		await self._session.execute(q)
		await self.flush()

	@handle_exception(TokenRepoException)
	async def flush(self):
		await self._session.flush()

	@handle_exception(TokenRepoException)
	async def refresh(self, obj: Any):
		await self._session.flush()


class TokenRepoAdminException(BaseMethodException):
	pass


class TokenRepoAdmin(TokenRepo):
	@handle_exception(TokenRepoAdminException)
	async def get_all_tokens(self) -> Sequence[AccessToken]:
		result = await self._session.scalars(select(AccessToken))
		return result.all()

	@handle_exception(TokenRepoAdminException)
	async def delete_all_tokens(self):
		await self._session.execute(delete(AccessToken))
		await self.flush()

	@handle_exception(TokenRepoAdminException)
	async def delete_expired_tokens(self):
		"""Delete all tokens that expired"""
		q = delete(AccessToken).where(AccessToken.expires_at < utc_now())
		await self._session.execute(q)
		await self._session.flush()
