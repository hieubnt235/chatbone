from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from ray import serve
from ray.serve.handle import DeploymentHandle

from chat.chat_assistants_svc import *

app = FastAPI()
svc = serve.deployment()(ChatAssistantSVC).bind()


@serve.deployment()
@serve.ingress(app)
class ChatboneApp:
	def __init__(self,chat_assistant_svc: DeploymentHandle ):
		self.chat_assistant_svc = chat_assistant_svc.options(stream=True)

	@app.post('/chat_session/create')
	async def create_chat_session(self,schema: ChatSVCBase) -> ChatSessionReturn:
		return await self.chat_assistant_svc.create_chat_session(schema)

	@app.delete('/chat_session/delete')
	async def delete_chat_session(self,schema: ChatSessionSVCDelete) -> dict:
		return await self.chat_assistant_svc.delete_chat_session(schema)

	@app.get('/get_messages')
	async def get_messages(self,schema: ChatSVCGetLatest) -> MessagesReturn:
		return await self.chat_assistant_svc.get_messages(schema)

	@app.post('/chat')
	async def chat(self,chat_request: AssistantRequest):
		
		return StreamingResponse( self.chat_assistant_svc.chat_assistant.chat.remote(chat_request) )

chatbone_app = ChatboneApp.bind(svc)
serve.run(chatbone_app,blocking=True,name='chatbone_app')