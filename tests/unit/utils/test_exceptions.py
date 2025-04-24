import asyncio

import pytest
from fastapi import HTTPException

from chatbone_utils import (handle_http_exception,
                            ServerError,
                            AlreadyRegisterError)
from chatbone_utils.utils import handle_exception, BaseMethodException

PreHTTPException = HTTPException(status_code=500,detail="pre http test.")


class PreException(Exception):
    pass

class ExceptionTest(BaseMethodException):
    pass

class Class:
    @handle_exception(ExceptionTest, message="func")
    def func(self):
        raise PreException

    @handle_exception(ExceptionTest, message="afunc")
    async def afunc(self):
        raise PreException


    @handle_http_exception(ServerError)
    def func2(self):
        raise PreException

    @handle_http_exception(ServerError)
    async def afunc2(self):
        raise PreException

    @handle_http_exception(ServerError)
    def func3(self):
        # Below exception will be reraised, not convert to ServerError.
        raise AlreadyRegisterError

@pytest.fixture(scope="function")
def class_object():
    return Class()



@pytest.mark.parametrize("method_name", ["func", "afunc"])
def test_exception(class_object,method_name):
    method = getattr(class_object,method_name)
    with pytest.raises(ExceptionTest) as e:
        asyncio.run(method()) if method_name== "afunc" else method()

    assert e.value.classname == class_object.__class__.__name__
    assert e.value.method == method_name
    assert isinstance(e.value.pre_exp, PreException)

@pytest.mark.parametrize("method_name", ["func2", "afunc2","func3"])
def test_http_exception(class_object,method_name):
    method = getattr(class_object,method_name)
    with pytest.raises(HTTPException) as e:
        asyncio.run(method()) if method_name== "afunc2" else method()
    if method_name=="func3":
        assert e.value == AlreadyRegisterError
    else:
        assert e.value == ServerError

