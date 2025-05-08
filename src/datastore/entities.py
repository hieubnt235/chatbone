from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import ForeignKey, String, Text, DateTime
from sqlalchemy.orm import (DeclarativeBase, Mapped, mapped_column, relationship, WriteOnlyMapped)
from uuid_extensions.uuid7 import uuid7

from utilities.func import utc_now
from utilities.mixin import ModelMixin


class Base(ModelMixin, DeclarativeBase):
	created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class User(Base):
	"""
	Attributes:
		username:
		hashed_password:
	"""
	__tablename__ = 'users'

	id: Mapped[UUID] = mapped_column(default=uuid7, primary_key=True)
	username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
	hashed_password: Mapped[str] = mapped_column(String(256), index=True)

	chat_sessions: Mapped[list['ChatSession']] = relationship(cascade='all, delete-orphan', lazy='selectin',
	                                                          passive_deletes=True)

	tokens: Mapped[list['AccessToken']] = relationship(cascade='all, delete-orphan', lazy='selectin',
	                                                   passive_deletes=True, back_populates='user')

	summaries: WriteOnlyMapped['UserSummary'] = relationship(cascade='all, delete-orphan', passive_deletes=True)


class UserSummary(Base):
	__tablename__ = 'user_summaries'
	id: Mapped[UUID] = mapped_column(default=uuid7, primary_key=True)
	user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
	summary: Mapped[str] = mapped_column(Text)


class ChatSession(Base):
	"""
	Chat history between users and AI.
	"""
	__tablename__ = 'chat_sessions'
	id: Mapped[UUID] = mapped_column(default=uuid7, primary_key=True)
	user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)

	messages: WriteOnlyMapped['Message'] = relationship(cascade='all, delete-orphan', passive_deletes=True)
	summaries: WriteOnlyMapped['ChatSummary'] = relationship(cascade='all, delete-orphan', passive_deletes=True)


class ChatSummary(Base):
	__tablename__ = 'chat_summaries'
	id: Mapped[UUID] = mapped_column(default=uuid7, primary_key=True)
	chat_session_id: Mapped[UUID] = mapped_column(ForeignKey('chat_sessions.id', ondelete='CASCADE'), index=True)
	summary: Mapped[str] = mapped_column(Text)


class Message(Base):
	__tablename__ = 'messages'
	id: Mapped[UUID] = mapped_column(default=uuid7, primary_key=True)
	chat_session_id: Mapped[UUID] = mapped_column(ForeignKey('chat_sessions.id', ondelete='CASCADE'), index=True)

	role: Mapped[Literal['user', 'assistant', 'system']]
	content: Mapped[str] = mapped_column(Text)


class AccessToken(Base):
	__tablename__ = 'access_tokens'

	id: Mapped[UUID] = mapped_column(default=uuid7, primary_key=True)
	user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
	expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now,
	                                             index=True)  # DEFAULT is expired intermediately
	user: Mapped['User'] = relationship(back_populates='tokens', lazy="joined", innerjoin=True)


__all__ = ['Base', 'ChatSession', 'User', 'Message', 'AccessToken']
