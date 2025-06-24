import asyncio
import threading
from abc import ABC, abstractmethod
from contextlib import AsyncExitStack, asynccontextmanager, AbstractAsyncContextManager
from copy import deepcopy
from datetime import timedelta, datetime, timezone
from enum import Enum
from functools import partial
from inspect import iscoroutinefunction
from math import floor
from types import NoneType, UnionType, FunctionType, MethodType
from typing import (
    Any,
    Callable,
    List,
    get_origin,
    Literal,
    get_args,
    Annotated,
    Self,
    Awaitable,
    AsyncContextManager,
    AsyncGenerator,
    AsyncIterator,
)
from uuid import UUID

import flet as ft
from flet.core.buttons import RoundedRectangleBorder
from flet.core.file_picker import (
    FilePickerResultEvent,
    FilePickerUploadEvent,
    FilePickerFile,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    TypeAdapter,
    field_validator,
    Field,
)

from chatbone.assistant_interface import (
    AssistantDataType_U,
    AnyMediaObject,
    MediaObject,
    ImageObject,
    InvalidFileExtension,
    InvalidBinaryFile,
    AssistantInputData,
    Text,
    BaseForm,
    DocumentObject,
)
from utilities.func import utc_now
from utilities.logger import logger
from utilities.misc import UniversalLock


class BaseUI(ft.Container, BaseModel, ABC):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.content = self._get_content()

    @abstractmethod
    def _get_content(self) -> ft.Control:
        """This method return a content as ft.Control to pass it to ft.Container.content"""


class BaseInputField(ABC, ft.Container):

    def __init__(self, *args, **kwargs):
        self._able_lock = UniversalLock()

        self._snackbar: ft.SnackBar = None
        """For notice user"""

        super().__init__(*args, **kwargs)

    @abstractmethod
    async def get_assistant_data(
        self, **kwargs
    ) -> AssistantDataType_U | List[AssistantDataType_U] | None:
        """Should only get VALID data, invalid data should be treated as no data and return None."""
        pass

    @abstractmethod
    async def _refresh(self):
        """Refresh for this InputField class only, will be call by cleanup(). Clean all pending state.
        Should not inplement logic for sub InputField, which will be done by cleanup() method instead.
        """
        pass

    @property
    @abstractmethod
    def sub_input_fields(self) -> list["BaseInputField"]:
        """This property return sub input fields (not self), used to cleanup.
        If class does not have input field, explicitly return []"""
        return []

    @property
    def preview_control(self) -> ft.Control:
        """Control that should be shown for preview. This is optional for overriding."""
        return self

    async def cleanup(self) -> Self:
        """Refresh self and all children, which is got by input_fields property."""
        await self._refresh()
        for input_field in self.sub_input_fields:
            await input_field.cleanup()
        return self

    def disable(self) -> Self:
        with self._able_lock:
            self.disabled = True
            self.visible = False
            return self

    def enable(self) -> Self:
        with self._able_lock:
            self.disabled = False
            self.visible = True
            return self

    def notice_user(self, text: str):
        l = len(self.page.overlay)
        if self._snackbar:
            self._snackbar.content = ft.Text(text, size=10)
        else:
            self._snackbar = ft.SnackBar(
                ft.Text(text),
                behavior=ft.SnackBarBehavior.FLOATING,
                dismiss_direction=ft.DismissDirection.VERTICAL,
                width=1000,
                duration=10000,
                show_close_icon=True,
                shape=RoundedRectangleBorder(radius=10),
            )
            l += 1
        self.page.open(self._snackbar)
        assert len(self.page.overlay) == l  # Ensure snackbar not accumulate.
        # TODO: flet-toast available is not a good code, rewrite new toast library, use simple snackbar for now.
        # flet_toast.warning(self.page,text,position=Position.BOTTOM_RIGHT,duration=10)
        # flet_toast.warning(self.page,text,position=Position.BOTTOM_RIGHT,duration=15)


class _FilePicker(ft.FilePicker):
    """File picker for one media type."""

    def __init__(
        self,
        username: str,
        user_id: UUID,
        datatype: type[MediaObject],
        allow_multiple: bool = False,
        *,
        # flet.FilePicker arguments
        on_result: Callable[[FilePickerResultEvent], None] | None = None,
        on_upload: Callable[[FilePickerUploadEvent], None] | None = None,
        ref: ft.Ref | None = None,
        disabled: bool = None,
        data: Any = None,
    ):
        # Config attributes
        self._username = username
        self._user_id = user_id
        self._datatype = datatype
        self._expires = timedelta(seconds=100)  # todo, it should be configurable
        self._allowed_extensions = datatype.extensions
        self._allow_multiple = allow_multiple

        super().__init__(on_result, on_upload, ref, disabled, data)

    async def pick_files(self, e=None):
        await asyncio.to_thread(
            super().pick_files,
            dialog_title=self._datatype.type.title(),
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=self._allowed_extensions,
            allow_multiple=self._allow_multiple,
        )

    async def upload(
        self, picked_files: List[FilePickerFile]
    ) -> tuple[list[ft.FilePickerUploadFile], list[InvalidFileExtension]]:
        """
        Upload the correct files.
        Args:
            picked_files: It should input as name, but use FilePickerFile because of Flet convention.
        Returns:
            List of correct files and list of exceptions.
        """

        upload_files: list[ft.FilePickerUploadFile] = []
        file_exceptions: list[InvalidFileExtension] = []
        for file in picked_files:
            try:
                url = await self._create_upload_url(file.name)
                upload_files.append(
                    ft.FilePickerUploadFile(file.name, url)
                )  # todo: wtf FilePickerUploadFile.id used for?
            except InvalidFileExtension as e:
                e.filename = file.name
                file_exceptions.append(e)
        super().upload(upload_files)
        return upload_files, file_exceptions

    async def cancel(self, filename: str):
        """
        Cancel uploading or pending and clean the storage.
        Args:
                filename:
        """
        await self._wait_for_canceled(filename)
        await self._datatype.object_storage.remove_object(
            self._make_object_name(filename)
        )

    async def _wait_for_canceled(self, filename: str):
        """TODO: Send command to frontend and wait for cancelled successfully."""
        pass

    async def _create_upload_url(self, file_name: str) -> str:
        return await self._datatype.get_upload_url(
            self._make_object_name(file_name),
            extension=None,
            tagging={
                "username": self._username,
                "user_id": self._user_id,
                "presigned_at": utc_now(),
            },
            expires=self._expires,
        )

    def _make_object_name(self, file_name: str):
        return "/".join(
            [
                self._username + "_" + str(self._user_id),
                str(datetime.now(timezone.utc).date()),
                file_name,
            ]
        )


class MediaInputField(BaseInputField):
    """Preview field for one file."""

    class MediaIcons(Enum):
        IMAGE = ft.Icons.IMAGE_OUTLINED
        VIDEO = ft.Icons.VIDEO_FILE_OUTLINED
        AUDIO = ft.Icons.AUDIO_FILE_OUTLINED
        DOCUMENT = ft.Icons.DOCUMENT_SCANNER_OUTLINED

    class _FilePreviewRow(ft.Row):

        def __init__(self, filename, media_field: "MediaInputField", **kwargs):
            super().__init__(vertical_alignment=ft.CrossAxisAlignment.CENTER, **kwargs)
            self.controls = [
                ft.IconButton(
                    ft.Icons.CANCEL_OUTLINED,
                    tooltip=f"Unselect file: {filename}",
                    on_click=self._unselect,
                ),
                ft.ProgressRing(0.0, scale=0.8),
                ft.Text(
                    f"{filename[:10]}+...+{filename[-10:]}",
                    size=12,
                    text_align=ft.TextAlign.LEFT,
                ),
            ]

            self._filename = filename
            self._media_field = media_field
            self.media_object: AnyMediaObject = None

        async def _unselect(self, e):
            await self._media_field._unselect(self._filename, update=True)

        async def update_progress(
            self, progress: float, media_object: AnyMediaObject = None
        ):
            assert progress >= 0
            if progress >= 1:
                assert isinstance(media_object, AnyMediaObject)
                preview_url = await media_object.get_preview_url()
                self.controls[1] = ft.IconButton(
                    ft.Icons.PREVIEW_ROUNDED,
                    on_click=lambda e: self.page.launch_url(preview_url),
                    tooltip=f"Preview file: {self._filename}",
                )
                self.media_object = media_object
            else:
                pr = self.controls[1]
                assert isinstance(pr, ft.ProgressRing)
                pr.value = progress
            self.page.update()

    def __init__(
        self,
        username: str,
        user_id: UUID,
        datatype: type[MediaObject],
        allow_multiple: bool = False,
        **kwargs,
    ):
        self._datatype = datatype
        self._allow_multiple = allow_multiple

        # Control
        self._file_picker = _FilePicker(
            username,
            user_id,
            datatype,
            allow_multiple,
            on_result=self._on_result,
            on_upload=self._on_upload,
        )

        button_title = f"Select {self._datatype.type.title()}"
        button_title = button_title + "s" if allow_multiple else button_title
        icon = getattr(MediaInputField.MediaIcons, datatype.type).value
        tooltip = f"Allowed extensions: {self._file_picker._allowed_extensions}"

        self._select_button = ft.ElevatedButton(
            button_title,
            on_click=self._file_picker.pick_files,
            icon=icon,
            tooltip=tooltip,
            scale=0.8,
        )
        self._unselect_all_button = ft.IconButton(
            ft.Icons.CANCEL_PRESENTATION_OUTLINED,
            tooltip="Unselect all",
            on_click=self._unselect_all,
            disabled=True,
            visible=False,
        )
        self._file_index_lock = UniversalLock()
        self._file_names: list[str] = []
        self._file_list = ft.ListView([], height=250, width=320)
        """controls attribute is list[_FilePreviewRow]"""

        column = ft.Column(
            [
                ft.Row(
                    [self._select_button, self._unselect_all_button],
                    alignment=ft.MainAxisAlignment.START,
                    spacing=0,
                ),
                self._file_list,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
            width=320,
        )

        super().__init__(column, border=ft.border.all(1), **kwargs)

        self._button_state_lock = UniversalLock()

    async def get_assistant_data(
        self, **kwargs
    ) -> AssistantDataType_U | List[AssistantDataType_U] | None:
        """
        Returns:
            If allow_multiple, return a list of MediaObject or a blank list. Else return only one MediaObject or None.
        """
        if not self._allow_multiple:
            assert len(self._file_names) <= 1
            return (
                (await self.get_file_preview_row(self._file_names[0])).media_object
                if len(self._file_names) == 1
                else None
            )

        async with self._file_index_lock:
            if not self._file_names:
                return []
            else:
                return [
                    f.media_object
                    for f in self._file_list.controls
                    if isinstance(f, MediaInputField._FilePreviewRow)
                    and f.media_object is not None
                ]

    def build(self):
        if not self._file_picker in self.page.overlay:
            self.page.overlay.append(self._file_picker)

    async def _on_result(self, e: ft.FilePickerResultEvent):
        """Add files to selected file list. Do not override."""
        if e.files is not None:
            # If not allow multiple, unselect the old and load the new.
            if not self._allow_multiple:
                assert len(self._file_names) <= 1
                await self._unselect_all()

            # If filename already available, unselect the old and load the new (override).
            for file in e.files:
                if file.name in self._file_names:
                    await self._unselect(file.name)

            # Upload the correct files, and dismiss others.
            async with self._file_index_lock:
                uploaded_files, file_exceptions = await self._file_picker.upload(
                    e.files
                )
                await self.make_file_preview_rows(uploaded_files, lock=False)
                self._change_unselect_all_button_state()
                self.page.update()

            def _log():
                filenames = [e.filename for e in file_exceptions]
                if filenames:
                    logger.info(
                        f"User '{self._file_picker._username}' uploaded {len(filenames)} incorrect extension files: {filenames}\n"
                        f"Allowed extensions: {file_exceptions[0].al_ex}"
                    )
                    self.notice_user(
                        f"Files: {filenames} have incorrect extensions and were unselected.\n"
                        f"Allowed extensions: {file_exceptions[0].al_ex}"
                    )

            await asyncio.to_thread(_log)

    async def _on_upload(self, e: ft.FilePickerUploadEvent):
        if e.error:
            await self._unselect(e.file_name, update=False)
            logger.info(f"Error happened during uploading file: '{e.error}'")
            self.notice_user(
                f"There is an server error while uploading file '{e.file_name}'."
            )
        else:
            media_object = None
            if floor(e.progress) == 1:
                try:
                    media_object = await self._datatype.validate_object(
                        self._file_picker._make_object_name(e.file_name)
                    )
                    await self.update_progress(e.file_name, e.progress, media_object)
                except InvalidBinaryFile:
                    await self._unselect(e.file_name, update=False)
                    m = "Uploaded file has the correct extension but wrong magic binary."
                    logger.info(m)
                    self.notice_user(
                        f"{m}. Make sure your extension of the file matches with binary structure. Unselect file '{e.file_name}'."
                    )
            else:
                await self.update_progress(e.file_name, e.progress, media_object)

    async def _unselect_all(self, e=None):
        async with self._file_index_lock:
            for filename in deepcopy(self._file_names):
                await self._unselect(filename, update=False, lock=False)
            self.page.update()

    async def _unselect(self, filename, update: bool = True, lock: bool = True):
        should_lock = lock
        async with AsyncExitStack() as stack:
            if lock:
                await stack.enter_async_context(self._file_index_lock)
                should_lock = False
        await self._file_picker.cancel(filename)
        await self.remove_file_review_row(filename, should_lock)
        if update:
            self.page.update()

    def _change_unselect_all_button_state(self):
        with self._button_state_lock:
            if self._file_names:
                self._unselect_all_button.disabled = False
                self._unselect_all_button.visible = True
            else:
                self._unselect_all_button.disabled = True
                self._unselect_all_button.visible = False

    async def update_progress(self, filename: str, progress: float, media_object=None):
        async with self._file_index_lock:
            row = await self.get_file_preview_row(filename, lock=False)
            await row.update_progress(progress, media_object)

    async def get_file_preview_row(
        self, filename: str, lock: bool = True
    ) -> "MediaInputField._FilePreviewRow":
        async with AsyncExitStack() as stack:
            if lock:
                await stack.enter_async_context(self._file_index_lock)
            index = self._file_names.index(filename)
            return self._file_list.controls[index]

    async def remove_file_review_row(
        self, filename: str, lock: bool = True
    ) -> "MediaInputField._FilePreviewRow":
        async with AsyncExitStack() as stack:
            if lock:
                await stack.enter_async_context(self._file_index_lock)
            index = self._file_names.index(filename)
            self._file_names.pop(index)
            fr = self._file_list.controls.pop(index)
            self._change_unselect_all_button_state()
            return fr

    async def make_file_preview_rows(
        self, uploaded_files: list[ft.FilePickerUploadFile], lock: bool = True
    ):
        async with AsyncExitStack() as stack:
            if lock:
                await stack.enter_async_context(self._file_index_lock)

            def _do():
                for file in uploaded_files:
                    self._file_list.controls.append(
                        MediaInputField._FilePreviewRow(file.name, self)
                    )
                    self._file_names.append(file.name)

            await asyncio.to_thread(_do)
            self._change_unselect_all_button_state()

    async def _refresh(self) -> None:
        await self._unselect_all()
        if self._file_picker in self.page.overlay:
            self.page.overlay.remove(self._file_picker)
            self.page.update()

    @property
    def sub_input_fields(self) -> list["BaseInputField"]:
        return []

    @property
    def preview_control(self) -> ft.Control:
        return ft.ListView(
            [m.controls[1:] for m in self._file_list.controls],
            height=self._file_list.height,
            width=self._file_list.width,
        )


class TextInputField(BaseInputField):

    def __init__(
        self,
        input_filter: ft.InputFilter = None,
        validator: Callable[[str], bool | Awaitable[bool]] = None,
        **kwargs,
    ):
        self._textfield = ft.TextField(
            input_filter=input_filter, on_change=self._on_change
        )
        self._validator = validator
        self._is_valid: bool = True
        self._preview_text = ft.Text(value=self._textfield.value)
        self._init = True  # check for newest text
        super().__init__(self._textfield, border=ft.border.all(1))

    async def _on_change(self, e):
        if self._init:
            self._init = False
        m = ""
        try:
            await self._validate()
        except Exception as e:
            self._is_valid = False
            m = f": {e}"
        self._textfield.helper_text = f"Invalid input{m}" if not self.is_valid else None
        self._preview_text.value = f"{self._textfield.value} {f"({self._textfield.helper_text})" if self._textfield.helper_text else ""} "
        self.page.update()

    async def _validate(self):
        if not callable(self._validator):
            self._is_valid = True if self.value is not None else False
        else:
            if iscoroutinefunction(self._validator):
                self._is_valid = await self._validator(self.value)
            else:
                self._is_valid = await asyncio.to_thread(self._validator, self.value)

    @property
    def is_valid(self) -> bool:
        return self._is_valid

    @property
    def value(self) -> str | None:
        return self._textfield.value

    @property
    def preview_control(self) -> ft.Control:
        return self._preview_text

    async def get_assistant_data(
        self, **kwargs
    ) -> AssistantDataType_U | List[AssistantDataType_U] | None:
        if self._init:
            # noinspection PyBroadException
            try:
                await self._validate()
                self._init = False
            except Exception:
                self._is_valid = False
                self._init = False
                return None
        r = Text(role="user", content=self.value) if self.is_valid else None
        return r

    async def _refresh(self) -> None:
        self._is_valid = False
        self._textfield.value = None
        self.page.update()

    @property
    def sub_input_fields(self) -> list["BaseInputField"]:
        return []


class InputFieldOption(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    input_field: BaseInputField
    description: str | None = None

    @field_validator("input_field", mode="after")
    @classmethod
    def _disable_all_fields(cls, field: BaseInputField) -> BaseInputField:
        field.disable()
        return field


class MultiOptionsInputField(BaseInputField):
    """User provide only one input according to only one options."""

    def __init__(
        self, input_field_options: dict[str, InputFieldOption], *args, **kwargs
    ):
        self._keys: list[str] = []
        self._stack = ft.Stack([])
        self._dropdown = ft.Dropdown(
            label="Options", options=[], on_change=self._on_change
        )
        self._desc = ft.Text()

        self._input_field_lock = UniversalLock()
        """This lock is used to sync stack and dropdown."""

        with self._input_field_lock:
            for key, opt in input_field_options.items():
                self._keys.append(key)
                self._stack.controls.append(opt.input_field)
                self._dropdown.options.append(ft.DropdownOption(key))
            self._input_field_options = input_field_options

        self._enable_lock = UniversalLock()
        self._current_enable_idx = None

        content = ft.Column(
            [
                ft.Row([ft.Text("Input type option:"), self._dropdown]),
                self._desc,
                self._stack,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
        )

        super().__init__(content, *args, **kwargs)

    async def _on_change(self, e):
        async with self._input_field_lock:
            async with self._enable_lock:
                new_key = self._dropdown.value
                idx = self._keys.index(new_key)
                if self._current_enable_idx is not None:
                    (
                        await self.sub_input_fields[self._current_enable_idx].cleanup()
                    ).disable()
                self.sub_input_fields[idx].enable()
                self._desc.value = self._input_field_options[new_key].description
                self._current_enable_idx = idx
                self.page.update()

    @property
    def sub_input_fields(self) -> list[BaseInputField]:
        return self._stack.controls

    async def get_assistant_data(
        self,
        return_meta: bool = False,
    ) -> AssistantDataType_U | list[AssistantDataType_U] | None:
        """
        Returns:
            A tuple of key and data if return_meta is True else return just data.
        """
        async with self._input_field_lock:
            for k, f in zip(self._keys, self.sub_input_fields):
                if d := (await f.get_assistant_data()):
                    if return_meta:
                        return k, d
                    return d
            return None

    @property
    def preview_control(self) -> ft.Control:
        return ft.Stack([c.preview_control for c in self.sub_input_fields])

    async def _refresh(self):
        pass


class InputFieldFactory(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    factory: Callable[..., BaseInputField | Awaitable[BaseInputField]]
    args: list[Any] = Field(default_factory=list)
    kwargs: dict[str, Any] = Field(default_factory=dict)


class ListInputField(BaseInputField):

    class _SavedField(ft.Row):
        def __init__(
            self,
            input_field: BaseInputField,
            list_input_field: "ListInputField",
            **kwargs,
        ):

            self._input_field = input_field.disable()
            self._list_input_field = list_input_field

            self._edit_button = ft.IconButton(
                ft.Icons.EDIT,
                on_click=partial(
                    list_input_field._on_open_edit_sheet, current_saved_field=self
                ),
            )
            self._remove_button = ft.IconButton(
                ft.Icons.CANCEL_OUTLINED,
                on_click=partial(
                    list_input_field._on_remove_saved_field, current_saved_field=self
                ),
            )

            super().__init__(
                controls=[self._edit_button, self._remove_button, self._input_field],
                **kwargs,
            )

        @property
        def input_field(self):
            return self._input_field

    def __init__(self, input_field_factory: InputFieldFactory, **kwargs):
        if not iscoroutinefunction(input_field_factory):
            f = input_field_factory.factory

            async def _factory(*args, **kwargs):
                return await asyncio.to_thread(f, *args, **kwargs)

            input_field_factory.factory = _factory
        self._input_field_factory: InputFieldFactory = input_field_factory

        self._add_new_button = ft.IconButton(
            ft.Icons.ADD_CIRCLE_OUTLINE_OUTLINED,
            on_click=self._on_open_input_sheet,
            tooltip="Add new input",
        )

        self._remove_all_button = ft.IconButton(
            ft.Icons.CANCEL_PRESENTATION_OUTLINED,
            on_click=self._on_remove_all,
            tooltip="Remove all data",
        )

        self._content_lock = UniversalLock()
        """Lock for manipulate input field."""

        self._listview = ft.ListView([], height=250, width=320)

        content = ft.Column(
            [
                self._listview,
                ft.Row([self._add_new_button, self._remove_all_button]),
            ]
        )
        super().__init__(content=content, **kwargs)

        self._sheet_input_field: BaseInputField | None = None
        self._sheet_index_field = ft.TextField(
            label="Index", input_filter=ft.NumbersOnlyInputFilter()
        )

        self._sheet = ft.BottomSheet(ft.Container(), on_dismiss=self._on_dismiss_sheet)

    def build(self):
        if not self._sheet in self.page.overlay:
            self.page.overlay.append(self._sheet)

    @property
    def _saved_field_list(self) -> list[_SavedField]:
        return self._listview.controls

    @property
    def _sheet_content(self):
        return self._sheet.content.content

    @_sheet_content.setter
    def _sheet_content(self, value: ft.Control):
        self._sheet.content.content = value

    async def _on_dismiss_sheet(self, e=None):
        assert not await self._content_lock.aacqurie(blocking=False)
        if self._sheet_input_field:
            await self._sheet_input_field.cleanup()
            self._sheet_input_field = None
            self._sheet_content = None
            self._sheet_index_field.value = None
        self.update()
        await self._content_lock.arelease()

        print([p.__class__.__name__ for p in self.page.overlay])
        print(self._saved_field_list)

    async def _on_open_input_sheet(self, e):
        await self._content_lock.aacqurie()  # Lock until dismiss
        try:
            self._sheet_input_field = await self._input_field_factory.factory(
                *self._input_field_factory.args, **self._input_field_factory.kwargs
            )
            self._sheet_index_field.value = None
            self._sheet_content = ft.Column(
                [
                    self._sheet_index_field,
                    self._sheet_input_field,
                    ft.Button(
                        "Save",
                        on_click=self._on_save_input_sheet,
                    ),
                ]
            )
            self.page.open(self._sheet)

        except Exception as e:
            logger.exception(e)
            self.page.close(self._sheet)
            self.notice_user("Server error when open input sheet.")

    async def _on_open_edit_sheet(self, e, *, current_saved_field: _SavedField):
        await self._content_lock.aacqurie()  # Lock until dismiss
        try:
            # todo: deep copy is dump. construct and do get_state instead.
            #  For now just construct entirely new. Every thing go right
            self._sheet_input_field = await self._input_field_factory.factory(
                *self._input_field_factory.args, **self._input_field_factory.kwargs
            )
            index = self._saved_field_list.index(current_saved_field)
            self._sheet_content = ft.Column(
                [
                    ft.Text(f"Edit input at index {index}"),
                    self._sheet_input_field,
                    ft.Button(
                        "Update",
                        on_click=partial(
                            self._on_save_edit_sheet,
                            index=index,
                        ),
                    ),
                ]
            )
            self.page.open(self._sheet)

        except Exception as e:
            logger.exception(e)
            self.page.close(self._sheet)
            self.notice_user("Server error when open edit sheet.")

    async def _on_save_input_sheet(self, e):
        async with self.__save_sheet_cm(
            "Saved", "Cannot save, the input is wrong."
        ) as input_field:
            if isinstance(input_field, BaseInputField):
                save_field = ListInputField._SavedField(input_field, self)
                if (idx := self._sheet_index_field.value) and (i := int(idx)) < len(
                    self._saved_field_list
                ):
                    self._saved_field_list.insert(i, save_field)
                else:
                    self._saved_field_list.append(save_field)

    async def _on_save_edit_sheet(self, e, *, index: int):
        async with self.__save_sheet_cm(
            "Updated", "Cannot Update, the input is wrong. Still hold the current one."
        ) as input_field:
            if isinstance(input_field, BaseInputField):
                # IMPORTANT: CLEAN UP BEFORE REMOVE.
                await self._saved_field_list[index].input_field.cleanup()
                self._saved_field_list.pop(index)
                self._saved_field_list.insert(
                    index, ListInputField._SavedField(input_field, self)
                )

    @asynccontextmanager
    async def __save_sheet_cm(
        self, s_m: str, f_m: str
    ) -> AsyncIterator[BaseInputField | None]:
        # Check for already locked, acquire() return false and self._sheet_input_field is already created
        assert (not await self._content_lock.aacqurie(blocking=False)) and (
            self._sheet_input_field is not None
        )

        if await self._sheet_input_field.get_assistant_data():
            try:
                yield self._sheet_input_field
                # Do something.
                self._sheet_input_field = None
                self._sheet_index_field.value = None
                self._sheet_content = None
                self.page.close(self._sheet)
                self.notice_user(s_m)  # success message
            except Exception as e:
                logger.exception(e)
                self.page.close(self._sheet)
                self.notice_user(
                    "Internal server error. Cannot save or update new data."
                )
                raise
        else:
            yield None
            self.notice_user(f_m)  # fail message

    async def _on_remove_saved_field(
        self,
        e=None,
        *,
        current_saved_field: _SavedField,
        lock: bool = True,
        update: bool = True,
    ):
        async with AsyncExitStack() as stack:
            if lock:
                await stack.enter_async_context(self._content_lock)
            await current_saved_field.input_field.cleanup()
            self._saved_field_list.remove(current_saved_field)
            if update:
                self.page.update()

    async def _on_remove_all(self, e):
        async with self._content_lock:
            while len(self._saved_field_list) > 0:
                await self._on_remove_saved_field(
                    current_saved_field=self._saved_field_list[0],
                    lock=False,
                    update=False,
                )
            self.page.update()

    async def get_assistant_data(
        self, **kwargs
    ) -> AssistantDataType_U | List[AssistantDataType_U] | None:
        async with self._content_lock:
            r = []
            for f in self._saved_field_list:
                data = await f.input_field.get_assistant_data()
                if data is not None:
                    r.append(data)
                else:
                    logger.warning(
                        f"Unexpected behavior, should only save the valid input put field. Detect the field {f} in list but 'get_assistant_data return None'. "
                    )
        r = None if r == [] else r
        return r

    async def _refresh(self):
        pass

    @property
    def sub_input_fields(self) -> list["BaseInputField"]:
        return []


class DictInputField(BaseInputField):
    pass


class FormInputField(BaseInputField):
# TODO
    def __init__(self, selection_type: type[BaseForm]):
        self._datatype = selection_type
        self._fields: dict[str, ft.Control] = {}

        super().__init__(self._make_fields())

    def _make_fields(self) -> ft.Control:
        for name, field in self._datatype.fields():
            control = self._make_field(field.annotation)

    def _make_field(self, ann) -> ft.Control:
        org = get_origin(ann)
        if org == Annotated:
            return self._make_field(get_args(ann)[0])

        if org is None:
            if ann in (str, int, float):
                ta = TypeAdapter
                return ft.Text(filter)

        elif org in (list, UnionType, Literal, tuple, dict):
            new_anns = list(get_args(ann))
            if NoneType in new_anns:
                assert len(new_anns) > 1
                new_anns.remove(NoneType)
            for new_ann in new_anns:
                new_ann = type(new_ann) if org == Literal else new_ann
                self._make_field(new_ann, get_origin(new_ann))

    async def get_assistant_data(
        self, **kwargs
    ) -> AssistantDataType_U | List[AssistantDataType_U] | None:
        pass


class AssistantInputfield(ft.Container):

    def __init___(self, input_datatype: type[AssistantInputData]):
        pass

    async def get_data(self) -> AssistantInputData:
        pass

    async def get_data_nowait(self) -> AssistantInputData:
        pass


if __name__ == "__main__":

    uuid = UUID("0cab9030-a5d5-49a8-ab90-30a5d519a818")
    print(ImageObject.extensions)

    async def main(page: ft.Page):
        page.vertical_alignment = ft.MainAxisAlignment.CENTER
        page.horizontal_alignment = ft.CrossAxisAlignment.CENTER

        def factory(*args, **kwargs):
            def _val(v: str):
                int(v)
                return True

            return MultiOptionsInputField(
                dict(
                    document=InputFieldOption(
                        input_field=MediaInputField("hieu", uuid, DocumentObject),
                        description="Choose one document",
                    ),
                    image=InputFieldOption(
                        input_field=MediaInputField(
                            "hieu",
                            uuid,
                            ImageObject,
                            allow_multiple=True,
                        ),
                        description="Choose many image.",
                    ),
                    text=InputFieldOption(input_field=TextInputField(validator=_val)),
                ),
                *args,
                **kwargs,
            )

        list_input_field = ListInputField(
            InputFieldFactory(
                factory=factory,
                kwargs=dict(
                    border=ft.border.all(1),
                    padding=ft.padding.all(20),
                ),
            ),
            border=ft.border.all(1),
            padding=ft.padding.all(20),
            width=500,
            height=500,
        )
        text = ft.Text()
        page.add(list_input_field, text)

        async def on_click(e):
            if data := (await list_input_field.get_assistant_data()):
                data = "\n".join([repr(d) for d in data])
            text.value = data or "NOTHING"
            page.update()

        page.add(ft.Button("Select all file", on_click=on_click))

    app = ft.app(main, export_asgi_app=True)
    import uvicorn

    uvicorn.run(app, port=5555)
