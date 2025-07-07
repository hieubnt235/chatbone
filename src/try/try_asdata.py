import threading
import time

from pydantic import PositiveInt, PositiveFloat, NonNegativeFloat

start = time.time()

from typing import Literal

from chatbone.src.assistant_interface import BaseForm

class Form1(BaseForm):
	a : int| list[int]| dict[int|float,str|None]
	b : Literal[5,"defe"]| PositiveInt | PositiveFloat
	# c : list[None|int] # raise as expect
	# noinspection PyTypeHints
	d: int|float| dict[list[int|float], int| NonNegativeFloat ] | list[list[tuple[Literal["abc",1, True] ]]]

print(time.time()-start) # 1.1s
def f():
	for f in Form1.fields():
		print(f[0],":",f[1].annotation)

start = time.time()
f()
print(t1:=(time.time()-start)) # 3.4e-05 s <1, run directly

start = time.time()
t = threading.Thread(target=f)
t.start()
t.join()
print(t2:=(time.time()-start)) # 3.4e-05 s
print(t2/t1)# 5.84

# typea = TypeAdapter(type=PositiveInt)
# print(typea.validate_python(1))