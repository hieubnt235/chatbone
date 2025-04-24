import asyncio

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from chatbone_utils.logger import logger
from chatbone_utils.datastore.schemas.user_svc import *
from chatbone_utils.exception import handle_http_exception, find_root_pre_exp
from chatbone_utils.func import utc_now
from datastore.entities import User, AccessToken, UserSummary
from datastore.repo import UserRepo, UserRepoException
from .base import BaseSVC, ServerError


##### HELPER SCHEMAS CONVERTERS

def _make_user_info(user: User) -> UserInfoReturn:
	return UserInfoReturn(**user.as_dict(),
	                      chat_ids=[s.id for s in user.chat_sessions],
	                      tokens=[TokenInfoReturn.model_validate(token, from_attributes=True) for token in
	                              user.tokens], )


def _make_user_summaries(summaries: list[UserSummary]) -> UserSummariesReturn:
	return UserSummariesReturn(summaries=[UserSummaryReturn.model_validate(s) for s in summaries])


def _should_create_token(flag: Literal['always', 'if_empty', "if_all_expired", "none"],
                         tokens: list[AccessToken]) -> bool:
	if flag == 'none':
		return False
	if flag == 'always' or (flag == 'if_empty' and len(tokens) == 0):
		return True

	if flag == 'if_all_expired':
		for token in tokens:
			# if any token still valid, return False.
			# logger.debug(utc_now())
			# logger.debug(token.expires_at)
			if utc_now() < token.expires_at:
				return False
		return True
	raise


##### EXCEPTION

AlreadyRegisterError = HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already register.")

UserNotExistError = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Username not found.")

VerifyFailError = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Username or hash password is not correct.")


##### SVC

class UserSVC(BaseSVC):
	def __init__(self, session: AsyncSession):
		super().__init__(session)
		self.user_repo = UserRepo(session)


class UserAccessSVC(UserSVC):
	"""
	Service class for user access-related operations.
    Methods:
        - create_user: Creates a new user and their first token.
        - verify_user: Verifies a user and optionally creates a new token.
        - get_user: Retrieves user information based on a token.
        - delete_user: Deletes a user based on a token.
        - delete_tokens: Deletes specific tokens owned by a user.
	"""
	@handle_http_exception(ServerError)
	async def create_user(self, schema: UserCreate) -> UserInfoReturn:
		"""
        Creates a new user and their first token.

        Args:
            schema (UserCreate): Schema containing user creation details.

        Returns:
            UserInfoReturn: The created user's information.

        Raises:
            AlreadyRegisterError: If the user is already registered.
		"""
		try:
			user = await self.user_repo.create(schema.username, schema.hashed_password)
			_ = await self.token_repo.create(user, schema.expires_at)
			await self.user_repo.refresh(user)
			return await asyncio.to_thread(_make_user_info, user)
		# User already exist error will be caught inside user_repo.create (IntegrityError).
		except UserRepoException as e:
			if isinstance(find_root_pre_exp(e),IntegrityError):
				raise AlreadyRegisterError
			else:
				raise

	@handle_http_exception(ServerError)
	async def verify_user(self, schema: UserVerify) -> UserInfoReturn:
		"""
        Verifies a user and optionally creates a new token.

        Args:
            schema (UserVerify): Schema containing user verification details.

        Returns:
            UserInfoReturn: The verified user's information.

        Raises:
            UserNotExistError: If the user does not exist.
            VerifyFailError: If the username or password is incorrect.
		"""
		if not (await self.user_repo.is_existing(schema.username)):
			raise UserNotExistError
		if (user := await self.user_repo.get_verify(schema.username, schema.hashed_password)) is None:
			raise VerifyFailError

		if await asyncio.to_thread(_should_create_token, schema.create_token_flag, user.tokens):
			_ = await self.token_repo.create(user, schema.expires_at)
		return await asyncio.to_thread(_make_user_info, user)

	@handle_http_exception(ServerError)
	async def get_user(self, schema: Token) -> UserInfoReturn:
		"""
		Retrieves user information based on a token. Return user info if token is valid.
		Different from verify_user by input type.

        Args:
            schema (Token): Schema containing the token ID.

        Returns:
            UserInfoReturn: The user's information.
		"""
		token = await self._get_token(schema.token_id)
		return await asyncio.to_thread(_make_user_info, token.user)

	@handle_http_exception(ServerError)
	async def delete_user(self, schema: Token):
		"""
		Deletes a user based on a token.

        Args:
            schema (Token): Schema containing the token ID.
		"""
		token = await self._get_token(schema.token_id)
		await self.user_repo.delete(token.user)

	@handle_http_exception(ServerError)
	async def delete_tokens(self, schema: TokenDelete):
		"""
        Deletes specific tokens owned by a user.

        Args:
            schema (TokenDelete): Schema containing the token IDs to delete.

        Raises:
            InvalidRequestError: If the user does not own the tokens.
		"""
		token = await self._get_token(schema.token_id)
		await self._check_valid_request(schema.token_ids, token.user.tokens, own_key='id')
		await self.token_repo.delete(token.user, schema.token_ids)


class UserSummarySVC(UserSVC):
	"""
	Service class for user summary-related operations.
    Methods:
        - create_summary: Creates a new summary for a user.
        - get_latest_summaries: Retrieves the latest summaries for a user.
        - delete_old_summaries: Deletes old summaries, retaining a specified number.

	"""

	@handle_http_exception(ServerError)
	async def create_summary(self, schema: UserSummarySVCCreate):
		"""
		Creates a new summary for a user.

        Args:
            schema (UserSummarySVCCreate): Schema containing the summary details.
		"""
		token = await self._get_token(schema.token_id)
		await self.user_repo.create_summary(token.user, schema.summary)

	@handle_http_exception(ServerError)
	async def get_latest_summaries(self, schema: UserSummarySVCGetLatest) -> UserSummariesReturn:
		"""
        Retrieves the latest summaries for a user.

        Args:
            schema (UserSummarySVCGetLatest): Schema containing the number of summaries to retrieve.

        Returns:
            UserSummariesReturn: The retrieved summaries.
		"""
		token = await self._get_token(schema.token_id)
		summaries = await self.user_repo.get_summaries(token.user, schema.n)
		return await asyncio.to_thread(_make_user_summaries, summaries)

	@handle_http_exception(ServerError)
	async def delete_old_summaries(self, schema: UserSummarySVCDeleteOld):
		"""
		Deletes old summaries, retaining a specified number.

        Args:
            schema (UserSummarySVCDeleteOld): Schema specifying the number of summaries to retain.
		"""
		token = await self._get_token(schema.token_id)
		await self.user_repo.delete_old_summaries(token.user, max_summaries=schema.remain)
