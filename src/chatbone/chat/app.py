import anyio
import ray
from fastapi import FastAPI, WebSocketDisconnect
from ray import serve
from chatbone.chat.svc.chat_assistant_svc import *
from utilities.schemas.chat import JsonRPCSchema
from .settings import chat_settings

config = chat_settings.config
app = FastAPI()


class GetMessages(JsonRPCSchema):
	params: ChatSVCGetLatest


@serve.deployment()
@serve.ingress(app)
class ChatBoneApp:

	@app.post('/chat_session/create')
	async def create_chat_session(self,schema: ChatSVCBase) -> ChatSessionReturn:
		return await chat_assistant_svc.create_chat_session(schema)

	@app.delete('/chat_session/delete')
	async def delete_chat_session(self,schema: ChatSessionSVCDelete) -> dict:
		"""Make request to delete chat session and clear cache if success."""
		res = await chat_assistant_svc.delete_chat_session(schema)
		return res

	@app.websocket('/chat/{session_id}')
	async def connect_chat_session(self,websocket:WebSocket, ):
		try:
			await asyncio.wait_for(websocket.accept(),30) # Wait for accept.
		except:
			raise WebSocketDisconnect(code=status.WS_1002_PROTOCOL_ERROR,
			                          reason="Timeout when waiting for websocket acceptance.")
		user_histories= ray.put(await self._get_user_session_histories(session_id,token_id))

		# Loop until disconnect.
		try:
			while True:
				# Handle all exceptions and keep the connection alive until disconnect or timeout when sending.
				try:
					assistant_handle, assistant_input = await self._get_assistant_input(websocket)

					# This class will use app_*_stream. Assistants use *_stream.
					app_write_stream, read_stream = anyio.create_memory_object_stream(0)
					write_stream, app_read_stream = anyio.create_memory_object_stream(0)

					await self.chat_assistant_svc.chat(assistant_handle, assistant_input,
					                                   read_stream,write_stream,
					                                   user_histories)



				except Exception as e:
					logger.exception(e)
					if not isinstance(e,WebSocketException):
						e = WebSocketException(code=status.WS_1011_INTERNAL_ERROR)
					# Try to send exception as text to keep the connection active, but if it cannot, disconnect ws.
					try:
						await asyncio.wait_for(websocket.send_text(e),config.chat_assistant_timeout.websocket_send)
					except:
						raise e # Disconnect
		except WebSocketDisconnect:
			pass


	async def _get_assistant_input(self,ws:WebSocket)->tuple[DeploymentHandle,BaseModel]:
		"""
		- Client sends assistant name as text.
		- Server get app and input schema, return schema to the client.
		- Client provides input, which then will be validated with the schema.

		Raises:
			WebSocketException

		Returns:
			Tuple: (assistant_handle, object ref of assistant_input)
		"""
		assistant_name:str=""
		try:
			assistant_name = await ws.receive_text()
			assistant_handle = serve.get_app_handle(assistant_name)
			input_schema: BaseModel = await assistant_handle.get_input_schemas.remote()

			await asyncio.wait_for(ws.send_json(input_schema),
			                       timeout=config.chat_assistant_timeout.websocket_send)
			assistant_input = input_schema.model_validate_json(await ws.receive_json())

			return assistant_handle, assistant_input

		except RayServeException:
			raise WebSocketException(code=status.WS_1003_UNSUPPORTED_DATA,
			                         reason=f"Assistant \'{assistant_name}\' doesn't exist.")
		except ValidationError:
			raise WebSocketException(code=status.WS_1007_INVALID_FRAME_PAYLOAD_DATA,
			                         reason=f"Assistant input format does not true.")
		except asyncio.TimeoutError:
			raise WebSocketException(code=status.WS_1002_PROTOCOL_ERROR,
			                         reason="Cannot send the input request schema.")

	async def _get_user_session_histories(self, session_id:UUID, token_id:UUID
	                            )-> tuple[MessagesReturn,UserSummariesReturn,ChatSummariesReturn]:
		messages = await self.chat_assistant_svc._get_messages(
			ChatSVCGetLatest(token_id=token_id,chat_session_id=session_id,n=config.max_messages))
		user_summaries = await self.chat_assistant_svc._get_user_summaries(
			UserSummarySVCGetLatest(token_id=token_id,n=config.max_user_summaries))
		chat_summaries = await self.chat_assistant_svc._get_chat_summaries(
			ChatSVCGetLatest(token_id=token_id,chat_session_id=session_id,n=config.max_chat_summaries)
		)

		return dict(messages = [m.model_dump(include={'role','content'}) for m in messages.messages],
		            user_summaries = [s.summary for s in user_summaries.summaries],
		            chat_summaries = [s.summary for s in chat_summaries.summaries])

	async def _ws_stream_handle(self,ws:WebSocket, app_read_stream:MemoryObjectReceiveStream, app_write_stream: MemoryObjectSendStream ):
		pass

	async def _handle_json_rpc(self, request:dict):

	@app.get('/get_messages')
	async def get_messages(self,schema: ChatSVCGetLatest) -> MessagesReturn:
		return await self.chat_assistant_svc.get_messages(schema)



serve.run(ChatboneApp.bind(),blocking=True,name='chatbone_app')