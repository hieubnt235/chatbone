from .base import BaseConfig

class ChatConfig(BaseConfig):

    @staticmethod
    def key() -> str:
        return "chat"

    max_messages_per_session: int
    max_sessions_per_user: int
    max_message_length:int
