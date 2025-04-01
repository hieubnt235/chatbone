import asyncio
from concurrent.futures.thread import ThreadPoolExecutor
from uuid import UUID

import jwt
from sqlalchemy.ext.asyncio import AsyncSession
from chatbone.configs import chatbone_configs, AuthConfig
from chatbone.settings import chatbone_settings
from chatbone import ServerError, AuthenticationError, UsernameNotFoundError, AlreadyRegisterError, \
    TokenError, handle_http_exception
from chatbone.repositories.user import UserRepo, TokenInfoAuthSuccess
from .schemas import *


def encode_jwt(token_info: TokenInfoAuthSuccess,
               secret_key: str,
               algorithm: str = "HS256"
               ) -> str:
    try:
        return jwt.encode(token_info.model_dump(mode='json'), secret_key, algorithm)
    except:
        raise ServerError


def decode_jwt(jwt_token: str,
               secret_key: str,
               algorithm: list[str] | None = None) -> UUID:
    """
    Decode a JWT token and return the token ID.

    Raises:
        TokenError: If decoding the JWT token fails.
    """
    try:
        if algorithm is None:
            algorithm = ["HS256"]
        token_info = jwt.decode(jwt_token, secret_key, algorithm)
        return UUID(token_info['id'])
    except Exception:
        raise TokenError


class AuthenticationService:
    """
    Service class for handling user authentication and registration.

        Methods:
            async def register(self, user: UserCredentials) -> None:

            async def authenticate(self, user: UserCredentials) -> AuthenticatedToken:

            async def decode_jwt_token(self,jwt_token:str)->UUID:
    """

    def __init__(self, session: AsyncSession):
        self.config: AuthConfig = chatbone_configs.auth_config
        self.user_repo = UserRepo(session)

        self.token_duration_seconds = self.config.token_duration_seconds
        self.jwt_encode_algorithm = self.config.jwt_encode_algorithm

        self.secret_key = chatbone_settings.auth_secret_key

    @handle_http_exception(ServerError)
    async def register(self, user: UserCredentials) -> None:
        """
        Register a new user.

        Args:
            user (UserIn): The user information for registration.

        Raises:
            AlreadyRegisterError: If the user is already registered.
            ServerError: If there is a server error during registration.
        """

        if await self.user_repo.verify(username=user.username):
            raise AlreadyRegisterError
        await self.user_repo.create(username=user.username,
                                    hashed_password=user.hashed_password)

    @handle_http_exception(ServerError)
    async def authenticate(self, user: UserCredentials) -> str:
        """
        Authenticate a user for login, create and return JWT str.

        Args:
            user : The user information for authentication.

        Raises:
            AuthenticationError: If authentication fails.
            UsernameNotFoundError: If the username is not found.
            ServerError: If there is a server error during authentication.

        Returns:
            str: The JWT token if authentication is successful.
        """
        if not await self.user_repo.verify(username=user.username):
            raise UsernameNotFoundError
        if (token_info := await self.user_repo.authenticate(username=user.username,
                                                            hashed_password=user.hashed_password,
                                                            token_duration_seconds=self.token_duration_seconds)) is None:
            raise AuthenticationError
        else:
            with ThreadPoolExecutor() as pool:
                return await asyncio.get_running_loop().run_in_executor(pool, encode_jwt,
                                                                        token_info, self.secret_key,
                                                                        self.jwt_encode_algorithm)

    @handle_http_exception(ServerError)
    async def decode_jwt_token(self, jwt_token: str) -> UUID:
        """
        Args:
            jwt_token:

        Returns: AccessToken.id (type UUID)

        Raises:
            ServerError: If there is a server error during decoding.
            TokenError: If decoding the JWT token fails.
        """
        with ThreadPoolExecutor() as pool:
            return await asyncio.get_running_loop().run_in_executor(pool, decode_jwt,
                                                                    jwt_token, self.secret_key,
                                                                    [self.jwt_encode_algorithm])
