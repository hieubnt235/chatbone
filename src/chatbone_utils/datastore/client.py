import functools

from chatbone_utils.client import BaseClient, ClientRequestSchema, ClientResponseSchema, get_http_response
from chatbone_utils.datastore.schemas.chat_svc import *
from chatbone_utils.datastore.schemas.user_svc import *
from chatbone_utils.exception import BaseMethodException


# All the magic stuff is in BaseClient, the concrete client like this is just define type.

class DatastoreClientException(BaseMethodException):
	pass


get_datastore_response = functools.partial(get_http_response, exception_type=DatastoreClientException)

# All the magic stuff is in BaseClient, the concrete client like this is just define type.

######################################################################## USER CLIENT
CreateUserRequest = ClientRequestSchema[UserCreate]
VerifyUserRequest = ClientRequestSchema[UserVerify]
GetAndDeleteUserRequest = ClientRequestSchema[Token]
DeleteTokensRequest = ClientRequestSchema[TokenDelete]


class _Access(BaseClient):
	path = '/access'

	@get_datastore_response('POST', UserInfoReturn)
	async def create(self, request: CreateUserRequest) -> ClientResponseSchema[UserInfoReturn]:
		"""
		Create new user and the first token if user doesn't exist.
		Args:
			request: ClientRequestSchema[UserCreate]
		"""
		pass

	@get_datastore_response('POST', UserInfoReturn)
	async def verify(self, request: VerifyUserRequest) -> ClientResponseSchema[UserInfoReturn]:
		"""
        Verifies a user and optionally creates a new token if needed.
		Args:
			request: ClientRequestSchema[UserCreate]
		"""
		pass

	@get_datastore_response('GET', UserInfoReturn)
	async def get(self, request: GetAndDeleteUserRequest) -> ClientResponseSchema[UserInfoReturn]:
		"""
		Params of request will be updated by request.body
		"""
		if request.body is not None:
			request.params.update(request.body.model_dump())

	@get_datastore_response('DELETE', UserInfoReturn)
	async def delete(self, request: GetAndDeleteUserRequest) -> ClientResponseSchema[UserInfoReturn]:
		pass

	@get_datastore_response('DELETE')
	async def delete_tokens(self, request: DeleteTokensRequest) -> ClientResponseSchema:
		pass


CreateUserSummaryRequest = ClientRequestSchema[UserSummarySVCCreate]
GetLatestUserSummariesRequest = ClientRequestSchema[UserSummarySVCGetLatest]
DeleteOldUserSummariesRequest = ClientRequestSchema[UserSummarySVCDeleteOld]


class _UserSummary(BaseClient):
	path = '/summary'

	@get_datastore_response('POST')
	async def create(self, request: CreateUserSummaryRequest) -> ClientResponseSchema:
		pass

	@get_datastore_response('GET', UserSummariesReturn)
	async def get_latest(self, request: GetLatestUserSummariesRequest) -> ClientResponseSchema[UserSummariesReturn]:
		if request.body is not None:
			request.params.update(request.body.model_dump())

	@get_datastore_response('DELETE')
	async def delete_old(self, request: DeleteOldUserSummariesRequest) -> ClientResponseSchema:
		pass


class _User(BaseClient):
	path = '/user'
	access: _Access
	summary: _UserSummary


######################################################################## CHAT CLIENT
CreateChatSessionRequest = ClientRequestSchema[ChatSVCBase]
DeleteChatSessionsRequest = ClientRequestSchema[ChatSessionSVCDelete]


class _Session(BaseClient):
	path = '/session'

	@get_datastore_response('POST', ChatSessionReturn)
	async def create(self, request: CreateChatSessionRequest) -> ClientResponseSchema[ChatSessionReturn]:
		pass

	@get_datastore_response('DELETE')
	async def delete(self, request: DeleteChatSessionsRequest) -> ClientResponseSchema:
		pass


CreateMessageRequest = ClientRequestSchema[ChatMessageSVCCreate]
# These use for both chat message and chat summary types.
GetLatestRequest = ClientRequestSchema[ChatSVCGetLatest]
DeleteOldRequest = ClientRequestSchema[ChatSVCDeleteOld]


class _Message(BaseClient):
	path = '/message'

	@get_datastore_response('POST')
	async def create(self, request: CreateMessageRequest) -> ClientResponseSchema:
		pass

	@get_datastore_response('GET', MessagesReturn)
	async def get_latest(self, request: GetLatestRequest) -> ClientResponseSchema[MessagesReturn]:
		if request.body is not None:
			request.params.update(request.body.model_dump())

	@get_datastore_response('DELETE')
	async def delete_old(self, request: DeleteOldRequest) -> ClientResponseSchema:
		pass


CreateChatSummaryRequest = ClientRequestSchema[ChatSummarySVCCreate]


class _ChatSummary(BaseClient):
	path = '/summary'

	@get_datastore_response('POST')
	async def create(self, request: CreateChatSummaryRequest) -> ClientResponseSchema:
		pass

	@get_datastore_response('GET', ChatSummariesReturn)
	async def get_latest(self, request: GetLatestRequest) -> ClientResponseSchema[ChatSummariesReturn]:
		if request.body is not None:
			request.params.update(request.body.model_dump())

	@get_datastore_response('DELETE')
	async def delete_old(self, request: DeleteOldRequest) -> ClientResponseSchema:
		pass


class _Chat(BaseClient):
	path = '/chat'
	message: _Message
	summary: _ChatSummary
	session: _Session


######################################################################## DATASTORE CLIENT
class DatastoreClient(BaseClient):
	"""Datastore service client class. This class is used to call Datastore endpoints.

	Attributes:

		url: Base url of the server, which will be used to concat with endpoints.

	Methods:

        - datastore.user.access.create(CreateUserRequest) -> ClientResponseSchema[UserInfoReturn]
        - datastore.user.access.verify(VerifyUserRequest) -> ClientResponseSchema[UserInfoReturn]
        - datastore.user.access.get(GetAndDeleteUserRequest) -> ClientResponseSchema[UserInfoReturn]
        - datastore.user.access.delete(GetAndDeleteUserRequest) -> ClientResponseSchema[UserInfoReturn]
        - datastore.user.access.delete_tokens(DeleteTokensRequest) -> ClientResponseSchema
        - datastore.user.summary.create(CreateUserSummaryRequest) -> ClientResponseSchema
        - datastore.user.summary.get_latest(GetLatestUserSummariesRequest) -> ClientResponseSchema[UserSummariesReturn]
        - datastore.user.summary.delete_old(DeleteOldUserSummariesRequest) -> ClientResponseSchema
        - datastore.chat.session.create(CreateChatSessionRequest) -> ClientResponseSchema[ChatSessionReturn]
        - datastore.chat.session.delete(DeleteChatSessionsRequest) -> ClientResponseSchema
        - datastore.chat.message.create(CreateMessageRequest) -> ClientResponseSchema
        - datastore.chat.message.get_latest(GetLatestRequest) -> ClientResponseSchema[MessagesReturn]
        - datastore.chat.message.delete_old(DeleteOldRequest) -> ClientResponseSchema
        - datastore.chat.summary.create(CreateChatSummaryRequest) -> ClientResponseSchema
        - datastore.chat.summary.get_latest(GetLatestRequest) -> ClientResponseSchema[ChatSummariesReturn]
        - datastore.chat.summary.delete_old(DeleteOldRequest) -> ClientResponseSchema

	Examples:
		datastore = DatastoreClient(url='http://127.0.0.1:8000')

		request = VerifyUserRequest(body=UserVerify(username='this is new name', hashed_password='string'))

		r = asyncio.run(datastore.user.access.verify(request))

		print(r.model_dump_json(indent=4))
	"""
	user: _User
	chat: _Chat


if __name__ == '__main__':
	import asyncio

	datastore = DatastoreClient(url='http://localhost:8000')

	request = VerifyUserRequest(body=UserVerify(username='this is new name', hashed_password='string'))

	r = asyncio.run(datastore.user.access.verify(request))

	print(r.model_dump_json(indent=4))
	print(type(r.content))
