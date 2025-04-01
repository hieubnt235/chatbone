import functools

from fastapi import HTTPException, status
from .logger import logger
from .configs import chatbone_configs
from .utils.exception import handle_exception


AlreadyRegisterError = HTTPException(status_code=status.HTTP_409_CONFLICT,
                                     detail="User already register.")

UsernameNotFoundError= HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                     detail="Username not found, please register first.")

AuthenticationError = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                    detail="Username or password is not correct.")

TokenError=HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                       detail="Token is not valid.")

ServerError= HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                           detail="Server error.")

max_sessions = chatbone_configs.chat_config.max_sessions_per_user
TooManySessionsError=HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                  detail=f"Only allow {max_sessions} sessions at once, you must delete some to make a new one.")

messages_length=chatbone_configs.chat_config.max_message_length
MessagesTooLongError=HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                   detail=f"Message is too long. Maximum length is {messages_length} characters.")

def _handle_http(e, http_exception:HTTPException,*args):
    assert args
    logger.debug(f"\nCaught {type(e).__name__}: {e}"
                 f"\nReraise {http_exception} ")
    if isinstance(e,HTTPException):
        raise # If it is HTTP one, raise it.
    else:
        raise http_exception
handle_http_exception = functools.partial(handle_exception,handle=_handle_http)


__all__=["handle_http_exception",
         "AlreadyRegisterError",
         "UsernameNotFoundError",
         "AuthenticationError",
         "TokenError",
         "ServerError","TooManySessionsError","MessagesTooLongError"]