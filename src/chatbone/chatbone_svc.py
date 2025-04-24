from fastapi import HTTPException, status

from chatbone_utils.datastore import *
from chatbone_utils.exception import handle_http_exception
from .settings import chat_settings

ServerError = HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Something went wrong with server.")


def TooManySessionsError(max_sessions: int):
	return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Too many sessions exist. You have to delete"
	                                                                     f"some to create new one. Max sessions allowed: {max_sessions}")


class AssistantStreamResponse(BaseModel):
	workflow: str | None = None
	node: str | None = None
	stream_data: str | None = None
	"""Provided when done."""
	data: str | None = None
	"""Provided when done."""


class AssistantList(BaseModel):
	pass

#TODO All real delete operation belong to admin. User only mark delete.
"""Strategy: 
create mark_delete attribute in entities
implement datastore repo update method.
At datastore svc, reimplement all delete_old to update the mark_delete.
For the real delete operation, append with admin prefix.Ex: admin_delete_old_messages,...
"""

class ChatboneSVC:
	"""
	Not start with _ = public api. start with _ = internal usage.

	"""

	def __init__(self):
		self.datastore: DatastoreClient = chat_settings.datastore
		self.config = chat_settings.config
		self.datastore_request_timeout = self.config.datastore_request_timeout

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

	@handle_http_exception(ServerError)
	async def chat(self):
		"""
		TODO main method
		Returns:

		"""
		pass


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
		req =ClientRequestSchema[UserSummarySVCDeleteOld](body=UserSummarySVCDeleteOld(body=schema),
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


