import functools
from utilities.logger import logger
from utilities.settings.clients._base import BaseClient, ClientRequestSchema, ClientResponseSchema, \
	get_http_response
from utilities.schemas.auth import *
from utilities.settings.clients.datastore import UserInfoReturn


get_auth_response=functools.partial(get_http_response)
RegisterUserRequest=ClientRequestSchema[UserRegister]
AuthenticateUserRequest=ClientRequestSchema[UserAuthenticate]

class AuthClient(BaseClient):
	@get_auth_response('POST',TokenJWT)
	async def register(self,request: RegisterUserRequest)->ClientResponseSchema[TokenJWT]:
		pass

	@get_auth_response('POST',TokenJWT)
	async def authenticate(self,request: AuthenticateUserRequest)->ClientResponseSchema[TokenJWT]:
		if not isinstance(request.data, UserAuthenticate):
			raise ValueError("Form data must be provided to register.")

	@get_auth_response('GET',UserInfoReturn)
	async def get_user(self,request: ClientRequestSchema)-> ClientResponseSchema[UserInfoReturn]:
		"""
		request.headers must have key: "Authorization": f"Bearer {access_token}"
		"""
		if request.headers.get('Authorization',None) is None:
			raise ValueError('Headers with \'Authorization\' key must be provided.')
		if 'Bearer' not in request.headers['Authorization']:
			raise ValueError('Value of \'Authorization\' must be start with \'Bearer \'.')


