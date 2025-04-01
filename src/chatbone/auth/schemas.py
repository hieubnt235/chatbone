from pydantic import BaseModel, ConfigDict


class User(BaseModel):
    model_config = ConfigDict(validate_assignment=True,validate_default=True)
    username:str

class UserIn(User):
    password:str

class UserCredentials(User):
    hashed_password:str

class AuthenticatedToken(BaseModel):
    """
    Attributes:
        access_token (str): The JWT token.
        token_type (str): The type of the token.
    """
    access_token:str
    token_type:str