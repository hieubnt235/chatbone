from contextlib import asynccontextmanager, AbstractAsyncContextManager

from datastore.settings.cm import get_session
from .chat_svc import ChatSessionSVC, ChatMessageSVC, ChatSummarySVC
from .user_svc import UserAccessSVC, UserSummarySVC

AnySVC = UserAccessSVC | UserSummarySVC

# APIs use CM for service access, do not need about session.

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
