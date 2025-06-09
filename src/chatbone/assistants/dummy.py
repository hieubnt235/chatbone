from pydantic import BaseModel

class A(BaseModel):
	d1:int
	d2:float

	@classmethod
	def __pydantic_init_subclass__(cls, **kwargs):
		print("init subclass")
		print(cls.model_fields)
		print(cls)
		super().__pydantic_init_subclass__(**kwargs)
		print(cls.model_fields)
		print(cls)


	def __init__(self,**kwargs):
		print("a init")
		super().__init__(**kwargs)
		print(self.__class__.model_fields)


class B(A):
	d3: str
	d4:str
	d1:str

	def __init__(self,**kwargs):
		super().__init__(**kwargs)
		print(self.__class__.model_fields)

# b = B(d3="W",d4="W",d1="#a",d2=5)