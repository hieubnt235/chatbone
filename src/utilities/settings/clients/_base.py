import asyncio
import functools
from contextlib import asynccontextmanager
from typing import ClassVar, AsyncGenerator, Literal, Coroutine, Any, Callable

import aiohttp
from aiohttp import ClientResponseError
from aiohttp.client import ClientResponse
from pydantic import BaseModel, PositiveInt, ConfigDict, Field, ValidationError, model_validator
from pydantic import HttpUrl

from utilities.exception import BaseMethodException, handle_exception
from utilities.logger import logger


class ClientRequestSchema[DataType:dict](BaseModel):
	headers: dict[str, str] = Field(default_factory=dict)
	cookies: dict = Field(default_factory=dict)
	params: dict = Field(default_factory=dict)
	data: DataType | str | bytes | None = None
	# Use alias bc aiohttp need json key, but json is primary key of pydantic.
	body: DataType| None = Field(None, serialization_alias='json')
	timeout: PositiveInt | None = 30
	raise_for_status:bool=True

	# Method call request will set these.
	method: Literal['GET', 'POST', 'PUT', 'DELETE'] | None = Field(None,
	                                                               description="This will be set by method call request, "
	                                                                           "DO NOT set it through constructor.")
	url: str | None = Field(None, description="This will be set by method call request, "
	                                          "DO NOT set it through constructor.")
	path_params: str=Field("", exclude=True)


	model_config = ConfigDict(extra='allow', validate_default=True,validate_assignment=True)



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
	content: DataType|dict | str | None = None
	info: str | None = None

	@classmethod
	async def from_client_response(cls, response: ClientResponse, content: Any = None,info:str|None=None):
		return await asyncio.to_thread(cls._from_client_response, response,content,info)

	@classmethod
	def _from_client_response(cls,response: ClientResponse, content: Any = None,info:str|None=None):
		return cls(status=response.status,
		           ok=response.ok,
		           reason=response.reason,
		           headers=dict(response.headers),
		           cookies={key: cookie.value for key, cookie in response.cookies.items()},
		           content_type=response.content_type,
		           content_length=response.content_length,
		           url=str(response.url),
		           real_url=str(response.url),
		           content=content,
		           info=info
		           )

class ClientException(BaseMethodException):
	pass

class BaseClient(BaseModel):
	path: ClassVar[str] = ""
	"""path must start and NOT end with / . Or blank string if it's a highest client. Ex: /user , /chat ,..."""
	url: str= "http://localhost:8000"
	"""url must NOT end with / . Ex: http//example.com ."""

	@model_validator( mode='before')
	@classmethod
	def check_and_init(cls,data:dict)-> dict:
		# Check integrity url.
		if data['url'].endswith('/'):
			raise ValidationError(f"\'url\' should not end with \'/\'. Got \'{data['url']}\'.")
		if (cls.path.endswith('/') or not cls.path.startswith('/')) and cls.path!="" :
			raise ValidationError(f"Class variable \'path\' must start and Not end with \'/\'. Got \'{cls.path}\'.")

		data['url'] = data['url']+cls.path

		# Initialize BaseClient
		# noinspection PyUnresolvedReferences
		for k,v in cls.model_fields.items():
			if issubclass(v.annotation, BaseClient):
				data[k] = v.annotation(url=data['url'])
		return data

	# raise_for_status is available now in ClientRequestSchema and default is True. So don't need this function to check.
	# def check_ok(self, res: ClientResponseSchema):
	# 	"""
	# 	Raise HTTPException if not ok.
	# 	Note that if ok, the type of response.content is match with the expected type of client. So don't have to check.
	# 	"""
	# 	if not res.ok:
	# 		logger.info(f"NOT OK.")
	# 		raise HTTPException(status_code=res.status,
	# 		                    detail=f"{self.__class__.__name__}: {res.content.get('detail','Something wrong with server.')}")

@asynccontextmanager
async def get_client_response(client:BaseClient, request: ClientRequestSchema) -> AsyncGenerator[ClientResponse, None]:
		async with aiohttp.ClientSession() as session:
			async with session.request(**request.model_dump(mode='json', by_alias=True)) as response:
				try:
					logger.debug(f"{client.__class__.__name__} call request {request.method} {request.url}")
					yield response
				except ClientResponseError as e:
					logger.error(repr(e),server=True)

response_action={
	'text/plain':'text',
	'application/json':'json',
	'x-www-form-urlencoded':'text'

}

async def json_response_handler(response: ClientResponse, response_type:BaseModel|None=None) ->ClientResponseSchema:
	content = await getattr(response, response_action[response.content_type])()

	# Content must be the same type of supplied response_type if ok.
	if issubclass(response_type, BaseModel) and response.ok:
		try:
			content = response_type.model_validate(content)
		except ValidationError:
			raise ValidationError("Server return successfully but response type not match with the expected schema.")
	return await ClientResponseSchema[response_type].from_client_response(response, content)


def get_http_response(method:Literal['GET','POST','PUT','DELETE'],
                      response_type: type[Any] = None,
                      exception_type: BaseMethodException = ClientException,
                      response_handler: Callable[[ClientResponse,...], Any ] = json_response_handler
                      ) -> Callable[ [Callable[...,Coroutine]], Callable[...,Coroutine]]:

	def decorator(func: Callable[...,Coroutine])-> Callable[...,Coroutine]:

		# Note: Wrap only method, with self is the first argument.
		@handle_exception(exception_type)
		@functools.wraps(func)
		async def wrapper(self,request: ClientRequestSchema)->ClientResponseSchema:
			await func(self,request)
			request.method=method
			request.url= self.url + '/' + func.__name__ + request.path_params
			async with get_client_response(self,request) as response:
				return await response_handler(response,response_type)

		return wrapper
	return decorator

