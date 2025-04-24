from pydantic import BaseModel

from ray import serve

from fastapi import FastAPI, APIRouter



class Model(BaseModel):
	a: int
	b: str

r = APIRouter()
@r.post('/get')
async def post(m: Model) -> dict:
	return {'receive': f"{m.a} and {m.b}."}


app = FastAPI()
app.include_router(r,prefix='/shit')
@serve.deployment(name='testapp')
@serve.ingress(app)
class App:
	pass


serve.run(App.bind(), blocking=True)
