import asyncio
from copy import deepcopy
from pathlib import Path
from typing import Literal, Any
from uuid import UUID

import flet as ft
from pydantic import Field, ConfigDict

from chatbone.broker import UserData, EncryptedTokenError, UserNotFoundError
from chatbone.chat.svc import *
from utilities.logger import logger
from utilities.settings.auth import *
from chatbone.assistant_interface import ImageObject, VideoObject, AudioObject, DocumentObject, TextStream, Selection
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
			self.go(route)
		return click

	async def post_init(self):
		pass

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

		#TODO 2

		self.assistant_choice= ft.Dropdown(label="Assistant")
		self.chat_session_choice=ft.Dropdown(label="Chat session")
		self.chat_input_field = ft.Row()
		self.chat_dialog= ft.ListView(expand=True,spacing=10)


		self.chat_controls:list[ft.Control] = [
			ft.Row([self.assistant_choice, self.chat_session_choice]),
			self.chat_dialog,
			self.chat_input_field
			]
		"""chat_controls will be shown only when chat_app.userdata exists. """

		if self.chat_app.userdata is not None:
			self.controls=self.chat_controls
			self.appbar.actions = [ft.Button(text="Logout", on_click=self.logout_click)]
		else:
			self.controls=self.auth_controls
			self.appbar.actions = []

	def _init_chat_controls(self):
		pass

	async def post_init(self):
		# assistant_info = await self._get_assistant_info()
		#TODO
		cs_ids = (await self.chat_app.local_data)["chat_session_ids"]
		self.chat_session_choice.options = [ft.DropdownOption()]

	async def chat_session_change(self):
		pass
	async def assistant_change(self):
		pass

	async def _get_assistant_info(self)->dict[str,str]:
		"""todo
		Get current assistants and their input format, this format will be used to make UI.
		Returns:
			dict with keys is assistant names, values are input formats.
		"""
		pass

	def make_chat_input_field(self):
		self.chat_input_field.controls.append(ft.TextField(),ft.FilePicker())



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
		await obj.post_init()
		return obj

a = ImageObject, VideoObject, AudioObject, DocumentObject, TextStream, Selection

Input2Control = {
	ImageObject: ft.FilePicker()

}

class ChatApp:
	def __init__(self, page:ft.Page):
		self.page = page
		self.route2viewname: dict[str, str] = {}
		self._set_up_page()
		self.id = self.page.session_id

		# Init later
		self.heartbeat_task: asyncio.Task|None=None
		"""This attribute in chatapp only for first time authenticate. It not be used for further operation, user chat_assistant_svc instead."""

		self.chat_assistant_svc: ChatAssistantSVC|None=None
		self.opening_chat_sessions: dict[UUID, asyncio.Task] = dict()

		logger.info(f"New client with ip '{self.page.client_ip}' connected on device'{self.page.client_user_agent}'. ")

	@property
	def userdata(self)->UserData|None:
		if self.chat_assistant_svc:
			return self.chat_assistant_svc.userdata
		return None

	@property
	def assistant_names(self)->list|None:
		if self.chat_assistant_svc:
			return list(self.chat_assistant_svc.assistant_apps.items())
		return None

	async def create_chat_session(self):
		session_id = await self.chat_assistant_svc.create_chat_session()
		local_data:dict[str,Any] = await self.local_data
		local_data['chat_session_ids'].append(str(session_id))
		await self.set_local_data(local_data)

	async def delete_chat_session(self, chat_session_id:UUID):
		await self.chat_assistant_svc.delete_chat_session(chat_session_id)
		local_data:dict[str,Any] = await self.local_data
		local_data['chat_session_ids'].pop(str(chat_session_id))
		await self.set_local_data(local_data)

	async def chat(self,chat_session_id:UUID, assistant_name:str):
		"""Connects to a chat session with the provided session ID and assistant name.
		1. Valid the assistant schema
		2. create handler or callback

		Args:
		    chat_session_id (UUID): The unique identifier of the chat session to connect to.
		    assistant_name (str): The name of the assistant to be associated with the chat session.
		Returns:
			chat history and input format.
		Notes:
			assistant_name can be not healthy at the time this method is called.
		"""
		assert self.chat_assistant_svc is not None


		# If reopen chat (change assistant)
		if self.opening_chat_sessions.get(chat_session_id) is not None:
			await self.close_chat_session(chat_session_id)
		self.opening_chat_sessions[chat_session_id] = asyncio.create_task(self._open_chat_session())

	async def _open_chat_session(self):
		pass

	async def close_chat_session(self,chat_session_id:UUID):
		if (t:= self.opening_chat_sessions.pop(chat_session_id),None) is not None:
			t.cancel()
			await t
			logger.info(f"{self.userdata.username}'s chat session '{chat_session_id}' was closed.")
		else:
			logger.warning(f"{self.userdata.username}'s chat session '{chat_session_id}' has closed before."
			               f"UI should already drop the close option from user for the first close.")

	@property
	async def local_data(self):
		return await self.page.client_storage.get_async("local_data")

	async def set_local_data(self, new_local_data):
		await self.page.client_storage.set_async("local_data", new_local_data)

	async def remove_local_data(self):
		await self.page.client_storage.remove_async("local_data")

	async def authenticate(self,username, password):
		req = ClientRequestSchema[UserAuthenticate](data=UserAuthenticate(username=username, password=password))
		token_jwt: TokenJWT = (await AUTH.authenticate(req)).content
		userinfo:UserInfoReturn = (await AUTH.get_user(ClientRequestSchema(headers={"Authorization": f"Bearer {token_jwt.access_token}"}))
								   ).content
		userdata = UserData(id = userinfo.id, username=userinfo.username, password=password,
							user_token=UserToken.model_validate(userinfo.tokens[-1],from_attributes=True))
		userdata = await userdata.save(expire_seconds=CONFIG.userdata_expire_seconds)
		encrypted_token = await userdata.get_encrypted_token()
		await self.set_local_data({"encrypted_token":encrypted_token, "chat_session_ids": userinfo.chat_ids})

	# noinspection PyMethodMayBeStatic
	async def register(self,username,password):
		req = ClientRequestSchema[UserRegister](body=UserRegister(username=username, password=password))
		token: TokenJWT = (await AUTH.register(req)).content

	async def login(self):
		local_data = await self.local_data
		logger.info(f"local data in session {local_data}.")
		if local_data:
			try:
				userdata = await UserData.verify_encrypted_token(local_data['encrypted_token'])
				self.fire_heartbeat_task()
				self.chat_assistant_svc = await ChatAssistantSVC.create(userdata)
				assert isinstance(self.heartbeat_task,asyncio.Task)
			except EncryptedTokenError:
				logger.info("encrypted token in local storage is no longer valid and get deleted.")
				await self.remove_local_data()

	async def logout(self):
		await self.remove_local_data()
		await self.stop_heartbeat()
		self.chat_assistant_svc=None

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

