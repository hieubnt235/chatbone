from typing import Any, Literal, Sequence
from uuid import UUID

from sqlalchemy import delete, select

from chatbone.utils.exception import BaseMethodException, handle_exception
from .entities.chat import ChatSession, Message
from ._token import _TokenRepo


class ChatRepoException(BaseMethodException):
    pass

class ChatRepo(_TokenRepo):

    @handle_exception(ChatRepoException)
    async def create_chat_session(self,*, token_id: UUID)->UUID|None:
        """
        Returns: Create and return chat_id if token is valid, else return None.
        """
        if (user := await self._get_user(token_id)) is None:
            return None
        cs = ChatSession()
        user.chat_sessions.append(cs)
        await self.flush()
        await self.refresh(cs)
        return cs.id

    @handle_exception(ChatRepoException)
    async def list_chat_sessions(self,*,token_id:UUID)-> list[UUID]|None:
        if (user := await self._get_user(token_id)) is None:
            return None
        return [cs.id for cs in user.chat_sessions]

    @handle_exception(ChatRepoException)
    async def delete_chat_sessions(self,*,chat_ids:list[UUID]):
        q = delete(ChatSession).where(ChatSession.id.in_(chat_ids))
        await self._session.execute(q)
        await self.flush()

    @handle_exception(ChatRepoException)
    async def get_messages(self,*,chat_id: UUID,limit:int=-1)-> Sequence[Message]:
        """Returns: list of messages ordered from latest to oldest.
        If limit <0, return all messages."""
        q = select(Message).where(Message.chat_session_id==chat_id).order_by(Message.created_at.desc())
        if limit>0:
            q= q.limit(limit)

        ms = await self._session.scalars(q)
        return ms.all()

    @handle_exception(ChatRepoException)
    async def create_message(self,*, chat_id: UUID, role:Literal['system','user','assistant'],content:str
                             )->Message:
        cs = await self._session.scalar(select(ChatSession).where(ChatSession.id==chat_id))
        message = Message(role=role,content=content)
        cs.messages.add(message)
        await self.flush()
        await self.refresh(message)
        return message

    @handle_exception(ChatRepoException)
    async def delete_messages(self,*, message_ids: list[UUID]):
        await self._session.execute(delete(Message).where(Message.id.in_(message_ids)))



    @handle_exception(ChatRepoException)
    async def flush(self):
        await self._session.flush()

    @handle_exception(ChatRepoException)
    async def refresh(self, obj: Any):
        await self._session.flush()

__all__ = ["ChatRepo","ChatRepoException"]