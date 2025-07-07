from uuid import UUID

from fastapi import APIRouter

from datastore.svc.cm import get_user_access_svc
from datastore.svc.user_svc import UserInfoReturn, UserCreate, UserVerify, Token, TokenDelete

router = APIRouter()


@router.post('/create')
async def create(user_cre: UserCreate) -> UserInfoReturn:
	async with get_user_access_svc() as svc:
		return await svc.create_user(user_cre)


@router.post('/verify')
async def verify(user_ver: UserVerify) -> UserInfoReturn:
	async with get_user_access_svc() as svc:
		return await svc.verify_user(user_ver)


@router.get('/get')
async def get(token_id: UUID) -> UserInfoReturn:
	async with get_user_access_svc() as svc:
		return await svc.get_user(Token(token_id=token_id))


@router.delete('/delete')
async def delete(token: Token) -> UserInfoReturn:
	async with get_user_access_svc() as svc:
		user = await svc.get_user(token)
		await svc.delete_user(token)
		user.addition_info = "This user is deleted successfully."
		return user


@router.delete('/delete_tokens')
async def delete_token(tokens_delete: TokenDelete):
	async with get_user_access_svc() as svc:
		await svc.delete_tokens(tokens_delete)
		return dict(info="Deleted successfully.")
