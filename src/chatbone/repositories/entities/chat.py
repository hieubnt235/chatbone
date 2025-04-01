from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import (DeclarativeBase, Mapped, mapped_column,
                            relationship, WriteOnlyMapped)
from uuid_extensions.uuid7 import uuid7

from chatbone.utils.mixin import ModelMixin
from chatbone.utils.time import utc_now


class Base(ModelMixin, DeclarativeBase):
    pass


class User(Base):
    """
    Attributes:
        username:
        hashed_password:
    """
    __tablename__ = 'users'

    id: Mapped[UUID] = mapped_column(default=uuid7,
                                     primary_key=True)
    username: Mapped[str] = mapped_column(String(32),
                                          unique=True,
                                          index=True)
    hashed_password: Mapped[str] = mapped_column(String(256),
                                                 index=True)

    created_at: Mapped[datetime] = mapped_column(default=utc_now,
                                                 index=True)

    chat_sessions: Mapped[list['ChatSession']] = relationship(cascade='all, delete-orphan',
                                                              lazy='selectin'
                                                              )

    tokens: Mapped[list['AccessToken']] = relationship(cascade='all, delete-orphan',
                                                       lazy='selectin')


class ChatSession(Base):
    """
    Chat history between users and AI.
    """
    __tablename__ = 'chat_sessions'
    id: Mapped[UUID] = mapped_column(default=uuid7,
                                     primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'),
                                          index=True)

    created_at: Mapped[datetime] = mapped_column(default=utc_now,
                                                 index=True)

    # user: Mapped['User'] = relationship(back_populates='chat_sessions')
    messages: WriteOnlyMapped['Message'] = relationship(cascade='all, delete-orphan',
                                                        passive_deletes=True)


class Message(Base):
    __tablename__ = 'messages'
    id: Mapped[UUID] = mapped_column(default=uuid7,
                                     primary_key=True)
    chat_session_id: Mapped[UUID] = mapped_column(ForeignKey('chat_sessions.id', ondelete='CASCADE'),
                                                  index=True)

    role: Mapped[Literal['user', 'assistant', 'system']]
    content: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(default=utc_now,
                                                 index=True)

    # chat_session: Mapped['ChatSession'] = relationship(back_populates='messages',
    #                                                    lazy='joined',
    #                                                    innerjoin=True)


class AccessToken(Base):
    __tablename__ = 'access_tokens'

    id: Mapped[UUID] = mapped_column(default=uuid7,
                                     primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))

    created_at: Mapped[datetime] = mapped_column(default=utc_now,
                                                 index=True)
    expires_at: Mapped[datetime] = mapped_column(index=True)

    # user: WriteOnlyMapped['User'] = relationship(back_populates='tokens',uselist=True)


__all__ = ['Base', 'ChatSession', 'User', 'Message', 'AccessToken']
