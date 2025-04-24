import functools
import inspect
import traceback
from typing import Any

from fastapi import HTTPException

from chatbone_utils.logger import logger
from chatbone_utils.typing import FUNCTYPE


class BaseMethodException(Exception):
    """
    This class should be derived and used by handle_exception(), not intent to used directly.
    """
    def __init__(self,
                 pre_exp: Exception|None=None,
                 method:str="",
                 *,
                 classname:str="",
                 message: str = "ERROR"):
        super().__init__(message)
        self.message = message
        self.pre_exp:Exception = pre_exp
        self.method = method
        self.classname=classname

    def __str__(self):
        return (f"\n<{"="*20}{self.classname}.{self.method} Exception{"="*20}>\n"
                f"<{self.pre_exp.__class__.__name__}: {self.pre_exp}>\n"
                f"<{self.classname}.{self.method}: {self.message}>\n"
                f"<{"-"*20}{self.classname}.{self.method} Exception{"-"*20}>")

def _get_method_classname(func:FUNCTYPE, arg0: Any)->dict[str,str]:
    r = dict(method=func.__name__, classname="")
    if a:=getattr(arg0,"__name__",None): # cls
        r['classname'] = a
    elif a:=getattr(arg0,"__class__",None): # self
        r['classname']=a.__name__

    return r


def _handle(e:Exception,exception_type:type[BaseMethodException],func,args0,message):
    pe = e
    logger.error(f"\nCaught \'{e.__class__.__name__}\': {e}.\n"
                 f"TRACE EXCEPTION ROOT:")
    while getattr(pe,'pre_exp',None) is not None:
        pe=pe.pre_exp
        logger.error(f"\n\'Traceback:{pe.__traceback__} {type(pe)}\': {pe}")
    logger.error(f"Reraise {exception_type.__name__} ")

    raise exception_type(e,
                         **_get_method_classname(func, args0),
                         message=message)


def handle_exception(exception_type:type[BaseMethodException]=BaseMethodException,*,
                     message:Any="ERROR",
                     handle=_handle)->Any:
    """
    Decorator that automatically catch all exceptions type raised in method/function (especially from external libraries),
    convert and reraise BaseMethodException.

    This function make a new message using message from previous raise, along with classname and method name.
    Intentionally use for track the method and class that raised at low level adapter (repo).
    Examples:

        class ClassAException(BaseMethodException):
            pass

        class A:
            @handle_exception(ClassAException) \n
            def foo():
                ...
    Args:
        handle:
        exception_type: The exception type to handle.
        message: message from method.
    """
    def decorator(func: FUNCTYPE):
        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    args0 = [] if not len(args)>0 else args[0]
                    return handle(e,exception_type,func,args0,message)

        else:
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                try:
                    return func(*args,**kwargs)
                except Exception as e:
                    args0 = [] if not len(args)>0 else args[0]
                    return handle(e, exception_type, func, args0, message)

        return wrapper
    return decorator


def _handle_http(e, http_exception:HTTPException,*args):
    assert args==args # dump use, ignore it.

    if isinstance(e,HTTPException):
        raise # If it is HTTP one, raise it.

    pe = e
    logger.error(f"\nCaught \'{e.__class__.__name__}\': {e}.\n"
                 f"TRACE EXCEPTION ROOT:")
    while getattr(pe, 'pre_exp', None) is not None:
        pe = pe.pre_exp
        logger.error(f"\n\'{type(pe)}\': {pe}")

    logger.error(f"\nReraise HTTP {http_exception}")
    raise http_exception


handle_http_exception = functools.partial(handle_exception,handle=_handle_http)


def find_root_pre_exp(e: BaseMethodException):
    while getattr(e,'pre_exp',None) is not None:
        e=e.pre_exp
    return e

def _handle_tools(*args)->str:
    e,func,m = args[0], args[2], args[4]
    return (f"An error occur when calling tool {func.__name__}: '{e}'.\n"
            f"{m}")

handle_tools_exception = functools.partial(handle_exception,handle=_handle_tools)

__all__=["BaseMethodException",
         "handle_exception",
         "handle_http_exception"]
