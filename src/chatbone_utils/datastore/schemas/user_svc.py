from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, PositiveInt, UUID7

from chatbone_utils.func import get_expire_date_factory

UUID = UUID7

##### REQUEST SCHEMAS

class UserCredentials(BaseModel):
	username: str
	hashed_password: str


class UserCreate(UserCredentials):
	expires_at: datetime = Field(default_factory=get_expire_date_factory(43200))
	"""UTC format datatime."""


class UserVerify(UserCreate):
	create_token_flag: Literal['always', 'if_empty', "if_all_expired", "none"] = 'if_all_expired'


class Token(BaseModel):
	token_id: UUID


class TokenDelete(Token):
	token_ids: list[UUID]


class UserSummarySVCCreate(Token):
	summary: str


class UserSummarySVCGetLatest(Token):
	n: int = -1


class UserSummarySVCDeleteOld(Token):
	remain: PositiveInt



# RETURN SCHEMAS
class TokenInfoReturn(BaseModel):
	id: UUID
	created_at: datetime
	expires_at: datetime

class UserInfoReturn(BaseModel):
	username: str
	hashed_password: str
	id: UUID
	created_at: datetime
	tokens: list[TokenInfoReturn]
	chat_ids: list[UUID]
	addition_info: dict=Field(default_factory=dict)

class UserSummaryReturn(BaseModel):
	id: UUID
	summary: str

class UserSummariesReturn(BaseModel):
	summaries: list[UserSummaryReturn]

