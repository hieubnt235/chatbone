import asyncio
from typing import Sequence

import jwt
from fastapi import HTTPException, status

from utilities.exception import handle_http_exception
from utilities.func import hash_password, get_expire_date
from utilities.settings.clients.auth import *
from utilities.settings.clients.datastore import DatastoreClient, UserCreate, ClientRequestSchema, UserInfoReturn, \
	ClientResponseSchema, Token, TokenInfoReturn, UserVerify
from .settings import auth_settings

ServerError = HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Something went wrong with server.")
JWTError = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Cannot decode jwt.')


class AuthenticationSVC:

	def __init__(self):
		self.datastore: DatastoreClient = auth_settings.datastore
		self.config = auth_settings.config

		self.token_duration_seconds = self.config.token_duration_seconds
		self.jwt_encode_algorithm = self.config.jwt_encode_algorithm
		self.secret_key = self.config.auth_secret_key
		self.datastore_request_timeout = self.config.datastore_request_timeout
		self.max_valid_tokens = self.config.max_valid_tokens

	@handle_http_exception(ServerError)
	async def register(self, schema: UserRegister) -> str:
		"""
		Create a user and first token.
		Intent to be used to sign up.

		Returns:
			encoded jwt.

		"""
		req = ClientRequestSchema[UserCreate](body=UserCreate(username=schema.username,
			hashed_password=await asyncio.to_thread(hash_password, schema.password),
			expires_at=get_expire_date(self.token_duration_seconds)), timeout=self.datastore_request_timeout.create)
		res: ClientResponseSchema[UserInfoReturn] = await self.datastore.user.access.create(req)
		# self.datastore.check_ok(res)
		return await asyncio.to_thread(self._encode_jwt, res.content)

	@handle_http_exception(ServerError)
	async def authenticate(self, schema: UserRegister) -> str:
		"""
		Check use name and password. return valid jwt, or create new one and return it if there is no valid one.
		Intent to be used to log in.
		Returns:
			encoded jwt.
		"""

		req = ClientRequestSchema[UserVerify](body=UserVerify(username=schema.username, password=schema.password,
			expires_at=get_expire_date(self.token_duration_seconds), create_token_flag='if_all_expired'),
			timeout=self.datastore_request_timeout.create)
		res: ClientResponseSchema[UserInfoReturn] = await self.datastore.user.access.verify(req)
		# self.datastore.check_ok(res)
		return await asyncio.to_thread(self._encode_jwt, res.content)

	@handle_http_exception(ServerError)
	async def expire_tokens(self):
		# TODO implement this method to support logout. But first, implement update token in datastore server, client.
		pass

	@handle_http_exception(ServerError)
	async def get_user(self, jwt: str) -> UserInfoReturn:
		"""
		Intent to be used to verify current jwt.

		Decode jwt, return user UserInfoReturn
		Returns:
		"""

		# Decode latest token and make request.
		try:
			token: TokenInfoReturn = await asyncio.to_thread(self._decode_jwt, jwt)
			req = ClientRequestSchema[Token](body=Token(token_id=token.id), timeout=self.datastore_request_timeout.get)
		except Exception:
			raise JWTError

		res: ClientResponseSchema[UserInfoReturn] = await self.datastore.user.access.get(req)
		# self.datastore.check_ok(res)
		return res.content

	@handle_http_exception(ServerError)
	async def delete_user(self):
		"""TODO"""
		pass

	def _encode_jwt(self, userinfo: UserInfoReturn) -> str:
		return jwt.encode(userinfo.model_dump(exclude={'hashed_password'}, mode='json'), key=self.secret_key,
		                  algorithm=self.jwt_encode_algorithm)

	def _decode_jwt(self, jwt_str: str) -> TokenInfoReturn:
		"""
		Decode jwt and return the LAST token in \'tokens\'.
		Args:
			jwt_str:

		Returns: Latest Token.

		"""
		if self.jwt_encode_algorithm is None:
			algo = None
		else:
			algo = self.jwt_encode_algorithm if isinstance(self.jwt_encode_algorithm, Sequence) else [
				self.jwt_encode_algorithm]

		info = jwt.decode(jwt_str, self.secret_key, algo)

		return TokenInfoReturn.model_validate(info['tokens'][-1])


auth_svc = AuthenticationSVC()
