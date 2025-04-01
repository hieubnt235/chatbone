from .base import BaseConfig


class AuthConfig(BaseConfig):
    token_duration_seconds:int
    jwt_encode_algorithm:str

    @staticmethod
    def key() -> str:
        return "auth"
