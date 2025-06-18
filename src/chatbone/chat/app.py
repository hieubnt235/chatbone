import asyncio
from abc import ABC, abstractmethod
from copy import deepcopy
from enum import Enum
from math import floor
from pathlib import Path
from types import UnionType
from typing import Literal, Any, get_origin, get_args, List, Type, Sequence, Dict
from uuid import UUID

import flet as ft
from flet.core.dropdown import DropdownOption
from pydantic import Field
from pydantic.fields import FieldInfo
from ray import serve
from uuid_extensions import uuid7

from chatbone.assistant_interface import (ImageObject, VideoObject, AudioObject, DocumentObject, TextStream, Selection,
                                          MediaObject, AnyMediaObject, )
from chatbone.broker import UserData, EncryptedTokenError, UserNotFoundError
from chatbone.chat.controls import BaseUI
from chatbone.chat.svc import *
from utilities.logger import logger
from utilities.misc import UniversalLock
from utilities.settings.auth import *

views_params_dict = CONFIG.views.model_dump(mode="json")


def get_view_params(view_name: str) -> dict[str, str | int | None | float]:
    r = views_params_dict[view_name]
    params = deepcopy(r["params"])
    params["route"] = r["route"]
    return params


def route2viewname(route: str) -> str:
    for k, v in views_params_dict.items():
        if v["route"] == route:
            return k
    raise ValueError(f"There is no View has route == '{route}'")


class ChatboneView(ft.View, BaseModel):
    view_name: Literal[""] = None
    model_config = ConfigDict(extra="allow")

    def __init__(
        self,
        *,
        view_name: str,
        chat_app: "ChatApp",
    ):
        """Create object directly by this constructor is not supported. Using 'ViewCreator' factory instead."""
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

    def go(self, route: str):
        self.chat_app.go(route)

    @property
    def default_config(self) -> dict[str, Any]:
        return dict(
            vertical_alignment="center", horizontal_alignment="center", bgcolor="blue50"
        )

    @property
    def config(self) -> dict[str, Any]:
        return self._config

    def switch_click(self, view_names_or_route: str):
        if view_names_or_route.startswith("/"):
            route = view_names_or_route
        else:
            route = views_params_dict[view_names_or_route]["route"]

        def click(e):
            self.go(route)

        return click

    async def post_init(self) -> None:
        """
        This method is intentional to be used to init dynamic object, allow asynchronous operation that __init__ cannot.
          will be call after init the view. See ViewCreator for more detail.
        """
        pass


class LoginView(ChatboneView):
    view_name: Literal["login"] = "login"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.title = ft.Text(
            "Login", size=30, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER
        )
        self.username_field = ft.TextField(autofocus=True, width=300, label="Username")
        self.password_field = ft.TextField(width=300, label="Password")
        self.login_status = ft.Text(
            expand=True,
            text_align=ft.TextAlign.CENTER,
        )
        self.login_button = ft.Button(text="Login", on_click=self.login_click)
        self.controls = [
            ft.Container(
                ft.Column(
                    [
                        self.title,
                        self.username_field,
                        self.password_field,
                        self.login_status,
                        self.login_button,
                    ]
                ),
                alignment=ft.alignment.center,
            ),
            ft.Button(text="Go to signup", on_click=self.switch_click("signup")),
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
            await self.chat_app.authenticate(username, password)
            self.login_status.value = "Login successfully."
            self.page.update()

            await self.chat_app.login()
            self.go(
                views_params_dict["main"]["route"]
            )  # this will go to chat view if login successfully.

        except HTTPException as e:
            self.login_status.value = f"Login fail.{e.detail}"
            self.page.update()
        except Exception as e:
            logger.error(e)
            self.login_status.value = f"Login fail. There is an error on server."
            self.page.update()


class SignupView(ChatboneView):
    view_name: Literal["signup"] = "signup"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.title = ft.Text(
            "Signup", size=30, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER
        )
        self.username_field = ft.TextField(autofocus=True, width=300, label="Username")
        self.password_field = ft.TextField(width=300, label="Password")
        self.password_again = ft.TextField(width=300, label="Password again")
        self.signup_status = ft.Text(
            expand=True,
            text_align=ft.TextAlign.CENTER,
        )
        self.signup_button = ft.Button(text="Signup", on_click=self.signup_click)
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
                    ]
                ),
                alignment=ft.alignment.center,
            ),
            ft.Button(text="Go to login", on_click=self.switch_click("login")),
        ]

    async def signup_click(self, e):
        if not self.password_field.value == self.password_again.value:
            self.signup_status.value = "Your passwords do not match to each other."
            self.page.update()
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
            self.page.update()


"""
UI Note
media object -> file picker
textstream -> concat str to messages
selection -> radio
statis: messages notification
message: textfield
}
"""

class FilePickerCancelUploadFile(BaseModel):
    filename:str
    object_name: str

class FilePicker(ft.FilePicker):

    async def _clean_storage(self, object_name:str):
        # TODO
        pass

    def _cancel(self, file: FilePickerCancelUploadFile):
        """Send command to client. No need to async"""

    async def cancel_upload(self,files:List[FilePickerCancelUploadFile]):
        """Cancel uploading as well as delete storage."""
        for file in files:
            self._cancel(file)
            await self._clean_storage(file.object_name)




class MainView(ChatboneView):
    view_name: Literal["main"] = "main"

    class AuthUI(BaseUI):
        title: ft.Text
        signup_button: ft.Button
        login_button: ft.Button

        def _get_content(self) -> ft.Control:
            return ft.Column(
                [
                    self.title,
                    ft.Row(self.signup_button, self.login_button, alignment="center"),
                ]
            )

    class ChatUI(BaseUI):
        chat_session_choices: ft.ListView
        assistant_choices: ft.RadioGroup
        dialog: ft.ListView
        input_fields: ft.ListView

        create_new_chat_session_button: ft.Button
        start_stop_button: ft.Button

        def _get_content(self) -> ft.Control:
            return ft.Row(
                [
                    self.session_choices,
                    self.dialog,
                    ft.Column(
                        [
                            self.assistant_choices,
                            self.input_fields,
                            self.start_stop_button,
                        ]
                    ),
                ]
            )

    class BaseInputField(ABC):

        @abstractmethod
        def get_value(self)->dict[str,Any]:
            """Value for model_validate"""
            pass

        @abstractmethod
        def get_control(self)->ft.Control:
            pass

    class SelectionInputField(BaseInputField):
        """This class is for select exclusively type of input to be used."""

        def __init__(self, controls: dict[str,ft.Control], **kwargs):
            for control in controls:
                control.visible = False

            self._controls = controls
            self._keys: list[str] = list(self._controls.items())
            self._current_visible_key:str = self._keys[0]

            self._dropdown = ft.Dropdown(label="Input type",
                                         options=[DropdownOption(k) for k in self._keys] ,
                                         on_change=self._change_visible)

            self._stack = ft.Stack(self._controls, kwargs.pop("stack_kwargs",{}))
            super().__init__(kwargs.pop("column_kwargs",{}))

            self.controls:list[ft.Control] = [self._dropdown,self._stack]

        def get_value(self) -> dict[str,Any]:
            pass

        def get_control(self) -> ft.Control:
            return ft.Column(self.controls)

        @property
        def keys(self):
            return self._keys

        def _change_visible(self, e: ft.ControlEvent):
            key = e.control.value
            self._controls[self._current_visible_key].visible = False
            self._controls[key].visible = True
            self._current_visible_key = key

    class SelectedFiles(BaseInputField):
        def __init__(self):
            self.upload_files: list[ft.FilePickerUploadFile] = []
            """List of selected files ready to upload."""
            self.preview_fields: list[ft.Row] = []
            """List of selected file rows. Each row controls has Tuple[ft.Button, ft.ProcessRing|ft.Button, ft.Text]."""
            self.file_names: list[str] = []
            """User for hold index to easy access."""

            self._lock = UniversalLock()

        def add_new_file(self, file: ft.FilePickerUploadFile):
            with self._lock:
                preview_field = ft.Row(
                    [
                        ft.IconButton(
                            ft.Icons.CANCEL_OUTLINED,
                            tooltip="Unselect file",
                            on_click=lambda _: self.remove_file(file.name),
                        ),
                        ft.ProgressRing(0.0),
                        ft.Text(file.name),
                    ]
                )

                if file.name in self.file_names:
                    index = self.file_names.index(file.name)
                    self.upload_files[index] = file
                    self.preview_fields[index] = preview_field
                else:
                    self.upload_files.append(file)
                    self.preview_fields.append(preview_field)
                    self.file_names.append(file.name)

        async def remove_file(self, file_name: str):
            with self._lock:
                index = self.file_names.index(file_name)
                self.file_names.remove(file_name)
                self.preview_fields.pop(index)
                self.upload_files.pop(index)

        def get_upload_file(self, file_name: str):
            with self._lock:
                return self.upload_files[self.file_names.index(file_name)]

        def get_preview_field(self, file_name: str):
            with self._lock:
                return self.preview_fields[self.file_names.index(file_name)]


    class InputField(ft.ListView):
        def __init__(self,**kwargs):
            super().__init__([],**kwargs)

        def get(self)->dict[str,Any]:
            """This assistant data will call .model_validate to output of this method."""
            pass

        def add(self, name:str, field:FieldInfo, control: ft.Control):
            title = name.title()
            if field.is_required():
                title += " (REQUIRE)"
            self.controls.append(
                ft.Column(
                    [
                        ft.Text(title, size=15, weight=ft.FontWeight.BOLD),
                        ft.Text(f"Description: {field.description}", size=10),
                        control
                    ]
                )
            )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.auth_ui = MainView.AuthUI(
            title=ft.Text(
                "Chatbone",
                size=50,
                weight=ft.FontWeight.BOLD,
                text_align=ft.TextAlign.CENTER,
            ),
            signup_button=ft.Button(
                text="Signup", on_click=self.switch_click("signup")
            ),
            login_button=ft.Button(text="Login", on_click=self.login_click),
        )

        self.chat_ui: MainView.ChatUI = None  # post_init
        if self.chat_app.userdata is None:
            self.controls = [self.auth_ui]
            self.appbar.actions = []

    async def post_init(self):
        if self.chat_app.userdata is not None:
            assert self.chat_ui is None
            await self._init_chat_ui()
            assert isinstance(self.chat_ui, MainView.ChatUI)
            self.controls = [self.chat_ui]
            self.appbar.actions = [ft.Button(text="Logout", on_click=self.logout_click)]

    async def _init_chat_ui(self):
        # Todo

        pass

    def _get_input_fields(
        self, assistant_schema: Type[AssistantData]
    ) -> "MainView.InputField":
        lv = MainView.InputField()

        data_fields: dict[str, FieldInfo] = assistant_schema.get_data_fields()

        for name, field in data_fields.items():
            lv.add(name,field, self._get_input_field())
        return lv

    def _get_input_field(self, ann: type[Any] ) -> ft.Control:
        args = list(get_args(ann)).remove(None)
        origin = get_origin(ann)

        if origin is None:
            if issubclass(ann,MediaObject):
                return self._get_media_input_field(ann)
            elif issubclass(ann, Selection):



            elif issubclass(ann,Text):
                pass


        elif origin is UnionType: # Outer most union.
            union_controls: list[ft.Control] = []
            for t in args:
                if get_origin(t) is not None:
                    union_controls.append(self._get_input_field(t))
                else:
                    if issubclass(t,MediaObject):
                        union_controls.append(self._get_media_input_field(t))
                    elif
            return MainView.InputOptions(union_controls)

        elif origin is list:
            for t in args:
                if get_origin(t) is not None:


        else:
            logger.error(f"Fail when making input field from type hint '{ann}'")
            return ft.Text("Assistant error, cannot parse assistant schema to show input fields.")

    def _get_media_input_field(
        self, datatype: type[MediaObject | List[AnyMediaObject]]
    ) -> ft.Control:
        """
        Args:
                datatype: the type hint class, must be MediaObject or  List[AnyMediaObject] class, not instance.
        Returns:
                ft.Control with layout:

        Notes:
            1. Does not support container inside container.
            2. List of Union ?
        """

        is_list: bool = False
        """The datatype is List[AnyMediaObject]."""
        object_types: Sequence[AnyMediaObject] = ()
        """All objects type that requested."""

        file_picker = ft.Ref[FilePicker]()
        select_button = ft.Ref[ft.ElevatedButton]()

        def _validate():
            if get_origin(datatype) == list:
                object_types = get_args(datatype)
                is_list = True
            else:
                object_types = [datatype]
            for dt in object_types:
                assert issubclass(dt, MediaObject)

        await asyncio.to_thread(_validate)

        selected_files = MainView.SelectedFiles()
        self.page.add(ft.Column(selected_files.preview_fields))

        async def on_result(e: ft.FilePickerResultEvent):
            if e.files is not None:
                for file in e.files:
                    object_name = uuid7(as_type="str") + "_" + file.name
                    upload_url = await datatype.get_upload_url(
                        object_name,
                        extension=None,
                        tagging={
                            "username": self.chat_app.userdata.username,
                            "user_id": self.chat_app.userdata.id,
                            "presigned_at": utc_now(),
                        },
                    )
                    selected_files.add_new_file(
                        ft.FilePickerUploadFile(name=file.name, upload_url=upload_url)
                    )
                    file_picker.upload(selected_files.upload_files)
                self.page.update()

        async def on_upload(e: ft.FilePickerUploadEvent):
            preview_field = selected_files.get_preview_field(e.file_name).controls
            if floor(e.progress) == 1:
                await asyncio.sleep(
                    0.05
                )  # sleep for ensure loaded.  # object = datatype.validate_object()

        button_name = "Select " + datatype.type.lower()
        if is_list:
            button_name += "s"

        filetype = getattr(
            ft.FilePickerFileType, datatype.type, ft.FilePickerFileType.CUSTOM
        )
        allowed_extensions: List[str] = []
        if (
            filetype := getattr(
                ft.FilePickerFileType, datatype.type, ft.FilePickerFileType.CUSTOM
            )
            == ft.FilePickerFileType.CUSTOM
        ):
            allowed_extensions = await asyncio.to_thread(
                lambda _: [m.extension for m in datatype.matchers]
            )

        select_button_kwargs = {
            "text": button_name,
            "icon": getattr(MediaIcons, datatype.type),
            "on_click": lambda _: file_picker.pick_files(
                file_type=filetype,
                allowed_extensions=allowed_extensions,
                allow_multiple=is_list,
            ),
        }
        self.page.add(
            FilePicker(ref=file_picker, on_result=on_result, on_upload=on_upload),
            ft.ElevatedButton(ref=select_button, **select_button_kwargs),
        )

    async def chat_session_change(self):
        pass

    async def assistant_change(self):
        pass

    def make_chat_input_field(self):
        self.chat_input_field.controls.append(ft.TextField(), ft.FilePicker())

    async def logout_click(self, e):
        await self.chat_app.logout()
        await self.chat_app.route_change(views_params_dict["main"]["route"])

    async def login_click(self, e):
        await self.chat_app.login()
        if self.chat_app.userdata is None:
            self.go(views_params_dict["login"]["route"])
        else:
            self.go(views_params_dict["main"]["route"])


VIEW_TYPE = LoginView | SignupView | MainView


class ViewCreator(BaseModel):
    view: VIEW_TYPE = Field(discriminator="view_name")

    @classmethod
    async def create(cls, view_name: str, chat_app: "ChatApp") -> ChatboneView:
        obj: VIEW_TYPE = cls(view={"view_name": view_name, "chat_app": chat_app}).view
        await obj.post_init()
        return obj


a = ImageObject, VideoObject, AudioObject, DocumentObject, TextStream, Selection

Input2Control = {ImageObject: ft.FilePicker()}


class ChatApp:

    def __init__(self, page: ft.Page):
        self.page = page
        self.route2viewname: dict[str, str] = {}
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

    @property
    def chat_assistant_svc(self):
        return self._chat_assistant_svc

    @property
    def userdata(self) -> UserData | None:
        if self.chat_assistant_svc is not None:
            return self.chat_assistant_svc.userdata
        return None

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
        logger.info(f"local data in session {local_data}.")
        if local_data:
            try:
                userdata = await UserData.verify_encrypted_token(
                    local_data["encrypted_token"]
                )
                self.fire_heartbeat_task()
                self._chat_assistant_svc = await ChatAssistantSVC.create(userdata)
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
        app.go(views_params_dict["main"]["route"])

    async def route_change(self, e: ft.RouteChangeEvent | str):
        """Notes: This method can be used to reset"""
        route_str = e if isinstance(e, str) else e.route
        routes = route_str.split("/")
        if routes[0] != "":  # Ex: "ass" or "ass/hole". The correct one is "/ass/hole"
            raise ValueError(f"Route must start with '/'. Got '{routes}'.")
        if routes[1] == "":  # "/"
            routes.pop(1)
        self.page.views.clear()
        r = ""
        for route in routes:
            r = Path(r + "/" + route).resolve().__str__()
            if self.route2viewname.get(r) is None:
                self.route2viewname[r] = await asyncio.to_thread(route2viewname, r)
            self.page.views.append(
                await ViewCreator.create(self.route2viewname[r], self)
            )
        self.page.update()
        logger.info(
            f"Page id '{self.id}' go to '{route_str}'. Views stack: {[(v.__class__.__name__,v.uid) for v in self.page.views]}"
        )

    async def view_pop(self, e: ft.ViewPopEvent):
        self.page.views.pop()
        self.go(self.page.views[-1].route)
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


@serve.deployment(num_replicas=3)
@serve.ingress(chat_fa_app)
class ChatboneApp:

    def __init__(self):
        import os
        import threading

        logger.debug(
            f"{self.__class__.__name__} started at Process:{os.getpid()}-Thread:{threading.get_native_id()}"
        )


if __name__ == "__main__":
    serve.run(ChatboneApp.bind())
