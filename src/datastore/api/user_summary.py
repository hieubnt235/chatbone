from uuid import UUID

from fastapi import APIRouter

from datastore.svc.cm import get_user_summary_svc
from datastore.svc.user_svc import UserSummarySVCCreate, UserSummarySVCGetLatest, UserSummariesReturn, \
	UserSummarySVCDeleteOld

router = APIRouter()

@router.post('/create')
async def create(summary_create: UserSummarySVCCreate):
	async with get_user_summary_svc( ) as svc:
		await svc.create_summary(summary_create)
		return dict(info="Create user summary successfully.")

@router.get('/get')
async def get_latest(token_id:UUID, n:int=-1)-> UserSummariesReturn:
	schema = UserSummarySVCGetLatest(token_id=token_id, n=n)
	async with get_user_summary_svc() as svc:
		return await svc.get_latest_summaries(schema)

@router.delete('/delete')
async def delete_old(delete_schema: UserSummarySVCDeleteOld):
	async with get_user_summary_svc() as svc:
		await svc.delete_old_summaries(delete_schema)
		return dict(info=f"Delete old summaries successfully.")