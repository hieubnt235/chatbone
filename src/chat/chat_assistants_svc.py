import ray
from fastapi import HTTPException, status, WebSocketException
from pydantic import ValidationError
from ray import serve, ObjectRef
from ray.serve.exceptions import RayServeException
from ray.serve.handle import DeploymentHandle
from starlette.websockets import WebSocket, WebSocketDisconnect

from utilities.exception import handle_http_exception
from utilities.logger import logger
from utilities.settings.clients.datastore import *
from .settings import chat_settings

ServerError = HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Something went wrong with server.")


def TooManySessionsError(max_sessions: int):
	return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Too many sessions exist. You have to delete"
	                                                                     f"some to create new one. Max sessions allowed: {max_sessions}")


class AssistantRequest(BaseModel):
	pass

class AssistantResponse(BaseModel):
	workflow: str | None = None
	node: str | None = None
	stream_data: str | None = None
	"""Provided when done."""
	data: str | None = None
	"""Provided when done."""

class AssistantList(BaseModel):
	pass

#TODO All real delete operation belong to admin. User only mark delete. Strategy below:
"""Strategy: 
create mark_delete attribute in entities
implement datastore repo update method.
At datastore svc, reimplement all delete_old to update the mark_delete.
For the real delete operation, append with admin prefix.Ex: admin_delete_old_messages,...
"""


""" Problem: How assistant access history ?
- Assistant know whether it need and when it need to retrieve history. So need mechanism for assistant 
OPTIONALLY call the history retrieval. Not always call or retrieve all history and pass to assistant at the first step.
Maybe assistant is in remote, so pass all history at first step, but assistant maybe doesn't need it, make it stupid.

- Strategy: Assistant have optional arguments call "retrieve_message, retrieve_info,..." Then chat service
provide it as function (no call), no matter it use or not, it call when it need.
"""

"""Problem: How to inject assistant?
Prefer: Have mechanism to add or remove assistants but not affect to the remain.

Options:
1. Inject assistant directly.
- Assistant is the same code base with Chatservice, so if add more assistant, need to stop and refresh.
- But it good if the app must have assistant to run.
- Easy to pass retrieve methods (see above problem) because of shared memory.

2. Assistant and chat service as deployments (another process) to app.
- Still the same codebase, but support independent upload.
- Easy to pass retrieve methods
- When service change API, Assistant must be change, maybe solve that by have a assistant interface, that know chatservice api.
- Easy cache.

3. Assistant as separating API.
- Complicated.
- Need API to call assistant, and assistant call the service.

=> User option 2 for now.

ChatAssistantSVC will inject to app.
Where exactly to inject assistant ?
Who pass ChatAssistantSvc to assistant ? itself or api app ?

"""

# class ChatAssistantCache(BaseModel):

# TODO monitor all websocket from all connection. Using singleton separated managers.
# @serve.deployment
# class _ConnectionsManager:
# 	def __init__(self):
# 		self._active_ws:int = 0
#


class ChatAssistantSVC:
	"""
	- Load User history, info, summary to object storage and distribute it.
	"""
	def __init__(self):
		self.datastore: DatastoreClient = chat_settings.datastore
		self.config = chat_settings.config
		self.datastore_request_timeout = self.config.datastore_request_timeout
		self.chat_assistant_timeout = self.config.chat_assistant_timeout

		self._websockets:list[WebSocket] = []

	@handle_http_exception(ServerError)
	async def chat(self,assistant_name:str, websocket: WebSocket):
		await websocket.accept()
		logger.debug("Websocket connected.")
		chat_input:ObjectRef=None
		assistant_handle:DeploymentHandle=None

		try:
			assistant_handle= serve.get_app_handle(assistant_name).
			input_schema: BaseModel = await assistant_handle.get_input_schemas.remote()

			await asyncio.wait_for(websocket.send_json(input_schema),timeout=self.chat_assistant_timeout.websocket_send)

			chat_input = input_schema.model_validate_json(await websocket.receive_json())
			chat_input = ray.put(chat_input)
		except RayServeException:
			raise WebSocketException(code=status.WS_1003_UNSUPPORTED_DATA,
			                         reason=f"Assistant \'{assistant_name}\' doesn't exist.")
		except ValidationError:
			raise WebSocketException(code=status.WS_1007_INVALID_FRAME_PAYLOAD_DATA,
			                         reason=f"Assistant input format does not true.")
		except asyncio.TimeoutError:
			raise WebSocketException(code=status.WS_1002_PROTOCOL_ERROR,
			                         reason="Cannot send the input request schema.")
		except WebSocketDisconnect:
			logger.debug("Websocket disconnected.")

		app_name = serve.get_replica_context().app_name
		try:
			async for response in assistant_handle.options(stream=True).remote(chat_input, app_name):
				response[]



	@handle_http_exception(ServerError)
	async def create_chat_session(self, schema: ChatSVCBase) -> ChatSessionReturn:
		user_info_res = await self.datastore.user.access.get(
			ClientRequestSchema[Token](body=Token(token_id=schema.token_id), timeout=self.datastore_request_timeout.default))

		if len(user_info_res.content.chat_ids >= self.config.max_sessions):
			raise TooManySessionsError(self.config.max_sessions)

		req = ClientRequestSchema[ChatSVCBase](body=schema, timeout=self.datastore_request_timeout.session_create)
		res = await self.datastore.chat.session.create(req)
		return res.content

	@handle_http_exception(ServerError)
	async def delete_chat_session(self, schema: ChatSessionSVCDelete) -> dict | None:
		req = ClientRequestSchema[ChatSessionSVCDelete](body=schema,
		                                                timeout=self.datastore_request_timeout.session_delete)
		res = await self.datastore.chat.session.delete(req)
		return res.content

	# Messages.
	@handle_http_exception(ServerError)
	async def _delete_old_messages(self,schema: ChatSVCDeleteOld)->dict|None:
		req = ClientRequestSchema[ChatSVCDeleteOld](body=schema,
		                                            timeout=self.datastore_request_timeout.message_delete_old)
		return (await self.datastore.chat.message.delete_old(req)).content

	@handle_http_exception(ServerError)
	async def get_messages(self, schema: ChatSVCGetLatest) -> MessagesReturn:
		"""
		Get messages and delete old messages. When received messages > maximum messages the delete old will run.

		Note: Delete all apply only received messages, not for all messages in db.
		That means if client get messages < max messages. The delete old will NOT run despite entire message in db > maximum messages.
		This is intentionally for overall performance. Because delete only also happen when create new message.
		"""
		req = ClientRequestSchema[ChatSVCGetLatest](body=schema,
		                                            timeout=self.datastore_request_timeout.message_get_latest)
		res = await self.datastore.chat.message.get_latest(req)

		# Delete old
		if len(res.content.messages)> self.config.max_messages:
			await self._delete_old_messages(ChatSVCDeleteOld(token_id=schema.token_id,
			                                                 chat_session_id=schema.chat_session_id,
			                                                 remain=self.config.max_messages))
			# request again to confirm.
			res = await self.datastore.chat.message.get_latest(req)
			assert len(res.content.messages)<= self.config.max_messages
		return res.content


	@handle_http_exception(ServerError)
	async def _create_message(self, schema: ChatMessageSVCCreate)->MessagesReturn:
		"""
		Create new messages and check if messages <= max messages.
		"""
		c_req = ClientRequestSchema[ChatMessageSVCCreate](body=schema,
		                                                  timeout=self.datastore_request_timeout.message_create)
		_ = await self.datastore.chat.message.create(c_req)

		messages = await self.get_messages(ChatSVCGetLatest(token_id=schema.token_id,
		                                                    chat_session_id=schema.chat_session_id,
		                                                    n=-1)) # This will activate delete old in get_massage.content
		# assert len(messages.messages)<= self.config.max_messages # already assert in get_messages.
		return messages

	# Chat summary
	@handle_http_exception(ServerError)
	async def _delete_old_chat_summaries(self, schema: ChatSVCDeleteOld)->dict|None:
		req = ClientRequestSchema[ChatSVCDeleteOld](body=schema,
		                                            timeout=self.datastore_request_timeout.summary_delete_old)
		return (await self.datastore.chat.summary.delete_old(req)).content


	@handle_http_exception(ServerError)
	async def _get_chat_summaries(self, schema: ChatSVCGetLatest)->ChatSummariesReturn:
		req = ClientRequestSchema[ChatSVCGetLatest](body=schema,
		                                            timeout=self.datastore_request_timeout.summary_get_latest)
		res = await self.datastore.chat.summary.get_latest(req)

		# Delete old
		if len(res.content.summaries) > self.config.max_chat_summaries:
			await self._delete_old_chat_summaries(
				ChatSVCDeleteOld(token_id=schema.token_id,
				                 chat_session_id=schema.chat_session_id,
				                 remain=self.config.max_chat_summaries))
			# request again to confirm.
			res = await self.datastore.chat.summary.get_latest(req)
			assert len(res.content.summaries) <= self.config.max_chat_summaries
		return res.content

	@handle_http_exception(ServerError)
	async def _create_chat_summary(self, schema: ChatSummarySVCCreate)->ChatSummariesReturn:
		c_req = ClientRequestSchema[ChatSummarySVCCreate](body=schema,
		                                                  timeout=self.datastore_request_timeout.summary_create)
		_ = await self.datastore.chat.summary.create(c_req)

		summaries = await self._get_chat_summaries(ChatSVCGetLatest(token_id=schema.token_id,
		                                                            chat_session_id=schema.chat_session_id,
		                                                            n=-1))
		# assert len(messages.messages)<= self.config.max_messages # already assert in get_messages.
		return summaries

	# User summary
	@handle_http_exception(ServerError)
	async def _delete_old_user_summaries(self, schema: UserSummarySVCDeleteOld)->dict|None:
		req =ClientRequestSchema[UserSummarySVCDeleteOld](body=schema,
		                                                  timeout=self.datastore_request_timeout.summary_delete_old)
		return (await self.datastore.user.summary.delete_old(req)).content

	@handle_http_exception(ServerError)
	async def _get_user_summaries(self, schema:UserSummarySVCGetLatest)->UserSummariesReturn:
		"""Get and delete old summaries."""
		req = ClientRequestSchema[UserSummarySVCGetLatest](body=schema,
		                                                   timeout=self.datastore_request_timeout.summary_get_latest)
		res = await self.datastore.user.summary.get_latest(req)

		if len(res.content.summaries)>self.config.max_user_summaries:
			_= await self._delete_old_user_summaries(UserSummarySVCDeleteOld(token_id=schema.token_id,
			                                                                 remain=self.config.max_user_summaries))
			res = await self.datastore.user.summary.get_latest(req)
			assert len(res.content.summaries)<= self.config.max_user_summaries
		return res.content


	@handle_http_exception(ServerError)
	async def _create_user_summary(self,schema: UserSummarySVCCreate)->UserSummariesReturn:
		req = ClientRequestSchema[UserSummarySVCCreate](body=schema,
		                                                timeout=self.datastore_request_timeout.summary_create)
		_=await self.datastore.user.summary.create(req)
		summaries = await self._get_user_summaries(UserSummarySVCGetLatest(token_id=schema.token_id,
		                                                                   n=-1))
		return summaries


