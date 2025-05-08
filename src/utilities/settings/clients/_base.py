import asyncio
import functools
import typing
from contextlib import asynccontextmanager
from typing import ClassVar, AsyncGenerator, Literal, Coroutine, Any, Callable

import aiohttp
from aiohttp.client import ClientResponse
from fastapi import HTTPException
from pydantic import BaseModel, PositiveInt, ConfigDict, Field, ValidationError, model_validator
from pydantic import HttpUrl

from utilities.logger import logger


# noinspection PyNestedDecorators
class BaseClient(BaseModel):
	model_config = ConfigDict(extra="ignore")
	path: ClassVar[str] = ""
	"""Base path (endpoint) of the service api that client class point to. 
	Use for the composition class to create complete url.path must start and NOT end with / . Or blank string if it's a highest client. 
	Ex: /user , /chat ,..."""

	url: str = "http://localhost:8000"
	"""url must NOT end with / . Ex: http//example.com ."""

	@model_validator(mode='before')
	@classmethod
	def check_and_init(cls, data: dict) -> dict:
		# Check integrity url.
		if data['url'].endswith('/'):
			raise ValidationError(f"\'url\' should not end with \'/\'. Got \'{data['url']}\'.")
		if (cls.path.endswith('/') or not cls.path.startswith('/')) and cls.path != "":
			raise ValidationError(f"Class variable \'path\' must start and Not end with \'/\'. Got \'{cls.path}\'.")

		data['url'] = data['url'] + cls.path

		subclients = {}
		# Init sub clients.
		for k, v in cls.model_fields.items():
			args = typing.get_args(v.annotation)
			cls_t = args[0] if len(args) > 0 else v.annotation

			if issubclass(cls_t, BaseClient):
				subclients[k] = cls_t

			# Prevalidate data to pass to all subclients, so that subclients doesn't need to validate anymore.
			elif issubclass(cls_t, BaseModel) and isinstance(data.get(k, None), dict):
				data[k] = cls_t(**data[k])
		for k, v in subclients.items():
			data[k] = v(**data)
		# all sub clients have the same init data.
		return data


class ClientResponseSchema[DataType:dict](BaseModel):
	status: int
	ok: bool
	reason: str
	headers: dict[str, str]
	cookies: dict[str, str]
	url: HttpUrl
	real_url: HttpUrl
	content_type: str
	content_length: int
	content: DataType | dict | str | None = None
	info: Literal['cache', 'http'] = 'http'

	@classmethod
	async def from_client_response(cls, response: ClientResponse, content: Any = None,
	                               info: Literal['cache', 'http'] = 'http'):
		return await asyncio.to_thread(cls._from_client_response, response, content, info)

	@classmethod
	def _from_client_response(cls, response: ClientResponse, content: Any = None, info: str | None = None):
		return cls(status=response.status, ok=response.ok, reason=response.reason, headers=dict(response.headers),
		           cookies={key: cookie.value for key, cookie in response.cookies.items()},
		           content_type=response.content_type, content_length=response.content_length, url=str(response.url),
		           real_url=str(response.url), content=content, info=info)


class ClientRequestSchema[DataType:dict](BaseModel):
	headers: dict[str, str] = Field(default_factory=dict)
	cookies: dict = Field(default_factory=dict)
	params: dict = Field(default_factory=dict)
	data: DataType | str | bytes | None = None
	# Use alias bc aiohttp need JSON key, but JSON is the primary key of pydantic.
	body: DataType | None = Field(None, serialization_alias='json')
	timeout: PositiveInt | None = 30
	raise_for_status: bool = False

	# Method call request will set these.
	method: Literal['GET', 'POST', 'PUT', 'DELETE'] | None = Field(None,
	                                                               description="This will be set by method call request, "
	                                                                           "DO NOT set it through constructor.")
	url: str | None = Field(None, description="This will be set by method call request, "
	                                          "DO NOT set it through constructor.")
	path_params: str = Field("", exclude=True)

	get_cache_handler: Callable[["ClientRequestSchema"], Coroutine[..., ..., ClientResponseSchema | None]] | None
	set_cache_handler: Callable[[ClientResponseSchema], Coroutine[..., ..., None]] | None

	model_config = ConfigDict(extra='allow', validate_default=True, validate_assignment=True,
	                          arbitrary_types_allowed=True)


# noinspection PyBroadException
@asynccontextmanager
async def get_client_response(client: BaseClient, request: ClientRequestSchema) -> AsyncGenerator[ClientResponse, None]:
	async with aiohttp.ClientSession() as session:
		async with session.request(**request.model_dump(mode='json', by_alias=True)) as response:
			logger.debug(f"{client.__class__.__name__} called request {request.method} {request.url}")
			if not response.ok:
				logger.debug(response)
				try:
					detail = (await response.json())['detail']
				except:
					detail = response.reason
				raise HTTPException(status_code=response.status, detail=detail)
			yield response


response_action = {'text/plain': 'text', 'application/json': 'json', 'x-www-form-urlencoded': 'text'

}


async def json_response_handler(response: ClientResponse,
                                response_type: BaseModel | None = None) -> ClientResponseSchema:
	content = await getattr(response, response_action[response.content_type])()  # ex: response.json

	# Content must be the same type of supplied response_type if ok.
	if issubclass(response_type, BaseModel) and response.ok:
		try:
			content = response_type.model_validate(content)
		except ValidationError:
			raise ValidationError("Server return successfully but response type not match with the expected schema.")
	# noinspection PyTypeHints
	return await ClientResponseSchema[response_type].from_client_response(response, content)


def get_http_response(method: Literal['GET', 'POST', 'PUT', 'DELETE'], response_type: type[Any] = None,
                      response_handler: Callable[
	                      [ClientResponse, ...], Coroutine[..., ..., ClientResponseSchema]] = json_response_handler) -> \
Callable[[Callable[..., Coroutine]], Callable[..., Coroutine]]:
	"""
	Args:
		method:
		response_type: None for no validation, does not mean the response is None.
		response_handler:

	Returns:
	"""

	def decorator(func: Callable[..., Coroutine]) -> Callable[..., Coroutine]:
		"""
		Args:
			func: preprocess the request, should return ClientRequestSchema or not return anything.
		"""

		# Note: Wrap only method, with self is the first argument.
		@functools.wraps(func)
		async def wrapper(self, request: ClientRequestSchema) -> ClientResponseSchema:
			# Preprocess request
			r = await func(self, request)
			request = r or request
			assert isinstance(request, ClientRequestSchema)

			# Handle get cache
			if request.get_cache_handler is not None:
				try:
					client_response = await request.get_cache_handler(request)
					if client_response is not None:  # None if no cache data
						assert isinstance(client_response, ClientResponseSchema)
						client_response.info = 'cache'
						return client_response
				except AssertionError as e:
					# Wrong format of function, raise to force replacing.
					logger.error(f"Cache handler must return ClientResponseSchema or None: {e}")
					raise e
				except Exception as e:
					# Cache error, the process should not interrupt.
					logger.error(f"Cache handler is provided but call fail: {e}")

			# Call API only if getting cache fail or not provided
			request.method = method
			request.url = self.url + '/' + func.__name__ + request.path_params
			async with get_client_response(self, request) as response:
				client_response = await response_handler(response, response_type)
				assert isinstance(client_response, ClientResponseSchema)
				client_response.info = 'http'

			# Handle set cache
			if request.set_cache_handler is not None:
				try:
					await request.set_cache_handler(client_response)
				except Exception as e:
					# Cache error
					logger.error(f"Cache handler is provided but call fail: {e}")
			return client_response

		return wrapper

	return decorator
