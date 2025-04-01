from typing import Sequence, Literal
from uuid import UUID

from pydantic import validate_call
from sqlalchemy.ext.asyncio import AsyncSession

from chatbone.configs import chatbone_configs
from chatbone.repositories import ChatRepo
from chatbone.repositories.entities.chat import Message
from chatbone import TokenError, handle_http_exception, ServerError, TooManySessionsError, MessagesTooLongError
from .schemas import ReturnMessage


class ChatService:
    def __init__(self,session: AsyncSession):
        self.chat_repo = ChatRepo(session)
        self.config = chatbone_configs.chat_config
        self.max_messages_per_session = self.config.max_messages_per_session
        self.max_sessions_per_user=self.config.max_sessions_per_user
        self.max_message_length = self.config.max_message_length

    @handle_http_exception(ServerError)
    async def verify_token(self,token_id:UUID):
        if not await self.chat_repo.verify_token(token_id):
            raise TokenError

    @handle_http_exception(ServerError)
    async def create_chat_session(self,token_id:UUID)->UUID:
        await self.verify_token(token_id)

        if (len(await self.list_chat_sessions(token_id=token_id))) >= self.max_sessions_per_user:
            raise TooManySessionsError
        if (chat_id:=await self.chat_repo.create_chat_session(token_id=token_id)) is None:
            raise TokenError
        return chat_id

    async def chat(self):
        """
        //TODO
        receive user message -> store it in db -> pass the whole session to workflow -> stream output -> Store message to db and cache.
        //TODO test graphdb, redis cache technique, ... 
        Returns:

        """
        pass

    @handle_http_exception(ServerError)
    async def list_chat_sessions(self,token_id:UUID)->Sequence[UUID]:
        if (chat_ids:=await self.chat_repo.list_chat_sessions(token_id=token_id)) is None:
            raise TokenError
        return chat_ids

    @handle_http_exception(ServerError)
    async def delete_chat_sessions(self,token_id:UUID, chat_ids:Sequence[UUID]|UUID):
        await self.verify_token(token_id)

        chat_ids = [chat_ids] if not isinstance(chat_ids,Sequence) else chat_ids
        await self.chat_repo.delete_chat_sessions(chat_ids=chat_ids)

    async def _get_messages(self,*,token_id:UUID, chat_id: UUID)-> Sequence[Message]:
        await self.verify_token(token_id)
        return await self.chat_repo.get_messages(chat_id=chat_id)

    @handle_http_exception(ServerError)
    async def get_messages(self,*,token_id:UUID, chat_id: UUID)-> list[ReturnMessage]:
        messages = await self._get_messages(token_id=token_id,chat_id=chat_id)
        return [ReturnMessage.model_validate(m,from_attributes=True) for m in messages]

    @handle_http_exception(ServerError)
    @validate_call
    async def create_message(self,*,token_id:UUID, chat_id: UUID,
                             role:Literal["user","assistant","system"], content:str) ->ReturnMessage:
        messages = await self._get_messages(token_id=token_id,chat_id=chat_id) #already verify token.

        if len(content)> self.max_message_length:
            raise MessagesTooLongError

        if (delta:= len(messages)-self.max_messages_per_session) >=0:
            del_ids = [m.id for m in messages[-(delta+1):]]
            await self.chat_repo.delete_messages(message_ids=del_ids)

        new_message = await self.chat_repo.create_message(chat_id=chat_id,role=role,content=content)
        return ReturnMessage.model_validate(new_message, from_attributes=True)
