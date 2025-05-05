from contextlib import asynccontextmanager, AbstractAsyncContextManager

from utilities.typing import SESSION_CONTEXTMANAGER
from .chat_svc import ChatSessionSVC, ChatMessageSVC, ChatSummarySVC
from .user_svc import UserAccessSVC, UserSummarySVC
from ..settings import datastore_settings


def get_session() -> SESSION_CONTEXTMANAGER:
	return datastore_settings.db.session()

AnySVC = UserAccessSVC | UserSummarySVC

# APIs use CM for service access, do not need to know about the session.

@asynccontextmanager
async def get_svc(svc_type: type[AnySVC]) -> AbstractAsyncContextManager[AnySVC]:
	async with get_session() as session:
		yield svc_type(session)

@asynccontextmanager
async def get_user_access_svc() -> AbstractAsyncContextManager[UserAccessSVC]:
	async with get_svc(UserAccessSVC) as svc:
		yield svc

@asynccontextmanager
async def get_user_summary_svc() -> AbstractAsyncContextManager[UserSummarySVC]:
	async with get_svc(UserSummarySVC) as svc:
		yield svc

@asynccontextmanager
async def get_chat_session_svc()-> AbstractAsyncContextManager[ChatSessionSVC]:
	async with get_svc(ChatSessionSVC) as svc:
		yield svc

@asynccontextmanager
async def get_chat_message_svc()-> AbstractAsyncContextManager[ChatMessageSVC]:
	async with get_svc(ChatMessageSVC) as svc:
		yield svc

@asynccontextmanager
async def get_chat_summary_svc()-> AbstractAsyncContextManager[ChatSummarySVC]:
	async with get_svc(ChatSummarySVC) as svc:
		yield svc
