from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import UUID

import flet as ft
from ray import serve

from chatbone.broker import UserData, EncryptedTokenError, UserNotFoundError
from chatbone.chat.svc import *
from utilities.logger import logger
from utilities.misc import UniversalLock
from utilities.settings.auth import *

view_config_dict = CONFIG.views.model_dump(mode="json")
views_params_dict = {}
"""keys are view_names, values are params including route."""

route2viewname = {}


# Make route become part of params dict
def _init_views():
    global views_params_dict, view_config_dict, route2viewname
    for view_name, vp in view_config_dict.items():
        params = deepcopy(vp["params"])
        params["route"] = vp["route"]
        views_params_dict[view_name] = params
        route2viewname[params["route"]] = view_name


_init_views()


class BaseView(ft.View):
    def __init__(self, view_name, chat_app: "ChatApp", **kwargs):
        """Create object directly by this constructor is not supported. Using 'ViewCreator' factory instead."""
        assert isinstance(chat_app, ChatApp)

        self._view_config = self.default_view_config
        self._view_config.update(kwargs)

        super().__init__(**self._view_config)
        self.chat_app = chat_app
        self.view_name = view_name
        self.appbar = ft.AppBar(title=ft.Text(self.view_name.title()))

    @property
    def default_view_config(self) -> dict[str, Any]:
        return {
            "vertical_alignment": ft.MainAxisAlignment.CENTER,
            "horizontal_alignment": ft.CrossAxisAlignment.CENTER,
        }

    @property
    def view_config(self) -> dict[str, Any]:
        return self._view_config

    def go_to_view(self, view_name: str):
        self.chat_app.go_to_view(view_name)

    async def post_init(self) -> None:
        """
        This method is intentional to be used to init dynamic object, allow asynchronous operation that __init__ cannot.
          will be call after init the view. See ViewCreator for more detail.
          
        """
        pass
    
    async def cleanup(self):
        pass

AnyView = type[BaseView]
Views: dict[str, type[BaseView]] = dict()


def view(view_name: str) -> Callable[[type[BaseView]], type[BaseView]]:
    def _register(cls: type[BaseView]):
        assert issubclass(cls, BaseView)
        global AnyView, Views
        if AnyView == BaseView:
            AnyView = cls
        else:
            AnyView = AnyView | cls
        Views[view_name] = cls
        return cls

    return _register


@view("login")
class LoginView(BaseView):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.title = ft.Text(
            "Login", size=30, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER
        )
        self.username_field = ft.TextField(autofocus=True, label="Username")
        self.password_field = ft.TextField(label="Password", password=True)
        self.login_status = ft.Text(
            expand=True,
            text_align=ft.TextAlign.CENTER,
        )
        self.login_button = ft.Button(text="Login", on_click=self._login_click)
        self._go_to_signup_button = ft.Button(
            "Go to signup",
            icon=ft.Icons.ARROW_RIGHT,
            on_click=lambda e: self.go_to_view("signup"),
        )
        self.controls = [
            ft.Container(
                ft.Column(
                    [
                        self.title,
                        self.username_field,
                        self.password_field,
                        self.login_status,
                        self.login_button,
                        self._go_to_signup_button,
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                alignment=ft.alignment.center,
                width=300,
            )
        ]

    async def _login_click(self, e):
        """
        1. Call auth service to log in, receive bearer access token as well as user info.
        2. Encrypt info a store in browser local storage.
        3. Call ChatApp.login, which will load encrypted token of user browser, load data, if everything works,
        it will go to chat controls, or main login controls, with will have option to move to this method again.
        """
        username = self.username_field.value
        password = self.password_field.value
        try:
            await self.chat_app.authenticate(username, password)
            self.login_status.value = "Login successfully."
            self.update()

            await self.chat_app.login()
            if self.chat_app.is_logged_in:
                self.go_to_view("app")
            else:
                self.go_to_view("home")  # this will go to app view if login successfully, See Mainview for detail

        except HTTPException as e:
            self.login_status.value = f"Login fail.{e.detail}"
            logger.exception(e)
            self.update()
        except Exception as e:
            logger.exception(e)
            self.login_status.value = f"Login fail. There is an error on server."
            self.update()


@view("signup")
class SignupView(BaseView):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.title = ft.Text(
            "Signup",
            size=30,
            weight=ft.FontWeight.BOLD,
            text_align=ft.TextAlign.CENTER,
        )
        self.username_field = ft.TextField(autofocus=True, label="Username")
        self.password_field = ft.TextField(label="Password", password=True)
        self.password_again = ft.TextField(label="Password again", password=True)
        self.signup_status = ft.Text(
            expand=True,
            text_align=ft.TextAlign.CENTER,
        )
        self.signup_button = ft.Button(text="Signup", on_click=self._signup_click)
        self._go_to_login_button = ft.Button(
            text="Go to login",
            icon=ft.Icons.ARROW_RIGHT,
            on_click=lambda e: self.go_to_view("login"),
        )
        self.controls = [
            ft.Container(
                ft.Column(
                    [
                        self.title,
                        self.username_field,
                        self.password_field,
                        self.password_again,
                        self.signup_status,
                        self.signup_button,
                        self._go_to_login_button,
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                alignment=ft.alignment.center,
                width=300,
            ),
        ]

    async def _signup_click(self, e):
        if not self.password_field.value == self.password_again.value:
            self.signup_status.value = "Your passwords do not match to each other."
            self.update()
        else:
            username = self.username_field.value
            password = self.password_field.value
            try:
                await self.chat_app.register(username, password)
                self.signup_status.value = (
                    "Signup successfully. Go to login page to login."
                )
            except HTTPException as e:
                logger.info(e)
                self.signup_status.value = e.detail
            except Exception as e:
                logger.error(e)
                self.signup_status.value = f"Signup fail. There is an error on server."
            self.update()


@view("home")
class HomeView(BaseView):
    """Call route change to this view to reset the login."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.controls = [
            ft.Container(
                ft.Column(
                    [
                        ft.Text(
                            "Chatbone",
                            size=50,
                            weight=ft.FontWeight.BOLD,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Button(
                            "Signup", on_click=lambda e: self.go_to_view("signup")
                        ),
                        ft.Button("Login", on_click=self._login_click),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                )
            )
        ]

    async def _login_click(self, e):
        await self.chat_app.login()
        if self.chat_app.is_logged_in:
            self.go_to_view("app")
        else:
            self.go_to_view("login")


@view("app")
class AppView(BaseView):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert self.chat_app.is_logged_in

        self.appbar.actions = [ft.Button(text="Logout", on_click=self._logout_click)]
        self.controls = [ft.Text("CHATBONE APP VIEW", size=100)]

    async def _logout_click(self, e):
        await self.chat_app.logout()
        self.go_to_view("home")

    async def chat_session_change(self):
        pass

    async def assistant_change(self):
        pass


class ViewCreator:
    @classmethod
    async def create(cls, view_route: str, chat_app: "ChatApp") -> BaseView:
        view_name = route2viewname[view_route]
        view_cls = Views[view_name]
        view = view_cls(view_name, chat_app, **views_params_dict[view_name])
        assert isinstance(view, BaseView)
        return view


class ChatApp:

    def __init__(self, page: ft.Page):
        self.page = page
        self._set_up_page()
        self.id = self.page.session_id

        # Init later
        self.heartbeat_task: asyncio.Task | None = None
        """This attribute in chatapp only for first time authenticate. It not be used for further operation, user chat_assistant_svc instead."""

        self._chat_assistant_svc: ChatAssistantSVC | None = (
            None  # assign after login successfully
        )

        self.opening_chat_sessions: dict[UUID, asyncio.Task] = dict()

        logger.info(
            f"New client with ip '{self.page.client_ip}' connected on device'{self.page.client_user_agent}'. "
        )

        self._route_change_lock = UniversalLock()

    @property
    def chat_assistant_svc(self):
        return self._chat_assistant_svc

    @property
    def userdata(self) -> UserData | None:
        if self.chat_assistant_svc is not None:
            return self.chat_assistant_svc.userdata
        return None

    @property
    def is_logged_in(self) -> bool:
        return True if self.userdata else False

    @property
    def assistant_apps(self) -> dict[str, AssistantApp] | None:
        if self.chat_assistant_svc is not None:
            return self.chat_assistant_svc.assistant_apps
        return None

    async def create_chat_session(self):
        """Create chat session and update local data chat session."""
        session_id = await self.chat_assistant_svc.create_chat_session()
        local_data: dict[str, Any] = await self.local_data
        local_data["chat_session_ids"].append(str(session_id))
        await self.set_local_data(local_data)

    async def delete_chat_session(self, chat_session_id: UUID):
        await self.chat_assistant_svc.delete_chat_session(chat_session_id)
        local_data: dict[str, Any] = await self.local_data
        local_data["chat_session_ids"].pop(str(chat_session_id))
        await self.set_local_data(local_data)

    async def chat(self, chat_session_id: UUID, assistant_name: str):
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
        self.opening_chat_sessions[chat_session_id] = asyncio.create_task(
            self._open_chat_session()
        )

    async def _open_chat_session(self):
        pass

    async def close_chat_session(self, chat_session_id: UUID):
        if (t := self.opening_chat_sessions.pop(chat_session_id), None) is not None:
            t.cancel()
            await t
            logger.info(
                f"{self.userdata.username}'s chat session '{chat_session_id}' was closed."
            )
        else:
            logger.warning(
                f"{self.userdata.username}'s chat session '{chat_session_id}' has closed before."
                f"UI should already drop the close option from user for the first close."
            )

    @property
    async def local_data(self):
        return await self.page.client_storage.get_async("local_data")

    async def set_local_data(self, new_local_data):
        logger.info(f"Set new local data: {new_local_data}")
        await self.page.client_storage.set_async("local_data", new_local_data)

    async def remove_local_data(self):
        await self.page.client_storage.remove_async("local_data")

    async def authenticate(self, username, password):
        req = ClientRequestSchema[UserAuthenticate](
            data=UserAuthenticate(username=username, password=password)
        )
        token_jwt: TokenJWT = (await AUTH.authenticate(req)).content
        userinfo: UserInfoReturn = (
            await AUTH.get_user(
                ClientRequestSchema(
                    headers={"Authorization": f"Bearer {token_jwt.access_token}"}
                )
            )
        ).content
        userdata = UserData(
            id=userinfo.id,
            username=userinfo.username,
            password=password,
            user_token=UserToken.model_validate(
                userinfo.tokens[-1], from_attributes=True
            ),
        )
        userdata = await userdata.save(expire_seconds=CONFIG.userdata_expire_seconds)
        encrypted_token = await userdata.get_encrypted_token()
        await self.set_local_data(
            {"encrypted_token": encrypted_token, "chat_session_ids": userinfo.chat_ids}
        )

    # noinspection PyMethodMayBeStatic
    async def register(self, username, password):
        req = ClientRequestSchema[UserRegister](
            body=UserRegister(username=username, password=password)
        )
        token: TokenJWT = (await AUTH.register(req)).content

    async def login(self):
        local_data = await self.local_data
        logger.info(f"local data in session: {local_data}.")
        if local_data:
            try:
                userdata = await UserData.verify_encrypted_token(
                    local_data["encrypted_token"]
                )
                self._chat_assistant_svc = await ChatAssistantSVC.create(userdata)
                assert self.userdata is not None

                self.fire_heartbeat_task()
                assert isinstance(self.heartbeat_task, asyncio.Task)

            except EncryptedTokenError:
                logger.info(
                    "encrypted token in local storage is no longer valid and get deleted."
                )
                await self.remove_local_data()

    async def logout(self):
        await self.remove_local_data()
        await self.stop_heartbeat()
        self._chat_assistant_svc = None

    async def stop_heartbeat(self):
        if self.heartbeat_task is not None:
            self.heartbeat_task.cancel()
            await self.heartbeat_task
            self.heartbeat_task = None

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

        self.heartbeat_task = asyncio.create_task(_heartbeat())

    @classmethod
    async def main(cls, page: ft.Page):
        app = cls(page)
        await app.login()
        if app.is_logged_in:
            app.go_to_view("app")
        else:
            app.go_to_view("home")

    async def route_change(self, e: ft.RouteChangeEvent | str):
        """Notes: This method can be used to reset by calling it to home route"""
        route_str = e if isinstance(e, str) else e.route
        assert route_str.startswith("/")
        routes = route_str.split("/")
        if routes[1]=="":
            routes.pop(1)
        
        async with self._route_change_lock:

            # Clear and recreate all views.
            while self.page.views:
                v= self.page.views.pop()
                assert isinstance(v,BaseView)
                await v.cleanup()
            
            r = ""
            views_stack = []
            for route in routes:
                r = Path(r + "/" + route).resolve().__str__()
                view = await ViewCreator.create(r, self)
                self.page.views.append(view)
                self.page.update()
                await view.post_init()
                views_stack.append(view.__class__.__name__)
            logger.info(
                f"Page id '{self.id}' go to '{route_str}'. Current views stack:{views_stack}"
            )

    async def view_pop(self, e: ft.ViewPopEvent):
        self.page.views.pop()
        if self.page.views:
            self.go(self.page.views[-1].route)
        else:
            self.go_to_view("home")
        logger.debug(
            f"After View pop called: {[v.__class__.__name__ for v in self.page.views]}"
        )

    # async def error(self,e:ControlEvent):
    # 	logger.error(f"There is an exception is not handled. Event info: '{e.__dict__}'.")
    # async def close(self,e):
    # 	logger.info("on close event")

    async def connect(self, e):
        self.fire_heartbeat_task()
        logger.info(
            f"Client ip '{self.page.client_ip}' reconnected on device '{self.page.client_user_agent}'. "
        )

    async def disconnect(self, e):
        await self.stop_heartbeat()
        logger.info(
            f"Client ip '{self.page.client_ip}' disconnected on device '{self.page.client_user_agent}'."
        )

    def go(self, route: str):
        logger.info(f"{self.id}: go to '{route}'")
        self.page.go(route)

    def go_to_view(self, view_name: str):
        self.go(views_params_dict[view_name]["route"])

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


@serve.deployment()
@serve.ingress(chat_fa_app)
class Chatbone:

    def __init__(self):
        import os
        import threading
        from utilities.logger import logger

        logger.info(
            f"{self.__class__.__name__} started at Process:{os.getpid()}-Thread:{threading.get_native_id()}"
        )


app = Chatbone.bind()

if __name__ == "__main__":
    # serve.run(app, blocking=True)
    import uvicorn

    uvicorn.run(chat_fa_app, port=23501)
