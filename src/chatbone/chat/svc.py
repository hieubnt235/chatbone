import asyncio
from uuid import UUID

from fastapi import HTTPException, status

from chatbone.broker import UserData
from chatbone.chat.settings import DATASTORE, CONFIG
from utilities.exception import handle_http_exception
from utilities.settings.clients.datastore import *

ServerError = HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Something went wrong with server.")


def TooManySessionsError(max_sessions: int):
	return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Too many sessions exist. You have to delete"
	                                                                     f"some to create new one. Max sessions allowed: {max_sessions}")


AuthenticationError = HTTPException(status_code=status.HTTP_407_PROXY_AUTHENTICATION_REQUIRED,
                                    detail="Chat session authentication fail because of expiring or no authentication.")


class _DataSVC:
	"""For interacting with data store service."""
	@handle_http_exception(ServerError)
	async def create_chat_session(self, schema: ChatSVCBase) -> ChatSessionReturn:
		user_info_res = await DATASTORE.user.access.get(ClientRequestSchema[Token](body=Token(token_id=schema.token_id),
		                                                                           timeout=CONFIG.datastore_request_timeout.default))

		if len(user_info_res.content.chat_ids >= CONFIG.max_sessions):
			raise TooManySessionsError(CONFIG.max_sessions)

		req = ClientRequestSchema[ChatSVCBase](body=schema, timeout=CONFIG.datastore_request_timeout.session_create)
		res = await DATASTORE.chat.session.create(req)
		return res.content

	@handle_http_exception(ServerError)
	async def delete_chat_session(self, schema: ChatSessionSVCDelete) -> dict | None:
		req = ClientRequestSchema[ChatSessionSVCDelete](body=schema,
		                                                timeout=CONFIG.datastore_request_timeout.session_delete)
		res = await DATASTORE.chat.session.delete(req)
		return res.content

	# Messages.
	@handle_http_exception(ServerError)
	async def _delete_old_messages(self, schema: ChatSVCDeleteOld) -> dict | None:
		req = ClientRequestSchema[ChatSVCDeleteOld](body=schema,
		                                            timeout=CONFIG.datastore_request_timeout.message_delete_old)
		return (await DATASTORE.chat.message.delete_old(req)).content

	@handle_http_exception(ServerError)
	async def _get_messages(self, schema: ChatSVCGetLatest) -> MessagesReturn:
		"""
		Get messages and delete old messages. When received messages > maximum messages, the delete old will run.

		Note: Delete all apply only received messages, not for all messages in db.
		That means if a client gets messages < max messages. The delete old will NOT run despite num messages in db > maximum messages.
		This is intentional for overall performance. Because delete only also happens when create a new message.
		"""
		req = ClientRequestSchema[ChatSVCGetLatest](body=schema,
		                                            timeout=CONFIG.datastore_request_timeout.message_get_latest)
		res = await DATASTORE.chat.message.get_latest(req)

		# Delete old
		if len(res.content.messages) > CONFIG.max_messages:
			await self._delete_old_messages(
				ChatSVCDeleteOld(token_id=schema.token_id, chat_session_id=schema.chat_session_id,
				                 remain=CONFIG.max_messages))
			# request again to confirm.
			res = await DATASTORE.chat.message.get_latest(req)
			assert len(res.content.messages) <= CONFIG.max_messages
		return res.content

	@handle_http_exception(ServerError)
	async def _create_message(self, schema: ChatMessageSVCCreate) -> MessagesReturn:
		"""
		Create new messages and check if messages <= max messages.
		"""
		c_req = ClientRequestSchema[ChatMessageSVCCreate](body=schema,
		                                                  timeout=CONFIG.datastore_request_timeout.message_create)
		_ = await DATASTORE.chat.message.create(c_req)

		messages = await self._get_messages(
			ChatSVCGetLatest(token_id=schema.token_id, chat_session_id=schema.chat_session_id,
			                 n=-1))  # This will activate delete old in get_massage.content
		# assert len(messages.messages)<= CONFIG.max_messages # already assert in get_messages.
		return messages

	# Chat summary
	@handle_http_exception(ServerError)
	async def _delete_old_chat_summaries(self, schema: ChatSVCDeleteOld) -> dict | None:
		req = ClientRequestSchema[ChatSVCDeleteOld](body=schema,
		                                            timeout=CONFIG.datastore_request_timeout.summary_delete_old)
		return (await DATASTORE.chat.summary.delete_old(req)).content

	@handle_http_exception(ServerError)
	async def _get_chat_summaries(self, schema: ChatSVCGetLatest) -> ChatSummariesReturn:
		req = ClientRequestSchema[ChatSVCGetLatest](body=schema,
		                                            timeout=CONFIG.datastore_request_timeout.summary_get_latest)
		res = await DATASTORE.chat.summary.get_latest(req)

		# Delete old
		if len(res.content.summaries) > CONFIG.max_chat_summaries:
			await self._delete_old_chat_summaries(
				ChatSVCDeleteOld(token_id=schema.token_id, chat_session_id=schema.chat_session_id,
				                 remain=CONFIG.max_chat_summaries))
			# request again to confirm.
			res = await DATASTORE.chat.summary.get_latest(req)
			assert len(res.content.summaries) <= CONFIG.max_chat_summaries
		return res.content

	@handle_http_exception(ServerError)
	async def _create_chat_summary(self, schema: ChatSummarySVCCreate) -> ChatSummariesReturn:
		c_req = ClientRequestSchema[ChatSummarySVCCreate](body=schema,
		                                                  timeout=CONFIG.datastore_request_timeout.summary_create)
		_ = await DATASTORE.chat.summary.create(c_req)

		summaries = await self._get_chat_summaries(
			ChatSVCGetLatest(token_id=schema.token_id, chat_session_id=schema.chat_session_id, n=-1))
		# assert len(messages.messages)<= CONFIG.max_messages # already assert in get_messages.
		return summaries

	# User summary
	@handle_http_exception(ServerError)
	async def _delete_old_user_summaries(self, schema: UserSummarySVCDeleteOld) -> dict | None:
		req = ClientRequestSchema[UserSummarySVCDeleteOld](body=schema,
		                                                   timeout=CONFIG.datastore_request_timeout.summary_delete_old)
		return (await DATASTORE.user.summary.delete_old(req)).content

	@handle_http_exception(ServerError)
	async def _get_user_summaries(self, schema: UserSummarySVCGetLatest) -> UserSummariesReturn:
		"""Get and delete old summaries."""
		req = ClientRequestSchema[UserSummarySVCGetLatest](body=schema,
		                                                   timeout=CONFIG.datastore_request_timeout.summary_get_latest)
		res = await DATASTORE.user.summary.get_latest(req)

		if len(res.content.summaries) > CONFIG.max_user_summaries:
			_ = await self._delete_old_user_summaries(
				UserSummarySVCDeleteOld(token_id=schema.token_id, remain=CONFIG.max_user_summaries))
			res = await DATASTORE.user.summary.get_latest(req)
			assert len(res.content.summaries) <= CONFIG.max_user_summaries
		return res.content

	@handle_http_exception(ServerError)
	async def _create_user_summary(self, schema: UserSummarySVCCreate) -> UserSummariesReturn:
		req = ClientRequestSchema[UserSummarySVCCreate](body=schema,
		                                                timeout=CONFIG.datastore_request_timeout.summary_create)
		_ = await DATASTORE.user.summary.create(req)
		summaries = await self._get_user_summaries(UserSummarySVCGetLatest(token_id=schema.token_id, n=-1))
		return summaries

class ChatAssistantSVC(_DataSVC):
	"""
	1. Do heartbeat for cache.
	2. Operation start and stop assistant.
	3. Persist messages, handle access token invalid at the end.
	"""

	@handle_http_exception(ServerError)
	async def chat(self, assistant_name:str, chat_session_id:UUID, userdata:UserData):
		"""
		Heartbeat
		Args:
			assistant_name:
			chat_session_id:
			userdata:
		Returns:
		"""
		try:
			cs = await userdata.get_c
		except asyncio.CancelledError:
			raise
		finally:
			pass

chat_assistant_svc = ChatAssistantSVC()

