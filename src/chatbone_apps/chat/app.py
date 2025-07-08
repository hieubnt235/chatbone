from asyncio import CancelledError
from asyncio.tasks import Task
from contextlib import ExitStack
from copy import deepcopy
from functools import partial
from inspect import iscoroutinefunction
from pathlib import Path
from typing import Any, Unpack

import flet as ft
from pydantic import Field
from ray import serve

from chatbone.assistant import (UserData, EncryptedTokenError, UserNotFoundError, ReadStream, )
from utilities.func import uuid_to_base64, base64_to_uuid
from utilities.misc import UniversalLock
from utilities.schemas.auth import *
from .chat_io import (ChatInputField, ChatOutputField, ContainerArgs, RequestInputField, )
from .svc import *

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
    """
    IMPORTANT: DO NOT CHANGE ROUTE ( MANUALLY OR USING page.go) IN BaseView.__init__ or BaseView.__post_init__.
    Because View will be created on route change event handler, so change again in handler raise alot of errors.
    """

    def __init__(self, view_name, chat_app: "ChatApp", **kwargs):
        """Create object directly by this constructor is not supported. Using 'ViewCreator' factory instead."""
        assert isinstance(chat_app, ChatApp)
        assert isinstance(chat_app.page, ft.Page)

        self._view_config = self.default_view_config
        self._view_config.update(kwargs)

        super().__init__(**self._view_config)
        self.chat_app = chat_app
        self.view_name = view_name
        self.appbar = ft.AppBar(
            title=ft.Text(self.view_name.title()),
            center_title=True,
            toolbar_height=50,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            is_secondary=True,
        )
        self.spacing = 10

        self.__post_initialized__: bool = False

    @property
    def page_width(self):
        return self.chat_app.page.width

    @property
    def page_height(self):
        return self.chat_app.page.height

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

    async def __post_init__(self):
        if self.__post_initialized__:
            raise RuntimeError("Post init multiple times.")
        await self.post_init()
        self.__post_initialized__ = True

    async def post_init(self) -> None:
        """
        This method is intentional to be used to init dynamic object, allow asynchronous operation that __init__ cannot.
          will be call after init the view and add to page. See ChatApp.route_change for more detail.
          The same as ft.Control.build, but async.
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
                # todo: notify user server error
                logger.warning(
                    "Loggin successfully, but 'is_logged_in' flag still False."
                )
                self.go_to_view("home")

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


class _IOFields(ft.Container):
    """Helper class for AppView.
    Only show fields if it has both input and output field. Otherwises show textprompt
    """

    def __init__(self, **kwargs: Unpack[ContainerArgs]):

        self._input_fields: ChatInputField | None = None
        self._output_fields: ChatOutputField | None = None
        self._field_lock = UniversalLock()

        self._prompt_texts = [
            ft.Text("Welcome to Chatbone", size=30),
            ft.Text("Open a chat session to start chatting"),
        ]

        self._task: Task | None = None

        self.__input_field_init__: bool = False
        self._init_lock = UniversalLock()

        super().__init__(content=ft.Column(self._prompt_texts), **kwargs)

    @property
    def lock(self):
        """Lock for current io fields. Cannot change them when locked. (Cannot open new chat during chat, or during open another chat)"""
        return self._field_lock

    def update(self, *, lock: bool = False) -> None:
        with ExitStack() as stack:
            if lock:
                stack.enter_context(self.lock)
            if self._input_fields and self._output_fields:
                self.content = ft.Column([self._output_fields, self._input_fields])
            else:
                self.content = ft.Column(self._prompt_texts)
            super().update()

    @property
    def chat_output_field(self) -> ChatOutputField | None:
        """Current chat output field"""
        return self._output_fields

    @chat_output_field.setter
    def chat_output_field(self, v: ChatOutputField):
        if self._task:
            raise ValueError(
                "Current output field is running task. Cancel it first before add now output fields."
            )
        assert isinstance(v, ChatOutputField)
        self._output_fields = v

    @property
    def chat_input_field(self) -> ChatInputField | None:
        return self._input_fields

    @chat_input_field.setter
    def chat_input_field(self, v: ChatInputField):
        if self.__input_field_init__:
            raise ValueError("ChatInputField should be assign only one time.")
        with self._init_lock:
            assert isinstance(v, ChatInputField)
            self._input_fields = v
            self.__input_field_init__ = True

    async def cleanup(self):
        async with self.lock:
            for f in [self.chat_input_field, self.chat_output_field]:
                if m := getattr(f, "cleanup", None):
                    if iscoroutinefunction(m):
                        await m()
                    if callable(m):
                        m()
            self._input_fields = None
            self._output_fields = None

    @property
    def task(self):
        return self._task

    @task.setter
    def task(self, task: Task):
        if self._task:
            raise ValueError(
                "Current output field is running task. Cancel it first before add new output fields."
            )
        self._task = task
        logger.debug(
            f"Chat task added to io fields. Username={self.chat_output_field._username}. cs_id {self.chat_output_field._cs_uid}."
        )

    def cancel_task(self) -> Task | None:
        """Return task if there is a task, or None"""
        if self._task:
            assert self.lock.locked
            self._task.cancel()
            t = self._task
            self._task = None
            logger.debug(f"Cancelled io field task {t}")
            return t


class ChatContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    chat_session_id: UUID
    task: Task
    read_stream: ReadStream


@view("app")
class AppView(BaseView):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert self.chat_app.is_logged_in

        self.appbar.actions = [ft.Button(text="Logout", on_click=self._logout_click)]

        self._cs_lock = UniversalLock()
        """Lock for add/update new chat session"""

        self._cs_list = ft.ListView([])
        self._cs_cache: dict[UUID, ChatOutputField] = {}  # TODO: is it necessary ?

        # Controls
        # noinspection PyTypeChecker
        self._cs_browser = ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("Chat sessions"),
                        ft.IconButton(
                            icon=ft.Icons.ADD,
                            tooltip="Add new chat session.",
                            on_click=self._on_add_new_chat_session,
                        ),
                    ]
                ),
                self._cs_list,
            ],
            width=self.page_width * 0.15,
        )

        self._send_lock = UniversalLock()
        """Lock for enable of send button"""
        self._chatting_lock = UniversalLock()
        """Lock for enable open different chat sessions or change assistang during chatting."""

        self._suspend_button = ft.IconButton(
            ft.Icons.STOP_CIRCLE,
            on_click=self._kill_chat_task,
        )
        self._send_button = ft.IconButton(ft.Icons.SEND, on_click=self._on_chat)

        self._button_stack = ft.Stack([self._send_button, self._suspend_button])

        # io_fields should be init first to add to controls GUI. So that I init the unique input fields later.
        self._io_fields = _IOFields(
            width=self.page_width * 0.5,
            height=self.page_height - 2 * self.spacing - self.appbar.toolbar_height,
        )
        self.controls = [
            ft.Row(
                [
                    self._cs_browser,
                    self._io_fields,
                ]
            ),
        ]

    def build(self):
        self._enable_send()

    def _enable_send(self, v: bool = True, *, lock: bool = True):
        with ExitStack() as stack:
            if lock:
                stack.enter_context(self._send_lock)
            if v:
                self._send_button.visible = True
                self._send_button.disabled = False
                self._suspend_button.visible = False
                self._suspend_button.disabled = True
            else:
                self._send_button.visible = False
                self._send_button.disabled = True
                self._suspend_button.visible = True
                self._suspend_button.disabled = False

            if self._output_field and self._input_field:
                self._button_stack.disabled = False
                self._button_stack.visible = True
            else:
                self._button_stack.disabled = True
                self._button_stack.visible = False

    @asynccontextmanager
    async def chatting(self):
        """Prevent user press buttons during chat, the only button can press is suspend button."""
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(
                self._chatting_lock
            )  # For not multiple chat
            await stack.enter_async_context(
                self._cs_lock
            )  # For not create or update new cs
            await stack.enter_async_context(self._send_lock)  # for not send
            try:
                self._input_field.chatting_mode(True)
                self._cs_browser.disabled = True
                self._enable_send(False, lock=False)  # already update
                self.page.update()
                logger.debug("Chatting mode entered successfully")
                yield
            finally:
                self._input_field.chatting_mode(False)
                self._cs_browser.disabled = False
                self._enable_send(lock=False)
                self.page.update()
                logger.debug("Chatting mode exists")

    # noinspection PyTypeChecker
    @property
    def chat_session_list(self) -> list[ft.ElevatedButton]:
        return self._cs_list.controls

    @chat_session_list.setter
    def chat_session_list(self, v: list[ft.ElevatedButton]):
        self._cs_list.controls = v

    @property
    def _input_field(self) -> ChatInputField | None:
        if not self._io_fields.chat_input_field:
            logger.warning(
                "_input_field gotten should not be None, it should be init through post_init()."
            )
        return self._io_fields.chat_input_field

    @property
    def _output_field(self) -> ChatOutputField | None:
        return self._io_fields.chat_output_field

    async def _make_cs_button(self, uid: UUID) -> ft.ElevatedButton:
        return ft.ElevatedButton(
            uuid_to_base64(uid),
            on_click=partial(
                self._on_open_chat_session,
                session_name_base64=await asyncio.to_thread(uuid_to_base64, uid),
            ),
        )

    async def refresh_chat_session_ids(self, *, update: bool = True):
        """Get the latest chat session ids"""
        async with self._cs_lock:
            l = []
            for uid in await self.chat_app.chat_session_ids:
                l.append(await self._make_cs_button(uid))
            self.chat_session_list = l
            if update:
                self.update()

    async def post_init(self) -> None:
        await self.refresh_chat_session_ids(update=False)

        # input field
        self._io_fields.chat_input_field = ChatInputField(
            self.chat_app.assistant_apps,
            username=self.chat_app.userdata.username,
            user_id=self.chat_app.userdata.id,
            buttons=self._button_stack,
            border=ft.border.all(1, ft.Colors.BLUE),
            border_radius=10,
            padding=5,
            expand=True,
        )

        self.page.update()

    async def _on_add_new_chat_session(self, e=None):
        async with self._cs_lock:
            new_cs_uid = await self.chat_app.create_chat_session()
            self.chat_session_list.append(await self._make_cs_button(new_cs_uid))
            self.update()

    async def _on_open_chat_session(
        self, e: ft.ControlEvent | None = None, *, session_name_base64: str
    ):
        if self._output_field:
            if self._output_field._cs_base64 == session_name_base64:
                return

        async with self._io_fields.lock:
            uid = await asyncio.to_thread(base64_to_uuid, session_name_base64)
            self._io_fields.chat_output_field = ChatOutputField(
                username=self.chat_app.userdata.username,
                user_id=self.chat_app.userdata.id,
                cs_base64=session_name_base64,
                cs_uid=uid,
                expand=True,
                border=ft.border.all(1, ft.Colors.BLUE),
                border_radius=10,
                padding=5,
            )
            self._io_fields.update()  # It will replace prompt text with io input fields.
            self._enable_send()
            messages = await self.chat_app.get_chat_session_messages(uid)
            logger.debug(f"Message history:\n{messages}")
            await self._output_field.push_messages(messages)

    async def _on_chat(self, e):
        user_input = await self._input_field.get_input_data()
        try:
            if user_input.data:
                await self._io_fields.lock.aacqurie()
                await self._output_field.push_messages([user_input.data])
                await self._fire_chat_task(self._output_field._cs_uid, user_input)
            else:
                logger.debug(f"Receive input without data {repr(user_input)}")
        except Exception as e:
            await self._kill_chat_task()
            logger.error(
                f"Error occur during fire chat task, user input {repr(user_input)}, chat_id {self._output_field._cs_uid}"
            )
            logger.exception(e)

    async def _fire_chat_task(self, cs_id: UUID, user_input: UserInputData):
        assert (
            await self._io_fields.lock.alocked
        )  # Must be locked by event handler (_on_chat)

        async def chat_task():
            # wait for set task to io field, so it can be cancel in the future.
            t = 2
            for i in range(t):
                if self._io_fields.task != asyncio.current_task():
                    await asyncio.sleep(0.5)
            if self._io_fields.task != asyncio.current_task():
                m = f"'chat task' was not added to _io_fields after {t} seconds. This is not expected to happened."
                logger.critical(m)
                raise RuntimeError(m)
            logger.debug(f"Chat task was added to _io_fields successfully.")

            async with AsyncExitStack() as stack:
                await stack.enter_async_context(self.chatting())
                message_stream = await stack.enter_async_context(
                    self._output_field.stream_message(user_input.data.chat_context_id)
                )
                try:
                    async for data in self.chat_app.chat(cs_id, user_input):
                        if isinstance(data, AssistantOutputData):
                            await message_stream.send(data)
                        elif isinstance(data, RequestInputField):
                            pass  # TODO
                        else:
                            logger.error(
                                f"Invalid type: {type(data)}. Type must be 'AssistantOutputData' or 'RequestInputField'. "
                            )
                except CancelledError as e:
                    io_task = self._io_fields.task
                    logger.debug(
                        f"io_task={io_task}\n"
                        f"End CancelledError handler of chat task={asyncio.current_task()}."
                    )
                finally:
                    await self._kill_chat_task()

        self._io_fields.task = asyncio.create_task(chat_task())

    async def _kill_chat_task(self, e=None):
        logger.debug("Killing chat task")
        task = None
        try:
            task = self._io_fields.cancel_task()
            logger.debug(
                f"Task {task} was cancelled and remove from io_fields. Now {self._io_fields.task}"
            )
            if task:
                await task
                logger.debug(
                    f"Chat task was killed. Username={self._output_field._username}."
                    f" cs_id={self._output_field._cs_uid}."
                )
            else:
                logger.debug("No task to kill")
        finally:
            if await self._io_fields.lock.alocked:
                await self._io_fields.lock.arelease()
            logger.debug("io fields lock released")

    async def cleanup(self):
        await self._kill_chat_task()

    async def _logout_click(self, e):
        await self.chat_app.logout()
        self.go_to_view("home")


class ViewCreator:
    @classmethod
    async def create(cls, view_route: str, chat_app: "ChatApp") -> BaseView:
        view_name = route2viewname[view_route]
        view_cls = Views[view_name]
        view = view_cls(view_name, chat_app, **views_params_dict[view_name])
        assert isinstance(view, BaseView)
        return view


class ChatApp:

    class _LocalData(BaseModel):
        key: ClassVar[str] = "<ChatboneLocalData>"
        model_config = ConfigDict(validate_default=True, validate_assignment=True)
        user_id: UUID
        chat_session_ids: list[UUID] = Field(default_factory=list)
        encrypted_token: str

    def __init__(self, page: ft.Page):
        self.page = page
        self._set_up_page()
        self.id = self.page.session_id

        # Init later
        self.heartbeat_task: Task | None = None
        """This attribute in chatapp only for first time authenticate. It not be used for further operation, user chat_assistant_svc instead."""

        self._chat_assistant_svc: ChatAssistantSVC | None = (
            None  # assign after login successfully
        )

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

    @property
    async def chat_session_ids(self) -> list[UUID] | None:
        """Return list of user chat session id, maybe load from local data or reload from database.
        For now, it will load from local data.
        """
        if d := await self.local_data:
            return d.chat_session_ids

    async def create_chat_session(self) -> UUID:
        """Create chat session and update local data chat session."""
        session_id = await self.chat_assistant_svc.create_chat_session()
        local_data = await self.local_data
        assert isinstance(local_data, ChatApp._LocalData)
        local_data.chat_session_ids.append(session_id)
        await self.set_local_data(local_data)
        return session_id

    async def get_chat_session_messages(self, session_id: UUID) -> list[DisplayMessage]:
        session_data = await self.chat_assistant_svc.get_chat_session(session_id)
        messages: list[DisplayMessage] = []
        for m in await session_data.get_data_segment():
            messages.extend(m.messages)
        return messages

    async def delete_chat_session(self, chat_session_id: UUID):
        await self.chat_assistant_svc.delete_chat_session(chat_session_id)
        local_data = await self.local_data
        assert isinstance(local_data, ChatApp._LocalData)
        local_data.chat_session_ids.remove(chat_session_id)
        await self.set_local_data(local_data)

    # async def close_chat_session(self, chat_session_id: UUID):
    #     if (t := self.opening_chat_sessions.pop(chat_session_id), None) is not None:
    #         t.cancel()
    #         await t
    #         logger.info(
    #             f"{self.userdata.username}'s chat session '{chat_session_id}' was closed."
    #         )
    #     else:
    #         logger.warning(
    #             f"{self.userdata.username}'s chat session '{chat_session_id}' has closed before."
    #             f"UI should already drop the close option from user for the first close."
    #         )

    async def chat(
        self, chat_session_id: UUID, user_input: UserInputData
    ) -> AsyncIterator[AssistantOutputData | RequestInputField]:
        async with AsyncExitStack() as stack:
            chat_handle = await stack.enter_async_context(
                self.chat_assistant_svc.chat(chat_session_id, user_input)
            )
            try:
                reader = await stack.enter_async_context(chat_handle.stream_reader)
                sender = await stack.enter_async_context(chat_handle.stream_sender)
                logger.debug("Connect chat assistant successful, start stream.")

                async for data in reader:
                    logger.debug(f"Chat app got data {repr(data)}")
                    if isinstance(data, AssistantOutputData):
                        yield data  # This can be raise Exception
                    elif isinstance(data, RequestedInput):
                        yield await self._make_request_input_field(data, sender)
                logger.debug("End stream successfully")
            except Exception as e:
                logger.exception(e)
                chat_handle.task.cancel()
                if not isinstance(e, asyncio.CancelledError):
                    raise

    async def _make_request_input_field(
        self, data: RequestedInput, sender: MemoryObjectSendStream
    ) -> RequestInputField:
        raise NotImplementedError

    @property
    def local_data_key(self) -> str:
        return ChatApp._LocalData.key

    @property
    async def local_data(self) -> _LocalData | None:
        data = await self.page.client_storage.get_async(self.local_data_key)
        logger.debug(f"Raw local data received in session: {data}.")
        if data:
            return ChatApp._LocalData.model_validate(data)
        return None

    async def set_local_data(self, new_local_data: _LocalData):
        logger.debug(f"Set new local data: {new_local_data}")
        await self.page.client_storage.set_async(
            self.local_data_key, new_local_data.model_dump(mode="json")
        )

    async def remove_local_data(self):
        await self.page.client_storage.remove_async(self.local_data_key)

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
            ChatApp._LocalData(
                user_id=userdata.id,
                chat_session_ids=userinfo.chat_ids,
                encrypted_token=encrypted_token,
            )
        )

    # noinspection PyMethodMayBeStatic
    async def register(self, username, password):
        req = ClientRequestSchema[UserRegister](
            body=UserRegister(username=username, password=password)
        )
        token: TokenJWT = (await AUTH.register(req)).content

    async def login(self):
        local_data = await self.local_data
        if local_data:
            try:
                userdata = await UserData.verify_encrypted_token(
                    local_data.encrypted_token
                )
                self._chat_assistant_svc = await ChatAssistantSVC.create(userdata)
                assert self.userdata is not None

                self.fire_heartbeat_task()
                assert isinstance(self.heartbeat_task, Task)

            except EncryptedTokenError:
                logger.debug(
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
                logger.debug(
                    f"Heartbeat of userdata '{self.userdata.username}' started."
                )
                await self.userdata.heartbeat(CONFIG.userdata_expire_seconds, 0.05)
            except asyncio.CancelledError:
                logger.debug(
                    f"Heartbeat of userdata '{self.userdata.username}' stopped."
                )

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
        if routes[1] == "":
            routes.pop(1)

        async with self._route_change_lock:

            # Clear and recreate all views.
            while self.page.views:
                v = self.page.views.pop()
                assert isinstance(v, BaseView)
                await v.cleanup()

            r = ""
            views_stack = []
            for route in routes:
                r = Path(r + "/" + route).resolve().__str__()
                view = await ViewCreator.create(r, self)
                self.page.views.append(view)
                self.page.update()
                await view.__post_init__()
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
        await self.login()
        if self.is_logged_in:
            self.go_to_view("app")
        else:
            self.go_to_view("home")
        logger.info(
            f"Client ip '{self.page.client_ip}' reconnected on device '{self.page.client_user_agent}'. "
        )

    async def disconnect(self, e):
        await self.stop_heartbeat()
        for view in self.page.views:
            assert isinstance(view, BaseView)
            await view.cleanup()

        logger.info(
            f"Client ip '{self.page.client_ip}' disconnected on device '{self.page.client_user_agent}'."
        )

    def go(self, route: str):
        logger.debug(f"{self.id}: go to '{route}'")
        self.page.go(route)

    def go_to_view(self, view_name: str):
        self.go(views_params_dict[view_name]["route"])

    def _set_up_page(self):
        self.page.views.clear()
        self.page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
        self.page.vertical_alignment = ft.MainAxisAlignment.CENTER
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

    uvicorn.run(chat_fa_app, port=8000)
