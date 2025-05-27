import asyncio
from copy import deepcopy
from pathlib import Path
from typing import Literal, Any

import flet as ft
from fastapi import HTTPException
from pydantic import Field, ConfigDict
from ray import serve

from chatbone.broker import UserData, UserToken, EncryptedTokenError, UserNotFoundError
from chatbone.chat.settings import CONFIG, AUTH
from utilities.logger import logger
from utilities.settings.clients.auth import *

views_params_dict = CONFIG.views.model_dump(mode='json')


def get_view_params(view_name: str) -> dict[str, str | int | None | float]:
	r = views_params_dict[view_name]
	params = deepcopy(r['params'])
	params['route'] = r['route']
	return params


def route2viewname(route: str) -> str:
	for k, v in views_params_dict.items():
		if v['route'] == route:
			return k
	raise ValueError(f"There is no View has route == '{route}'")


class ChatboneView(ft.View, BaseModel):
	view_name: Literal[''] = None
	model_config = ConfigDict(extra='allow')

	def __init__(self, *, view_name: str, chat_app: "ChatApp", ):
		assert chat_app.page is not None

		BaseModel.__init__(self, view_name=view_name)

		self._config = self.default_config
		self._config.update(get_view_params(self.view_name))
		ft.View.__init__(self, **self._config)

		self.chat_app = chat_app
		self.page = chat_app.page
		self.appbar = ft.AppBar(title=ft.Text(self.view_name.title()))

	def __hash__(self):
		return ft.View.__hash__(self)

	def go(self,route:str):
		self.chat_app.go(route)

	@property
	def default_config(self) -> dict[str, Any]:
		return dict(vertical_alignment="center", horizontal_alignment="center", bgcolor="blue50")

	@property
	def config(self) -> dict[str, Any]:
		return self._config

	def switch_click(self,view_names_or_route:str):
		if view_names_or_route.startswith('/'):
			route = view_names_or_route
		else:
			route = views_params_dict[view_names_or_route]['route']
		def click(e):
			self.page.go(route)
		return click

class LoginView(ChatboneView):
	view_name: Literal['login'] = 'login'

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

		self.title = ft.Text("Login", size=30, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER)
		self.username_field = ft.TextField(autofocus=True, width=300, label="Username")
		self.password_field = ft.TextField(width=300, label="Password")
		self.login_status = ft.Text(expand=True, text_align=ft.TextAlign.CENTER, )
		self.login_button= ft.Button(text="Login", on_click=self.login_click)
		self.controls = [
			ft.Container(ft.Column([self.title,self.username_field,self.password_field, self.login_status,self.login_button ]),
			             alignment=ft.alignment.center),
			ft.Button(text='Go to signup', on_click=self.switch_click("signup"))
		]

	async def login_click(self, e):
		"""
			1. Call auth service to log in, receive bearer access token as well as user info.
			2. Encrypt info a store in browser local storage.
			3. Call ChatApp.login, which will load encrypted token of user browser, load data, if everything works,
			it will go to chat controls, or main login controls, with will have option to move to this method again.
		"""
		username = self.username_field.value
		password = self.password_field.value
		try:
			await self.chat_app.authenticate(username,password)
			self.login_status.value = "Login successfully."
			self.page.update()

			await self.chat_app.login()
			self.go(views_params_dict['main']['route']) # this will go to chat view if login successfully.

		except HTTPException as e:
			self.login_status.value = f"Login fail.{e.detail}"
			self.page.update()
		except Exception as e:
			logger.error(e)
			self.login_status.value = f"Login fail. There is an error on server."
			self.page.update()

class SignupView(ChatboneView):
	view_name: Literal['signup'] = 'signup'

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

		self.title = ft.Text("Signup", size=30, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER)
		self.username_field = ft.TextField(autofocus=True, width=300, label="Username")
		self.password_field = ft.TextField(width=300, label="Password")
		self.password_again = ft.TextField(width=300, label="Password again")
		self.signup_status = ft.Text(expand=True, text_align=ft.TextAlign.CENTER, )
		self.signup_button = ft.Button(text="Signup", on_click=self.signup_click)
		self.controls = [
			ft.Container(ft.Column([self.title,self.username_field,self.password_field,  self.password_again, self.signup_status,self.signup_button]),
			             alignment=ft.alignment.center,),
			ft.Button(text='Go to login', on_click=self.switch_click("login"))
		]

	async def signup_click(self, e):
		if not self.password_field.value == self.password_again.value:
			self.signup_status.value = "Your passwords do not match to each other."
			self.page.update()
		else:
			username = self.username_field.value
			password = self.password_field.value
			try:
				await self.chat_app.register(username,password)
				self.signup_status.value = "Signup successfully. Go to login page to login."
			except HTTPException as e:
				logger.info(e)
				self.signup_status.value = e.detail
			except Exception as e:
				logger.error(e)
				self.signup_status.value = f"Signup fail. There is an error on server."
			self.page.update()

class UserInputFormat(BaseModel):
	description:str|None=None
	url:

class Image(UserInputFormat):


class AssistantInput(BaseModel):
	pass

class ChatUI(ft.Container):
	def __init__(self,*args,**kwargs):
		super().__init__(*args,**kwargs)
		self.chat_box = ft.ListView(spacing=10,expand=True)
		self.messages :list[ft.Text] = []
		self.input_field = ft.Row([
			ft.TextField()
		])

class MainView(ChatboneView):
	view_name: Literal['main'] = 'main'

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

		self.auth_controls:list[ft.Control] = [
			ft.Text("Chatbone", size=50, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
			ft.Row([
				ft.Button(text="Signup", on_click=self.switch_click('signup')),
				ft.Button(text='Login', on_click=self.login_click),
			],
				alignment="center")
		]

		#TODO

		self.chat_controls:list[ft.Control] = [
			ft.ListView(expand=True,spacing=10),
			ft.Button(text="Logout", on_click=self.logout_click)]
		"""chat_controls will be shown only when chat_app.userdata exists. """

		if self.chat_app.userdata is not None:
			self.controls=self.chat_controls
			self.page.update()
		else:
			self.controls=self.auth_controls

	async def logout_click(self,e):
		await self.chat_app.logout()
		await self.chat_app.route_change(views_params_dict['main']['route'])

	async def login_click(self,e):
		await self.chat_app.login()
		if self.chat_app.userdata is None:
			self.go(views_params_dict['login']['route'])
		else:
			self.go(views_params_dict['main']['route'])


VIEW_TYPE = LoginView | SignupView | MainView
class ViewCreator(BaseModel):
	view: VIEW_TYPE = Field(discriminator='view_name')

	@classmethod
	async def create(cls, view_name: str, chat_app:"ChatApp") -> ChatboneView:
		obj: VIEW_TYPE = cls(view={"view_name": view_name, "chat_app": chat_app}).view
		return obj


class ChatApp:
	def __init__(self, page:ft.Page):
		self.page = page
		self.route2viewname: dict[str, str] = {}
		self._set_up_page()
		self.id = self.page.session_id
		self.heartbeat_task: asyncio.Task|None=None
		self.userdata: UserData | None = None
		logger.info(f"New client with ip '{self.page.client_ip}' connected on device'{self.page.client_user_agent}'. ")


	async def authenticate(self,username, password):
		req = ClientRequestSchema[UserAuthenticate](data=UserAuthenticate(username=username, password=password))
		token_jwt: TokenJWT = (await AUTH.authenticate(req)).content
		userinfo:UserInfoReturn = (await AUTH.get_user(ClientRequestSchema(headers={"Authorization": f"Bearer {token_jwt.access_token}"}))
								   ).content
		userdata = UserData(id = userinfo.id, username=userinfo.username, password=password,
							user_token=UserToken.model_validate(userinfo.tokens[-1],from_attributes=True))
		await userdata.save(expire_seconds=CONFIG.userdata_expire_seconds)
		encrypted_token = await userdata.get_encrypted_token()
		await self.page.client_storage.set_async("encrypted_token", encrypted_token)

	async def register(self,username,password):
		req = ClientRequestSchema[UserRegister](body=UserRegister(username=username, password=password))
		token: TokenJWT = (await AUTH.register(req)).content

	async def login(self):
		self.userdata=None
		encrypted_token = await self.page.client_storage.get_async("encrypted_token")
		logger.info(f"encrypted_token in session {encrypted_token}.")
		if encrypted_token:
			try:
				self.userdata = await UserData.verify_encrypted_token(encrypted_token)
				self.fire_heartbeat_task()
				assert isinstance(self.heartbeat_task,asyncio.Task)
			except EncryptedTokenError:
				logger.info("encrypted token in local storage is no longer valid and get deleted.")
				await self.page.client_storage.remove_async("encrypted_token")

	async def logout(self):
		await self.page.client_storage.remove_async("encrypted_token")
		await self.stop_heartbeat()
		self.userdata=None # this must be after stop heart beat

	async def stop_heartbeat(self):
		if self.heartbeat_task is not None:
			self.heartbeat_task.cancel()
			await self.heartbeat_task
			self.heartbeat_task=None

	def fire_heartbeat_task(self):
		"""Fire the heartbeat_task and save a task in self.hearbeat_task."""
		async def _heartbeat():
			if self.userdata is None:
				raise UserNotFoundError("Userdata not found, login first.")
			try:
				logger.info(f"Heartbeat of userdata {self.userdata.username} started.")
				await self.userdata.heartbeat(CONFIG.userdata_expire_seconds, 0.05)
			except asyncio.CancelledError:
				logger.info(f"Heartbeat of userdata {self.userdata.username} stopped.")
		self.heartbeat_task= asyncio.create_task(_heartbeat())

	@classmethod
	async def main(cls, page: ft.Page):
		app = cls(page)
		await app.login()
		app.go(views_params_dict['main']['route'])

	async def route_change(self, e: ft.RouteChangeEvent|str):
		"""Notes: This method can be used to reset"""
		route_str = e if isinstance(e,str) else e.route
		routes = route_str.split('/')
		if routes[0]!="": # Ex: "ass" or "ass/hole". The correct one is "/ass/hole"
			raise ValueError(f"Route must start with '/'. Got '{routes}'.")
		if routes[1]=="": # "/"
			routes.pop(1)
		self.page.views.clear()
		r=""
		for route in routes:
			r = Path(r+"/"+route).resolve().__str__()
			if self.route2viewname.get(r) is None:
				self.route2viewname[r] = await asyncio.to_thread(route2viewname, r)
			self.page.views.append(await ViewCreator.create(self.route2viewname[r], self))
		self.page.update()
		logger.info(f"Page id '{self.id}' go to '{route_str}'. Views stack: {[(v.__class__.__name__,v.uid) for v in self.page.views]}")

	async def view_pop(self,e: ft.ViewPopEvent):
		self.page.views.pop()
		self.go(self.page.views[-1].route)
		logger.debug(f"After View pop called: {[v.__class__.__name__ for v in self.page.views]}")

	# async def error(self,e:ControlEvent):
	# 	logger.error(f"There is an exception is not handled. Event info: '{e.__dict__}'.")
	# async def close(self,e):
	# 	logger.info("on close event")

	async def connect(self,e):
		self.fire_heartbeat_task()
		logger.info(f"Client ip '{self.page.client_ip}' reconnected on device '{self.page.client_user_agent}'. ")

	async def disconnect(self,e):
		await self.stop_heartbeat()
		logger.info(f"Client ip '{self.page.client_ip}' disconnected on device '{self.page.client_user_agent}'.")

	def go(self,route:str):
		logger.debug(f"{self.id}: go to '{route}'")
		self.page.go(route)

	def _set_up_page(self):
		self.page.views.clear()
		self.page.horizontal_alignment = "center"
		self.page.vertical_alignment = "center"
		self.page.on_route_change = self.route_change
		self.page.on_view_pop = self.view_pop
		self.page.on_connect = self.connect
		self.page.on_disconnect = self.disconnect

		# self.page.on_error = self.error
		# self.page.on_close = self.close



chat_fa_app = ft.app(ChatApp.main, export_asgi_app=True)
# chat_fa_app = ft.app(ChatApp.main, view=ft.AppView.WEB_BROWSER)

@serve.deployment(num_replicas=3)
@serve.ingress(chat_fa_app)
class ChatboneApp:
	def __init__(self):
		import os
		import threading
		logger.debug(f"{self.__class__.__name__} started at Process:{os.getpid()}-Thread:{threading.get_native_id()}")



if __name__ == "__main__":
	# redis, auth and datastore deploy first.
	import uvicorn
	uvicorn.run("app:chat_fa_app", port=8888,reload=True)  # serve.run(ChatApp.bind(),blocking=True)
	# serve.run(ChatboneApp.bind())

	# def print_routes(app):
	# 	if isinstance(app,FastAPI):
	# 		for r in app.router.routes:
	# 			if isinstance(r,Mount):
	# 				print_routes(r.app)
	# 			print(r)
	# 	else:
	# 		print("**", type(app))
	#
	# print_routes(chat_app)

# class GetMessages(JsonRPCSchema):
# 	params: ChatSVCGetLatest

# TODO : ONLY CHAT AND ASSISTANT
# TODO: CHATAPP USE ONLY GET_USER_INFO FROM AUTH.

# @serve.deployment()
# @serve.ingress(app)
# class ChatBoneApp:
#
# 	@app.post('/chat_session/create')
# 	async def create_chat_session(self, schema: ChatSVCBase) -> ChatSessionReturn:
# 		return await chat_assistant_svc.create_chat_session(schema)
#
# 	@app.delete('/chat_session/delete')
# 	async def delete_chat_session(self, schema: ChatSessionSVCDelete) -> dict:
# 		"""Make request to delete chat session and clear cache if success."""
# 		res = await chat_assistant_svc.delete_chat_session(schema)
# 		return res
#
# 	@app.websocket('/chat/{session_id}')
# 	async def connect_chat_session(self, websocket: WebSocket, ):
# 		try:
# 			await asyncio.wait_for(websocket.accept(), 30)  # Wait for accept.
# 		except:
# 			raise WebSocketDisconnect(code=status.WS_1002_PROTOCOL_ERROR,
# 			                          reason="Timeout when waiting for websocket acceptance.")
# 		user_histories = ray.put(await self._get_user_session_histories(session_id, token_id))
#
# 		# Loop until disconnect.
# 		try:
# 			while True:
# 				# Handle all exceptions and keep the connection alive until disconnect or timeout when sending.
# 				try:
# 					assistant_handle, assistant_input = await self._get_assistant_input(websocket)
#
# 					# This class will use app_*_stream. Assistants use *_stream.
# 					app_write_stream, read_stream = anyio.create_memory_object_stream(0)
# 					write_stream, app_read_stream = anyio.create_memory_object_stream(0)
#
# 					await self.chat_assistant_svc.chat(assistant_handle, assistant_input, read_stream, write_stream,
# 					                                   user_histories)
#
#
#
# 				except Exception as e:
# 					logger.exception(e)
# 					if not isinstance(e, WebSocketException):
# 						e = WebSocketException(code=status.WS_1011_INTERNAL_ERROR)
# 					# Try to send exception as text to keep the connection active, but if it cannot, disconnect ws.
# 					try:
# 						await asyncio.wait_for(websocket.send_text(e), config.chat_assistant_timeout.websocket_send)
# 					except:
# 						raise e  # Disconnect
# 		except WebSocketDisconnect:
# 			pass
#
# 	async def _get_assistant_input(self, ws: WebSocket) -> tuple[DeploymentHandle, BaseModel]:
# 		"""
# 		- Client sends assistant name as text.
# 		- Server get app and input schema, return schema to the client.
# 		- Client provides input, which then will be validated with the schema.
#
# 		Raises:
# 			WebSocketException
#
# 		Returns:
# 			Tuple: (assistant_handle, object ref of assistant_input)
# 		"""
# 		assistant_name: str = ""
# 		try:
# 			assistant_name = await ws.receive_text()
# 			assistant_handle = serve.get_app_handle(assistant_name)
# 			input_schema: BaseModel = await assistant_handle.get_input_schemas.remote()
#
# 			await asyncio.wait_for(ws.send_json(input_schema), timeout=config.chat_assistant_timeout.websocket_send)
# 			assistant_input = input_schema.model_validate_json(await ws.receive_json())
#
# 			return assistant_handle, assistant_input
#
# 		except RayServeException:
# 			raise WebSocketException(code=status.WS_1003_UNSUPPORTED_DATA,
# 			                         reason=f"Assistant \'{assistant_name}\' doesn't exist.")
# 		except ValidationError:
# 			raise WebSocketException(code=status.WS_1007_INVALID_FRAME_PAYLOAD_DATA,
# 			                         reason=f"Assistant input format does not true.")
# 		except asyncio.TimeoutError:
# 			raise WebSocketException(code=status.WS_1002_PROTOCOL_ERROR, reason="Cannot send the input request schema.")
#
# 	async def _get_user_session_histories(self, session_id: UUID, token_id: UUID) -> tuple[
# 		MessagesReturn, UserSummariesReturn, ChatSummariesReturn]:
# 		messages = await self.chat_assistant_svc._get_messages(
# 			ChatSVCGetLatest(token_id=token_id, chat_session_id=session_id, n=config.max_messages))
# 		user_summaries = await self.chat_assistant_svc._get_user_summaries(
# 			UserSummarySVCGetLatest(token_id=token_id, n=config.max_user_summaries))
# 		chat_summaries = await self.chat_assistant_svc._get_chat_summaries(
# 			ChatSVCGetLatest(token_id=token_id, chat_session_id=session_id, n=config.max_chat_summaries))
#
# 		return dict(messages=[m.model_dump(include={'role', 'content'}) for m in messages.messages],
# 		            user_summaries=[s.summary for s in user_summaries.summaries],
# 		            chat_summaries=[s.summary for s in chat_summaries.summaries])
#
# 	async def _ws_stream_handle(self, ws: WebSocket, app_read_stream: MemoryObjectReceiveStream,
# 	                            app_write_stream: MemoryObjectSendStream):
# 		pass
#
# 	async def _handle_json_rpc(self, request: dict):
#
# 	@app.get('/get_messages')
# 	async def get_messages(self, schema: ChatSVCGetLatest) -> MessagesReturn:
# 		return await self.chat_assistant_svc.get_messages(schema)
#
#
# serve.run(ChatboneApp.bind(), blocking=True, name='chatbone_app')
