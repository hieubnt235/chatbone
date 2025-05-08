__all__ = ['UserCredentials', 'UserCreate', 'UserVerify', 'Token', 'TokenDelete', 'UserSummarySVCCreate',
           'UserSummarySVCGetLatest', 'UserSummarySVCDeleteOld', 'TokenInfoReturn', 'UserInfoReturn',
           'UserSummaryReturn', 'UserSummariesReturn']

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, PositiveInt

from utilities.func import get_expire_date_factory


# UUID = UUID7

##### REQUEST SCHEMAS

class UserCredentials(BaseModel):
	username: str
	hashed_password: str


class UserCreate(UserCredentials):
	expires_at: datetime = Field(default_factory=get_expire_date_factory(43200))
	"""UTC format datatime."""


class UserVerify(UserCreate):
	create_token_flag: Literal['always', 'if_empty', "if_all_expired", "none"] = 'if_all_expired'
	hashed_password: str | None = Field(None, deprecated=True,
	                                    description="Future hash algorithm hash one pwd into multiple pwd, so cannot use this value to compare.")
	password: str


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
	addition_info: dict = Field(default_factory=dict)


class UserSummaryReturn(BaseModel):
	id: UUID
	summary: str


class UserSummariesReturn(BaseModel):
	summaries: list[UserSummaryReturn]
