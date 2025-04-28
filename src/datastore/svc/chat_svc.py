import asyncio
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from utilities.settings.clients.datastore.schemas.chat_svc import *
from utilities.exception import handle_http_exception
from datastore.entities import Message, ChatSession, ChatSummary
from datastore.repo import ChatRepo
from .base import BaseSVC, InvalidRequestError, ServerError


## RETURN SCHEMAS helper for client validate and parse json.
def _make_chat_messages(messages: Sequence[Message]) -> MessagesReturn:
	return MessagesReturn(messages=[MessageReturn.model_validate(m) for m in messages])


def _make_chat_summaries(summaries: Sequence[ChatSummary]) -> ChatSummariesReturn:
	return ChatSummariesReturn(summaries=[ChatSummaryReturn.model_validate(s) for s in summaries])


class ChatSVC(BaseSVC):
	def __init__(self, session: AsyncSession):
		super().__init__(session)
		self.chat_repo = ChatRepo(session)

	@handle_http_exception(ServerError)
	async def _get_chat_session(self, schema: ChatSessionGet) -> ChatSession:
		"""
        Retrieve a chat session if the user owns it. Raise an error otherwise.
        Args:
            schema (ChatSessionGet): Schema containing the token ID and chat session ID.
        Returns:
            ChatSession: The retrieved chat session.
        Raises:
            InvalidRequestError: If the chat session is not found or not owned by the user.
            TokenError: If the token is invalid.
		"""
		token = await self._get_token(schema.token_id)
		if (cs := await self.chat_repo.get_chat_session(token.user, schema.chat_session_id)) is None:
			raise InvalidRequestError
		return cs


class ChatSessionSVC(ChatSVC):
	"""
	Service class for chat session-related operations.

    Methods:
        - create_chat_session: Create a new chat session.
        - delete_chat_sessions: Delete specified chat sessions.
	"""

	@handle_http_exception(ServerError)
	async def create_chat_session(self, schema: ChatSVCBase) -> ChatSessionReturn:
		"""
		Create a new chat session for the user.
		"""
		token = await self._get_token(schema.token_id)
		cs = await self.chat_repo.create_chat_session(token.user)
		return ChatSessionReturn(id=cs.id)

	@handle_http_exception(ServerError)
	async def delete_chat_sessions(self, schema: ChatSessionSVCDelete):
		"""
		Delete specified chat sessions.
		"""
		token = await self._get_token(schema.token_id)
		await self._check_valid_request(schema.chat_session_ids, token.user.chat_sessions, own_key='id')
		await self.chat_repo.delete_chat_sessions(token.user, schema.chat_session_ids)


class ChatMessageSVC(ChatSVC):
	"""
	Service class for chat message-related operations.

    Methods:
        - create_message: Create a new chat message.
        - get_latest_messages: Retrieve the latest chat messages.
        - delete_old_messages: Delete old chat messages while retaining a specified number.
	"""

	@handle_http_exception(ServerError)
	async def create_message(self, schema: ChatMessageSVCCreate):
		"""
		Create a new chat message in a chat session.
		"""
		cs = await self._get_chat_session(schema)
		await self.chat_repo.create_message(cs, Message(role=schema.role, content=schema.content))

	@handle_http_exception(ServerError)
	async def get_latest_messages(self, schema: ChatSVCGetLatest) -> MessagesReturn:
		"""
		Retrieve the latest chat messages from a chat session.
		"""
		cs = await self._get_chat_session(schema)
		messages = await self.chat_repo.get_messages(cs, schema.n)
		return await asyncio.to_thread(_make_chat_messages, messages)

	@handle_http_exception(ServerError)
	async def delete_old_messages(self, schema: ChatSVCDeleteOld):
		"""Delete old chat messages while retaining a specified number.
		"""
		cs = self._get_chat_session(schema)
		await self.chat_repo.delete_old_messages(cs, schema.remain)


class ChatSummarySVC(ChatSVC):
	"""
	Service class for chat summary-related operations.

    Methods:
        - create_summary: Create a new chat summary.
        - get_latest_summaries: Retrieve the latest chat summaries.
        - delete_old_summaries: Delete old chat summaries while retaining a specified number.

	"""

	@handle_http_exception(ServerError)
	async def create_summary(self, schema: ChatSummarySVCCreate):
		"""Create a new chat summary for a chat session."""
		cs = await self._get_chat_session(schema)
		await self.chat_repo.create_summary(cs, schema.summary)

	@handle_http_exception(ServerError)
	async def get_latest_summaries(self, schema: ChatSVCGetLatest) -> ChatSummariesReturn:
		"""Retrieve the latest chat summaries from a chat session."""
		cs = await self._get_chat_session(schema)
		summaries = await self.chat_repo.get_summaries(cs, schema.n)
		return await asyncio.to_thread(_make_chat_summaries, summaries)

	@handle_http_exception(ServerError)
	async def delete_old_summaries(self, schema: ChatSVCDeleteOld):
		"""Delete old chat summaries while retaining a specified number."""
		cs = await self._get_chat_session(schema)
		await self.chat_repo.delete_old_summaries(cs, schema.remain)
