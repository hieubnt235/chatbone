from pydantic import BaseModel


class UserRegister(BaseModel):
	username: str
	password: str

class UserAuthenticate(UserRegister):
	scope:str=""
	grant_type:str="password"

class TokenJWT(BaseModel):
	access_token:str
	token_type:str='bearer'