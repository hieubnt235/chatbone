from cloudpickle import cloudpickle
from pydantic import BaseModel

with open("../instance", mode="rb") as f:
	with open("../class", mode="rb") as f1:
		obj = cloudpickle.load(f)
		print(type(obj))
		for data in obj:
			print(data)
		print(obj.__class__.model_fields)

		cls: BaseModel = cloudpickle.load(f1)
		print(cls.__name__, cls.model_fields)
		print(cls.__module__)
