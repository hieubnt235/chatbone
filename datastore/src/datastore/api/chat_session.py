from fastapi import APIRouter

from datastore.svc.chat_svc import ChatSVCBase, ChatSessionReturn, ChatSessionSVCDelete
from datastore.svc.cm import get_chat_session_svc

router = APIRouter()


@router.post('/create')
async def create(schema: ChatSVCBase) -> ChatSessionReturn:
	async with get_chat_session_svc() as svc:
		return await svc.create_chat_session(schema)


@router.post('/delete')
async def delete(schema: ChatSessionSVCDelete):
	async with get_chat_session_svc() as svc:
		await svc.delete_chat_sessions(schema)
		return dict(info="Delete successfully.")
