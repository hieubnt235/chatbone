from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import delete, select, and_

from datastore.entities import ChatSession, Message, User, ChatSummary
from utilities.exception import BaseMethodException, handle_exception
from utilities.mixin import RepoMixin


# TODO make repo abstraction
class ChatRepoException(BaseMethodException):
	pass


class ChatRepo(RepoMixin):

	@handle_exception(ChatRepoException)
	async def create_chat_session(self, user: User) -> ChatSession:
		"""
		Returns: Create and return chat_id if token is valid, else return None.
		"""
		await self.refresh(user)
		cs = ChatSession()
		user.chat_sessions.append(cs)
		await self.flush()
		await self.refresh(cs)
		return cs

	@handle_exception(ChatRepoException)
	async def delete_chat_sessions(self, user: User, chat_session_ids: list[UUID]):
		"""
		Delete if user own it.THIS METHOD JUST DELETE AND DON'T CHECK WHOSE SESSION IS. SERVICE HAS TO CHECK IT.
		Args:
		    user:
			chat_session_ids:

		Returns:

		"""
		q = delete(ChatSession).where(and_(ChatSession.id.in_(chat_session_ids), ChatSession.user_id == user.id))
		await self._session.execute(q)
		await self.flush()

	@handle_exception(ChatRepoException)
	async def get_chat_session(self, user: User, chat_session_id: UUID) -> ChatSession | None:
		"""
		Return chat session if user has it (defined by id).
		Args:
			user:
			chat_session_id:
		"""
		q = select(ChatSession).where(and_(ChatSession.id == chat_session_id, ChatSession.user_id == user.id))
		return await self._session.scalar(q)

	@handle_exception(ChatRepoException)
	async def get_messages(self, chat_session: ChatSession, n: int = -1) -> Sequence[Message]:
		"""
		Get n latest messages.
		If limit <0, return all messages."""
		q = chat_session.messages.select().order_by(Message.created_at.desc())
		if n >= 0:
			q = q.limit(n)
		ms = await self._session.scalars(q)
		return ms.all()

	@handle_exception(ChatRepoException)
	async def create_message(self, chat_session: ChatSession, message: Message):
		await self.refresh(chat_session)
		self._session.add(chat_session)
		chat_session.messages.add(message)
		await self.flush()

	@handle_exception(ChatRepoException)
	async def delete_old_messages(self, chat_session: ChatSession, max_messages: int):
		assert max_messages >= 0
		sq = (select(Message.id).where(Message.chat_session_id == chat_session.id).order_by(
			Message.created_at.desc()).offset(max_messages).subquery())
		await self._session.execute(chat_session.messages.delete().where(
			and_(Message.id.in_(sq), Message.chat_session_id == chat_session.id)))  # defensive
		await self.flush()

	@handle_exception(ChatRepoException)
	async def create_summary(self, chat_session: ChatSession, summary: str):
		await self.refresh(chat_session)
		self._session.add(chat_session)
		chat_session.summaries.add(ChatSummary(summary=summary))
		await self.flush()

	@handle_exception(ChatRepoException)
	async def get_summaries(self, chat_session: ChatSession, n: int) -> Sequence[ChatSummary]:
		"""
		Get n latest summaries.
		Args:
		    chat_session:
			n:
		Returns:
		"""
		q = chat_session.summaries.select().order_by(ChatSummary.created_at.desc())
		if n >= 0:
			q = q.limit(n)
		r = await self._session.scalars(q)
		return r.all()

	@handle_exception(ChatRepoException)
	async def delete_old_summaries(self, chat_session: ChatSession, max_summaries: int):
		"""
		Delete old summaries while keeping the length of remaining summaries <= max_summaries.
		If max_summaries==0 delete all  summaries.
		Args:
		    chat_session:
			max_summaries:
		"""
		assert max_summaries >= 0
		sq = (select(ChatSummary.id).where(ChatSummary.chat_session_id == chat_session.id).order_by(
			ChatSummary.created_at.desc()).offset(max_summaries).subquery())
		await self._session.execute(chat_session.summaries.delete().where(
			and_(ChatSummary.id.in_(sq), ChatSummary.chat_session_id == chat_session.id)))
		await self.flush()

	@handle_exception(ChatRepoException)
	async def flush(self):
		await self._session.flush()

	@handle_exception(ChatRepoException)
	async def refresh(self, obj: Any):
		await self._session.flush()


__all__ = ["ChatRepo", "ChatRepoException"]
