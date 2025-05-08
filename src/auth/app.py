from typing import Annotated

from fastapi import FastAPI, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from ray import serve

from auth.auth_svc import auth_svc, UserRegister, TokenJWT
from utilities.settings.clients.datastore import UserInfoReturn

app = FastAPI(
	description="Authenticate service should be called by other services to filter data, not by user directly.")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="authenticate")


@app.post('/register')
async def register(schema: UserRegister) -> TokenJWT:
	jwt = await auth_svc.register(schema)
	return TokenJWT(access_token=jwt, token_type='bearer')


@app.post('/authenticate')
async def authenticate(schema: Annotated[OAuth2PasswordRequestForm, Depends()]) -> TokenJWT:
	jwt = await auth_svc.authenticate(UserRegister(username=schema.username, password=schema.password))
	return TokenJWT(access_token=jwt, token_type='bearer')


@app.get('/get_user')
async def get_user(jwt: Annotated[str, Depends(oauth2_scheme)]) -> UserInfoReturn:
	return await auth_svc.get_user(jwt)


@serve.deployment()
@serve.ingress(app)
class Auth:
	pass


app = Auth.bind()

if __name__ == '__main__':
	serve.run(app, blocking=True)  # import uvicorn  # uvicorn.run("app:app", reload=True)
