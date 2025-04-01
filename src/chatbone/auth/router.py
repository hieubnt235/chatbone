from fastapi import APIRouter

from .dependencies import RegisterDep, AuthenticateDep
from .schemas import AuthenticatedToken

auth_router = APIRouter(prefix='/auth')

@auth_router.post('/register')
async def register(token:RegisterDep)-> AuthenticatedToken:
    return token


@auth_router.post("/token")
async def login(jwt_token: AuthenticateDep)->AuthenticatedToken:
    return jwt_token




