import functools
import inspect
from typing import Any

from chatbone.logger import logger
from chatbone.utils.typing import FUNCTYPE


class BaseMethodException(Exception):
    """
    This class should be derived and used by handle_exception(), not intent to used directly.
    """
    def __init__(self,
                 pre_exp: Exception,
                 method:str,
                 *,
                 classname:str="",
                 message: str = "ERROR"):
        super().__init__(message)
        self.message = message
        self.pre_exp = pre_exp
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

def _handle(e,exception_type:type[BaseMethodException],func,args0,message):
    logger.debug(f"\nCaught {e.__class__.__name__}"
                 f"\nReraise {exception_type.__name__} ")
    raise exception_type(e,
                         **_get_method_classname(func, args0),
                         message=message)


def handle_exception(exception_type:type[BaseMethodException], message:str="ERROR",handle=_handle)->Any:
    """
    Decorator that automatically catch all exceptions type raised in method/function (especially from external libraries),
    convert and reraise BaseMethodException.

    This function make a new message using message from previous raise, along with classname and method name.
    Intentionally use for track the method and class that raised at low level adapter (repositories).
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
                    handle(e,exception_type,func,args0,message)

        else:
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                try:
                    return func(*args,**kwargs)
                except Exception as e:
                    args0 = [] if not len(args)>0 else args[0]
                    handle(e, exception_type, func, args0, message)

        return wrapper
    return decorator

__all__=["BaseMethodException",
         "handle_exception"]
