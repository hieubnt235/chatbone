__all__ = ["TokenError", "InvalidRequestError", "BaseSVC"]

import asyncio
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from datastore.entities import AccessToken
from datastore.repo import TokenRepo
from utilities.func import check_is_subset

TokenError = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token is not valid.")
InvalidRequestError = HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid request.")
ServerError = HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Something went wrong with server.")


class BaseSVC:
	def __init__(self, session: AsyncSession):
		self.token_repo = TokenRepo(session)

	async def _get_token(self, token_id: UUID) -> AccessToken:
		"""Retrieve a token if it exists and hasn't expired. All service should use this to verify token
		and get User through AccessToken.user .
		Args:
			token_id (UUID): The ID of the token to retrieve.

		Returns:
			AccessToken | None: The token if it exists and hasn't expired, otherwise None.
		Raises:
			TokenError: If it cannot get any valid token.
		"""
		if (token := await self.token_repo.get_verify(token_id)) is None:
			raise TokenError
		return token

	# noinspection PyMethodMayBeStatic
	async def _check_valid_request(self, user_req: list[Any], user_own: list[Any], *, req_key: str | None = None,
	                               own_key: str | None = None):
		"""
		User request must be a subset of user own. If not, raise InvalidRequestError.
		Used for valid whether user own object before delete.
		No need to use when getting object. The get method in repo already check it, if user not own object, it will return None.
		Args:
			user_own:
			user_req:
		Raises:
			InvalidRequestError:
		Returns:
		"""
		if not await asyncio.to_thread(check_is_subset, user_req, user_own, key1=req_key, key2=own_key):
			raise InvalidRequestError
