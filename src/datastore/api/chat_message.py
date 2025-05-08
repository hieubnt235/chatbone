from uuid import UUID

from fastapi import APIRouter

from datastore.svc.chat_svc import ChatMessageSVCCreate, ChatSVCGetLatest, ChatSVCDeleteOld, MessagesReturn
from datastore.svc.cm import get_chat_message_svc

router = APIRouter()


@router.post('/create')
async def create(schema: ChatMessageSVCCreate):
	async with get_chat_message_svc() as svc:
		await svc.create_message(schema)
		return dict(info="Message created successfully.")


@router.get('/get')
async def get_latest(token_id: UUID, chat_session_id: UUID, n: int = -1) -> MessagesReturn:
	schema = ChatSVCGetLatest(token_id=token_id, chat_session_id=chat_session_id, n=n)
	async with get_chat_message_svc() as svc:
		return await svc.get_latest_messages(schema)


@router.delete('/delete')
async def delete_old(schema: ChatSVCDeleteOld):
	async with get_chat_message_svc() as svc:
		await svc.delete_old_messages(schema)
		return dict(info="Old messages deleted successfully.")
