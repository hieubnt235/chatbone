from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from chatbone_utils.func import utc_now
from chatbone_utils.mixin import ModelMixin
class Base(ModelMixin, DeclarativeBase):
	created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=utc_now, index=True)


class Service(Base):
	__tablename__ = 'services'