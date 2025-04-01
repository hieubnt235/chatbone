from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from chatbone.settings import chatbone_settings



ChatDBSessionDep = Annotated[AsyncSession,Depends(chatbone_settings.chat_db._get_async_session)]
"""Yield chatdb session. It does not raise HTTPException but FastAPI will catch it and raise
InternalError."""