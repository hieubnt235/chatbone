__all__ = ['MessageCreate', 'ChatSessionRequest', 'ChatSVCBase', 'ChatSessionGet', 'ChatSessionSVCDelete',
           'ChatMessageSVCCreate', 'ChatSummarySVCCreate', 'ChatSVCGetLatest', 'ChatSVCDeleteOld', 'MessageReturn',
           'MessagesReturn', 'ChatSessionReturn', 'ChatSummaryReturn', 'ChatSummariesReturn']

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, PositiveInt


# REQUEST SCHEMAS
class MessageCreate(BaseModel):
	role: Literal['user', 'system', 'assistant']
	content: str


class ChatSessionRequest(BaseModel):
	token_id: UUID
	chat_session_id: UUID


class ChatSVCBase(BaseModel):
	model_config = ConfigDict(validate_assignment=True, validate_default=True)
	token_id: UUID


class ChatSessionGet(ChatSVCBase):
	chat_session_id: UUID


class ChatSessionSVCDelete(ChatSVCBase):
	chat_session_ids: list[UUID]


class ChatMessageSVCCreate(ChatSessionGet, MessageCreate):
	pass


class ChatSummarySVCCreate(ChatSessionGet):
	summary: str


class ChatSVCGetLatest(ChatSessionGet):
	n: int = -1  # get all


class ChatSVCDeleteOld(ChatSessionGet):
	remain: PositiveInt


# RETURN SCHEMAS

class MessageReturn(BaseModel):
	role: Literal['user', 'system', 'assistant']
	content: str
	id: UUID
	created_at: datetime


class MessagesReturn(BaseModel):
	messages: list[MessageReturn]


class ChatSessionReturn(BaseModel):
	id: UUID  # Yeah, only id 😀


class ChatSummaryReturn(BaseModel):
	id: UUID
	chat_session_id: UUID
	summary: str


class ChatSummariesReturn(BaseModel):
	summaries: list[ChatSummaryReturn]
