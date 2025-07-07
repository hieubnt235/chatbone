from uuid import UUID

from fastapi import APIRouter

from datastore.svc.chat_svc import ChatSVCGetLatest, ChatSVCDeleteOld, ChatSummarySVCCreate, ChatSummariesReturn
from datastore.svc.cm import get_chat_summary_svc

router = APIRouter()


@router.post('/create')
async def create(schema: ChatSummarySVCCreate):
	async with get_chat_summary_svc() as svc:
		await svc.create_summary(schema)
		return dict(info="Summary created successfully.")


@router.get('/get')
async def get_latest(token_id: UUID, chat_session_id: UUID, n: int = -1) -> ChatSummariesReturn:
	schema = ChatSVCGetLatest(token_id=token_id, chat_session_id=chat_session_id, n=n)
	async with get_chat_summary_svc() as svc:
		return await svc.get_latest_summaries(schema)


@router.delete('/delete')
async def delete_old(schema: ChatSVCDeleteOld):
	async with get_chat_summary_svc() as svc:
		await svc.delete_old_summaries(schema)
		return dict(info="Old chat summaries deleted successfully.")
