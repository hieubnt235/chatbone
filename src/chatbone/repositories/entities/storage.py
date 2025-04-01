from uuid import UUID

from sqlalchemy import Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from uuid_extensions import uuid7


class Base(DeclarativeBase):
    pass

class Document(Base):
    __tablename__ = 'documents'
    id: Mapped[UUID] = mapped_column(default=uuid7,
                                     primary_key=True)
    summary: Mapped[str|None] = mapped_column(Text)