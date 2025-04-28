from typing import Annotated

from fastapi import FastAPI, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

from auth.auth_svc import auth_svc, UserRegister, TokenJWT
from utilities.settings.clients.datastore import UserInfoReturn

app = FastAPI()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/authenticate")

@app.post('/register')
async def register(schema: UserRegister)->TokenJWT:
	jwt= await auth_svc.register(schema)
	return TokenJWT(access_token=jwt, token_type='bearer')

@app.post('/authenticate')
async def authenticate(schema : Annotated[OAuth2PasswordRequestForm,Depends()] )->TokenJWT:
	jwt = await auth_svc.authenticate(UserRegister(username=schema.username,password=schema.password))
	return TokenJWT(access_token=jwt, token_type='bearer')

@app.get('/get_user')
async def get_user(jwt: Annotated[str, Depends(oauth2_scheme) ] )->UserInfoReturn:
	return await auth_svc.get_user(jwt)


if __name__=='__main__':
	import uvicorn
	uvicorn.run("app:app", reload=True)