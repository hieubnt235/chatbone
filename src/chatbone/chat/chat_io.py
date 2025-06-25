import asyncio
import pprint
from abc import ABC, abstractmethod
from contextlib import AsyncExitStack, asynccontextmanager, ExitStack
from copy import deepcopy
from datetime import timedelta, datetime, timezone
from enum import Enum
from functools import partial
from inspect import iscoroutinefunction, isclass
from math import floor
from pprint import pformat
from types import NoneType, UnionType
from typing import (
    Any,
    Callable,
    List,
    get_origin,
    Annotated,
    Self,
    Awaitable,
    AsyncIterator,
    get_args,
    Sequence,
    Iterable,
    Generator,
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
    ValidationError,
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
    DocumentObject,
    BaseSelection,
)
from chatbone.chat.svc import AssistantApp
from utilities.func import utc_now
from utilities.logger import logger
from utilities.misc import UniversalLock, SyncList, SyncListObject

arbitrary_types_allowed_config = ConfigDict(arbitrary_types_allowed=True)


class BaseUI(ft.Container, BaseModel, ABC):
    model_config = arbitrary_types_allowed_config

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
    def sub_input_fields(self) -> Iterable["BaseInputField"]:
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
            await self._media_field._unselect(self._filename)

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

            async with self._file_index_lock:

                # If filename already available, unselect the old and load the new (override).
                for file in e.files:
                    if file.name in self._file_names:
                        await self._unselect(file.name, lock=False, update=False)
                self.page.update()

                # Upload the correct files, and dismiss others.
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
            await self._unselect(e.file_name)
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
                    await self._update_progress(e.file_name, e.progress, media_object)
                except InvalidBinaryFile:
                    await self._unselect(e.file_name)
                    m = "Uploaded file has the correct extension but wrong magic binary."
                    logger.info(m)
                    self.notice_user(
                        f"{m}. Make sure your extension of the file matches with binary structure. Unselect file '{e.file_name}'."
                    )
            else:
                await self._update_progress(e.file_name, e.progress, media_object)

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

    async def _update_progress(self, filename: str, progress: float, media_object=None):
        try:
            async with self._file_index_lock:
                row = await self.get_file_preview_row(filename, lock=False)
                await row.update_progress(progress, media_object)
        except ValueError as e:
            logger.warning(
                f"{e}.This error maybe occur because cancel now does not stop update progress at the frontend, "
                f"so it keep updating. Will be fix in the future by rewrite FilePicker at front end to handle this."
                f"Also note that for now, it still leak in the storage."
            )

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
    def sub_input_fields(self) -> Iterable["BaseInputField"]:
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
        self,text_type: type[Text],
        **kwargs,
    ):
        self._text_type = text_type
        self._textfield = ft.TextField(
            input_filter=text_type.input_filter, on_change=self._on_change
        )
        self._notice_text = ft.Text(value=self._textfield.value)
        self._value = None

        column = ft.Column([self._textfield,self._notice_text])
        super().__init__(column, border=ft.border.all(1))

    async def _on_change(self, e):
        val = await self._validate()
        if val is None:
            self._notice_text.value = "Invalid input"
        else:
            self._notice_text.value = None
        self.value = val
        self.page.update(self._textfield,self._notice_text)

    async def _validate(self):
        try:
            if iscoroutinefunction(self._text_type.validator):
                val = await self._text_type.validator(self._textfield.value)
            else:
                val = await asyncio.to_thread(self._text_type.validator, self._textfield.value)
            if val is None:
                return None
            return str(val)
        except Exception as e:
            logger.warning(e)
            return None

    @property
    def value(self) -> str | None:
        return self._value

    @value.setter
    def value(self, v: str | None):
        self._value = v

    async def get_assistant_data(
        self, **kwargs
    ) -> AssistantDataType_U | List[AssistantDataType_U] | None:
        r = self._text_type(role="user", content=self.value) if self.value else None
        return r

    async def _refresh(self) -> None:
        self._textfield.value = None
        self._notice_text.value = None
        self.value = None
        self.page.update()

    @property
    def sub_input_fields(self) -> Iterable["BaseInputField"]:
        return []


class SelectionInputField(BaseInputField):

    def __init__(self, selection_type: type[BaseSelection], **kwargs):
        """
        Args:
            options: dict with keys are option keys, values is the description.
            **kwargs:
        """
        assert selection_type.options is not None
        self._selection_type = selection_type

        self._dd = ft.Dropdown(
            options=[ft.DropdownOption(k, v) for k, v in selection_type.options.items()]
        )

        self._desc = ft.Text(pformat(selection_type.options))

        content = ft.Column([self._dd, self._desc])

        super().__init__(content, **kwargs)

    async def get_assistant_data(
        self, **kwargs
    ) -> AssistantDataType_U | List[AssistantDataType_U] | None:
        if (v := self._dd.value ) is None:
            return None
        return self._selection_type(selection=v)

    async def _refresh(self):
        pass

    @property
    def sub_input_fields(self) -> Iterable["BaseInputField"]:
        return []


class InputFieldOption(BaseModel):
    model_config = arbitrary_types_allowed_config
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
            label="Form options", options=[], on_change=self._on_change
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
    model_config = arbitrary_types_allowed_config
    factory: Callable[..., BaseInputField | Awaitable[BaseInputField]]
    args: Sequence[Any] = Field(default_factory=list)
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
        """Lock for manipulate input field. (Not for sync some heaper attribute of fields)."""

        self._listview = ft.ListView([], height=250, width=320)
        """Control of this ListView is _SavedField object, should access through _saved_field_list"""

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
        async with self._save_sheet_cm() as (index, input_field):
            if isinstance(input_field, BaseInputField):
                save_field = ListInputField._SavedField(input_field, self)

                if index and (i := int(index)) < len(self._saved_field_list):
                    self._saved_field_list.insert(i, save_field)
                else:
                    self._saved_field_list.append(save_field)
                self._clean_sheet()  # IMPORTANT, clean sheet for not cleanup input field when close sheet.
                self._close_sheet()
                self.notice_user("Saved")
            else:
                self.notice_user("Cannot save, the input is wrong.")

    async def _on_save_edit_sheet(self, e, *, index: int):
        async with self._save_sheet_cm() as (_, input_field):
            if isinstance(input_field, BaseInputField):
                # IMPORTANT: CLEAN UP BEFORE REMOVE.
                await self._saved_field_list[index].input_field.cleanup()
                self._saved_field_list.pop(index)
                self._saved_field_list.insert(
                    index, ListInputField._SavedField(input_field, self)
                )
                self.notice_user("Updated")
                self._clean_sheet()
                self._close_sheet()
            else:
                self.notice_user(
                    "Cannot Update, the input is wrong. Still hold the current one."
                )

    @asynccontextmanager
    async def _save_sheet_cm(self) -> AsyncIterator[tuple[str, BaseInputField | None]]:
        # Check for already locked, acquire() return false and self._sheet_input_field is already created
        assert (not await self._content_lock.aacqurie(blocking=False)) and (
            self._sheet_input_field is not None
        )
        try:
            if await self._sheet_input_field.get_assistant_data():
                yield self._sheet_index_field.value, self._sheet_input_field
            else:
                yield self._sheet_index_field.value, None
            self.page.update()
        except Exception as e:
            logger.exception(e)
            self._close_sheet()
            self.notice_user("Internal server error. Cannot save or update new data.")
            raise

    def _clean_sheet(self):
        """IMPORTANT: This method MUST be called before close sheet if don't want to clean input field ( for success case).
        And MUST NOT be called for case when input field is expected to clean (ex: close sheet without saving intentionally).
         See _on_dismiss_sheet for details."""
        self._sheet_input_field = None
        self._sheet_index_field.value = None
        self._sheet_content = None

    def _close_sheet(self):
        """The on_dismiss_sheet will be called after this method.
        Note that if not _clean_sheet first, it will cleanup the input field."""
        self.page.close(self._sheet)

    async def _on_dismiss_sheet(self, e=None):
        assert not await self._content_lock.aacqurie(blocking=False)
        if self._sheet_input_field:
            await self._sheet_input_field.cleanup()
            self._clean_sheet()
        self.update()
        await self._content_lock.arelease()

        logger.debug(f"Page overlay after dismiss sheet: {self.page.overlay}")
        logger.debug(f"Listview after dismiss sheet: {self._saved_field_list}")

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
    def sub_input_fields(self) -> Iterable["BaseInputField"]:
        return []


# Defined outside for TypeAdapter convenient
class _DictInputFieldSavedField(ListInputField._SavedField):

    def __init__(
        self,
        input_field: BaseInputField,
        dict_input_field: "DictInputField",
        *,
        field_key: str,  # new compare to ListInputField
        **kwargs,
    ):
        super().__init__(input_field, dict_input_field, **kwargs)
        self._key = ft.Text(
            value=field_key, weight=ft.FontWeight.BOLD, color=ft.Colors.RED
        )
        self.controls.insert(0, self._key)

    @property
    def field_key(self):
        return self._key.value

    @field_key.setter
    def field_key(self, v: str):
        self._key.value = v


class _SyncListViewObject(SyncListObject):
    object_adapter = TypeAdapter(ft.ListView, config=arbitrary_types_allowed_config)
    adapter = TypeAdapter(
        _DictInputFieldSavedField, config=arbitrary_types_allowed_config
    )
    list_attr = "controls"


class DictInputField(ListInputField):

    class _SavedFieldSyncList(SyncList):
        field_keys: list[str]
        saved_fields: _SyncListViewObject

    def __init__(self, input_field_factory: InputFieldFactory, **kwargs):

        super().__init__(input_field_factory, **kwargs)

        self._listview = ft.ListView(controls=[], height=250, width=320)
        """Control of this ListView is _DictInputFieldSavedField object, should access through _saved_field_list"""

        # Override ListInputField
        self._saved_field_sync_list = DictInputField._SavedFieldSyncList(
            field_keys=[],
            saved_fields=_SyncListViewObject(object=self._listview),
        )

        content = ft.Column(
            [
                self._listview,
                ft.Row([self._add_new_button, self._remove_all_button]),
            ]
        )
        self.content = content

        self._sheet_index_field = ft.TextField(label="Key", max_length=20)

    @property
    def _saved_field_list(self) -> _SavedFieldSyncList:
        return self._saved_field_sync_list

    async def _add_field(self, field: _DictInputFieldSavedField):
        # Remove and clean up available key if exists.
        if (k := field.field_key) in self._saved_field_list.field_keys:
            current_saved_field = self._saved_field_list.get_values_by_value(
                "field_keys", k
            )["saved_fields"]
            assert isinstance(current_saved_field, _DictInputFieldSavedField)
            await self._remove_field(current_saved_field)

        self._saved_field_list.append(field_keys=k, saved_fields=field)

    async def _remove_field(self, field: _DictInputFieldSavedField):
        """Clean up field and remove"""
        await field.input_field.cleanup()
        self._saved_field_list.remove(field_keys=field.field_key)

    @classmethod
    def is_valid_key(cls, key: str):
        if isinstance(key, str) and key != "":
            return True
        return False

    async def get_assistant_data(
        self, **kwargs
    ) -> dict[str, AssistantDataType_U | List[AssistantDataType_U]] | None:
        async with self._content_lock:
            r = {}
            for f in self._saved_field_list.get_list("saved_fields"):
                assert isinstance(f, _DictInputFieldSavedField)
                data = await f.input_field.get_assistant_data()
                if data is not None:
                    r[f.field_key] = data
                else:
                    logger.warning(
                        f"Unexpected behavior, should only save the valid input put field. Detect the field {f.input_field.__class__} "
                        f"in list but 'get_assistant_data return None'. "
                    )
        r = None if r == {} else r
        return r

    async def _on_open_edit_sheet(
        self, e, *, current_saved_field: _DictInputFieldSavedField
    ):
        # Almost like the base class with slightly change.
        await self._content_lock.aacqurie()  # Lock until dismiss
        try:
            self._sheet_input_field = await self._input_field_factory.factory(
                *self._input_field_factory.args, **self._input_field_factory.kwargs
            )
            self._sheet_index_field.value = current_saved_field.field_key
            self._sheet_content = ft.Column(
                [
                    self._sheet_index_field,
                    self._sheet_input_field,
                    ft.Button(
                        "Update",
                        on_click=partial(
                            self._on_save_edit_sheet,
                            current_saved_field=current_saved_field,  # change this
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
        async with self._save_sheet_cm() as (key, input_field):
            if valid_key := self.is_valid_key(key) and isinstance(
                input_field, BaseInputField
            ):
                await self._add_field(
                    _DictInputFieldSavedField(input_field, self, field_key=key)
                )
                self._clean_sheet()
                self._close_sheet()
                self.notice_user("Saved")
            else:
                if not valid_key:
                    self.notice_user(
                        f"Cannot save. The key '{key}' is not the valid one."
                    )
                else:
                    self.notice_user("Cannot save. Input is wrong.")

    async def _on_save_edit_sheet(
        self, e, *, current_saved_field: _DictInputFieldSavedField
    ):
        update = []
        async with self._save_sheet_cm() as (key, input_field):
            if key != current_saved_field.field_key:
                if self.is_valid_key(key):
                    update.append("key")
                else:
                    self.notice_user(f"Cannot update. Key {key } is not a valid name. ")
                    return

                # Key belong to another saved field. Not support edit one field to override others. Use new instead.
                if key in self._saved_field_list.field_keys:
                    self.notice_user(
                        f"Cannot Update. Key {key} already exists in another data field."
                    )
                    return

            if isinstance(input_field, BaseInputField):
                update.append("field")

            if len(update) > 0:
                if len(update) == 2:
                    await self._remove_field(current_saved_field)
                    assert key not in self._saved_field_list.field_keys
                    await self._add_field(
                        _DictInputFieldSavedField(input_field, self, field_key=key)
                    )

                elif update[0] == "field":
                    await self._add_field(
                        _DictInputFieldSavedField(
                            input_field, self, field_key=current_saved_field.field_key
                        )
                    )

                elif update[0] == "key":
                    # Thread safe change key, does not need to hard update and clean up.
                    with self._saved_field_list._lock:
                        idx = self._saved_field_list.field_keys.index(
                            current_saved_field.field_key
                        )
                        self._saved_field_list.field_keys[idx] = key
                        current_saved_field.field_key = key

                self._clean_sheet()
                self._close_sheet()
                self.notice_user(f"Updated new {" and ".join(update)}.")

            else:
                self.notice_user(
                    "Cannot Update, the input is wrong or key not change. Still hold the current one."
                )

    async def _on_remove_saved_field(
        self,
        e=None,
        *,
        current_saved_field: _DictInputFieldSavedField,
        lock: bool = True,
        update: bool = True,
    ):
        assert isinstance(current_saved_field, _DictInputFieldSavedField)
        async with AsyncExitStack() as stack:
            if lock:
                await stack.enter_async_context(self._content_lock)
            await self._remove_field(current_saved_field)  # already cleanup
            if update:
                self.page.update()

    async def _on_remove_all(self, e):
        async with self._content_lock:
            while len(self._saved_field_list.saved_fields.list) > 0:
                await self._on_remove_saved_field(
                    current_saved_field=self._saved_field_list.saved_fields.list[0],
                    lock=False,
                    update=False,
                )
            self.page.update()


class TupleInputField(BaseInputField):

    def __init__(self, input_fields: Sequence[BaseInputField], **kwargs):
        super().__init__(**kwargs)

        self.content = ft.ListView(list(input_fields))

    @property
    def input_fields(self) -> list[BaseInputField]:
        return self.content.controls

    async def get_assistant_data(
        self, **kwargs
    ) -> tuple[AssistantDataType_U | List[AssistantDataType_U]] | None:
        """Return tuple of all field data, or None if there is one that's lack of data."""
        l = []
        for field in self.input_fields:
            if (data := await field.get_assistant_data()) is None:
                return None
            l.append(data)
        return tuple(l)

    async def _refresh(self):
        pass

    @property
    def sub_input_fields(self) -> Iterable["BaseInputField"]:
        return self.input_fields


class InputFieldInfo(BaseModel):
    model_config = arbitrary_types_allowed_config
    input_field: BaseInputField
    description: str | None = None


class SchemaInputField(BaseInputField):
    """Input field for key-value, where key and typehint of them are fix. This class act like pydantic model or TypeDict,
    not allow to add more like DictInputField or normal dict.
    """

    def __init__(self, schema: dict[str, InputFieldInfo], **kwargs):
        """
        Args:
            schema: keys are field name
            **kwargs:
        """
        panels = []
        for field_name, field_info in schema.items():
            panels.append(
                ft.ExpansionPanel(
                    header=ft.Text(field_name),
                    can_tap_header=True,
                    content=ft.Column(
                        [ft.Text(field_info.description), field_info.input_field]
                    ),
                )
            )

        panel_list = ft.ListView(
            [ft.ExpansionPanelList(panels)]
        )  # wrap to listview to scroll

        self._lock= UniversalLock()

        super().__init__(content=panel_list, **kwargs)

    @property
    def sub_input_fields(self) -> Iterable["BaseInputField"]:
        """
        Look at the ExpansionPanel creation for more details.
        Returns:
            Generator object instead of list for lazy access.
        """
        def _r():
            for panel in self._iter_panels():
                yield panel.content.controls[1]
        return _r()

    @property
    def iter_input_fields(self) -> Generator[tuple[str, "BaseInputField"], None, None]:
        def _r():
            for panel in self._iter_panels():
                yield panel.header.value, panel.content.controls[1]
        return _r()

    def _iter_panels(self)->Generator[ft.ExpansionPanel,None,None]:
        with self._lock:
            for c in self.content.controls[0].controls: # Look the layout for more details
                assert isinstance(c, ft.ExpansionPanel)
                yield c

    async def get_assistant_data(
        self, include_none: bool = True, **kwargs
    ) -> dict[str, AssistantDataType_U | List[AssistantDataType_U] | None] | None:
        """This output of this method is intentionally to be used to construct AssistantDataInput object.

        Args:
            include_none: If this is True, always return a dict. Else if return None if any values is None.
            **kwargs:
        Returns:
            A dict with keys are field name and AssistantDataType object as values
        """
        r = {}
        for field_name, input_field in self.iter_input_fields:
            if (
                data := await input_field.get_assistant_data()
            ) is None and not include_none:
                return None
            r[field_name] = data

        return r

    async def _refresh(self):
        pass


### Note: Belows are not BaseInputField


class _ChatInputFieldSyncStackObject(SyncListObject):
    object_adapter = TypeAdapter(ft.Stack, config=arbitrary_types_allowed_config)
    adapter = TypeAdapter(ft.ExpansionTile, config=arbitrary_types_allowed_config)
    list_attr = "controls"


class _ChatInputFieldSyncDropdownObject(SyncListObject):
    object_adapter = TypeAdapter(ft.Dropdown, config=arbitrary_types_allowed_config)
    adapter = TypeAdapter(ft.DropdownOption, config=arbitrary_types_allowed_config)
    list_attr = "options"


class ChatInputField(ft.Container):

    class _StackSyncList(SyncList):
        input_fields: _ChatInputFieldSyncStackObject
        """Accept ft.ExpansionTile"""
        dropdowns: _ChatInputFieldSyncDropdownObject
        """Accept ft.DropdownOption"""

        assistant_names: list[str]

        current_assistant: str | None = None

    def __init__(
        self,
        assistant_apps: dict[str, AssistantApp],
        *,
        username: str,
        user_id: UUID,
        **kwargs,
    ):
        """Parse assistant input to input field.
        Args:
            assistant_apps: get from ChatAssistantSVC.assistant_names
            **kwargs:
        """
        assert len(assistant_apps)>0
        self._apps = assistant_apps
        self._username = username
        self._user_id = user_id
        self._dropdown = ft.Dropdown(
            label="Assistant options", options=[], on_change=self._on_change
        )
        self._stack = ft.Stack([])
        self._stack_lock = UniversalLock()

        self._stack_sync_list = ChatInputField._StackSyncList(
            input_fields=_ChatInputFieldSyncStackObject(object=self._stack),
            dropdowns=_ChatInputFieldSyncDropdownObject(object=self._dropdown),
            assistant_names=[],
        )
        """list keys: input_fields (ft.ExpansionTile), dropdowns (ft.DropdownOption)"""

        with self._stack_lock:
            for name, app in self._apps.items():
                self._add_assistant(name, app.schema, app.description, lock=False)
            # self._dropdown.value = self._stack_sync_list.assistant_names[0]
            # self._current_assistant =
        super().__init__(**kwargs)
        self.content = ft.ListView([self._dropdown, self._stack])

    async def get_input_data(
        self, raise_if_validate_fail: bool = False
    ) -> tuple[str, AssistantInputData] | None:
        """
        Args:
            raise_if_validate_fail: If False, return None if validate fail.
        Returns:
            tuple of assistant name (name that shown to user, not app name) and validated AssistantInputData of current open assistant.
        """
        async with self._stack_lock:
            if (name:= self._current_assistant) is None:
                return None
            data = await self._get_input_field(name).get_assistant_data()
            try:
                return self._apps[name].schema.model_validate(data)
            except ValidationError as e:
                if raise_if_validate_fail:
                    raise
                return None

    @property
    def _current_assistant(self):
        return self._stack_sync_list.current_assistant

    @_current_assistant.setter
    def _current_assistant(self, v: str | None):
        self._stack_sync_list.current_assistant = v

    async def _on_change(self, e):
        async with self._stack_lock:
            if self._current_assistant is not None:
                await self._disable_assistant(self._current_assistant, lock=False)
                self._current_assistant = None

            ex = self._get_expansion(self._dropdown.value)
            ex.disabled=False
            ex.visible = True
            self._get_input_field(expansion=ex).enable()
            self._current_assistant = self._dropdown.value
            self.page.update()

    def _get_expansion(self, assistant_name)->ft.ExpansionTile:
        expansion = self._stack_sync_list.get_values_by_value(
            "assistant_names", assistant_name, ["input_fields"]
        )["input_fields"]
        assert isinstance(expansion, ft.ExpansionTile)
        return expansion

    def _get_input_field(self, assistant_name: str=None,*,expansion:ft.ExpansionTile = None) -> SchemaInputField:
        """
        This method is change definition depend on the layout, so this act as interface, along with _get_expansion.
        Args:
            assistant_name:
            expansion:
        Returns:
            SchemaInputField
        """
        assert assistant_name is not None or expansion is not None
        if assistant_name:
            expansion = self._get_expansion(assistant_name)
        input_field = expansion.controls[0] # see _add_assistant" for details about expansion structure.
        assert isinstance(input_field, SchemaInputField)
        return input_field

    async def add_assistant(
        self,
        assistant_name: str,
        datatype: type[AssistantInputData],
        description: str = None,
    ):
        """Add new assistant, override the old one.
        Args:
            assistant_name: Name of assistant for user to select, add new assistant with the same name will override the old.
            datatype: Subclass of AssistantInputData
            description: assistant description
        """
        async with self._stack_lock:
            await asyncio.to_thread(
                self._add_assistant, assistant_name, datatype, description, lock=False
            )
            self.page.update()

    def _add_assistant(
        self,
        assistant_name: str,
        datatype: type[AssistantInputData],
        description: str = None,
        *,
        lock: bool = True,
    ):
        if assistant_name in self._stack_sync_list.assistant_names:
            raise ValueError(
                f"Assistant {assistant_name} already exists. Remove first before add."
            )
        with ExitStack() as stack:
            if lock:
                stack.enter_context(self._stack_lock)
            schema = {}
            for field_name, field_info in datatype.iter_data_fields():
                schema[field_name] = InputFieldInfo(
                    input_field=self._parse_ann(field_info.annotation),
                    description=field_info.description,
                )
            schema_field = SchemaInputField(schema).disable()

            ex_title = ft.ExpansionTile(
                title=ft.Text(assistant_name),
                subtitle=ft.Text(description),
                controls=[schema_field],
                disabled=True,
                visible=False
            )
            self._stack_sync_list.append(
                input_fields=ex_title,
                dropdowns=ft.DropdownOption(assistant_name),
                assistant_names=assistant_name,
            )

    async def remove_assistant(self, assistant_name: str):
        async with self._stack_lock:
            await self._disable_assistant(assistant_name, lock=False)
            await asyncio.to_thread(
                self._stack_sync_list.remove, assistant_names=assistant_name
            )
            self.page.update()

    async def _disable_assistant(self, assistant_name: str, *, lock: bool = True):
        """Disable and cleanup assistant"""
        async with AsyncExitStack() as stack:
            if lock:
                await stack.enter_async_context(self._stack_lock)
            ex = self._get_expansion(assistant_name)
            ex.visible = False
            ex.disabled = True
            await self._get_input_field(expansion=ex).disable().cleanup()
            self.page.update()

    def _parse_ann(self, ann: type) -> BaseInputField | None:
        """Parse annotation recursively."""

        if ann is None:
            raise ValueError("Does not support standalone 'None' typehint.")
        org = get_origin(ann)

        if org == Annotated:
            return self._parse_ann(get_args(ann)[0])

        if org == UnionType:
            opt = {}
            i = 1
            for arg in get_args(ann):
                if input_fields := self._parse_ann(arg):
                    opt[f"Form {i}"] = InputFieldOption(input_field=input_fields)
                    i += 1
            return MultiOptionsInputField(opt)

        if org == list:
            # Special case for pick multiple files. When definition is list[ImageObject] or something like that
            # Note that not list[ImageObject|VideoObject]. Multiple files picker only pick one media type.

            arg = get_args(ann)[0]  # list only have one arg
            if isclass(arg):
                if issubclass(arg, MediaObject):
                    return MediaInputField(
                        self._username, self._user_id, arg, allow_multiple=True
                    )

            return ListInputField(
                input_field_factory=InputFieldFactory(
                    factory=self._parse_ann, args=(get_args(ann)[0],)
                )
            )

        if org == dict:
            key_ann, value_ann = get_args(ann)
            assert key_ann == str
            return DictInputField(
                input_field_factory=InputFieldFactory(
                    factory=self._parse_ann, args=(value_ann,)
                )
            )

        if org == tuple:
            l = []
            for arg in get_args(ann):
                if input_fields := self._parse_ann(arg):
                    l.append(input_fields)
            assert len(l) > 0
            return TupleInputField(l)

        if org is None:
            if ann == NoneType:
                return None

            if issubclass(ann, Text):
                return TextInputField(ann)

            if issubclass(ann, BaseSelection):
                return SelectionInputField(ann)

            if issubclass(ann, MediaObject):
                return MediaInputField(
                    self._username, self._user_id, ann, allow_multiple=False
                )

        # Note expect to raise
        m = (
            f"Cannot parse assistant input annotation {ann}. This is app error, not user or dev."
            f"AssistantInputData interface must check for this. This error should not be catch."
        )
        logger.warning(m)
        raise ValueError(m)


for ta in ChatInputField._StackSyncList.adapters.values():
    ta.rebuild()


class ChatOutputField(ft.Container):
    """
    chat message,...
    """


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
        dict_input_field = DictInputField(
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

        option = MultiOptionsInputField(
            dict(
                list_input=InputFieldOption(
                    input_field=list_input_field, description="this is list input field"
                ),
                dict_input=InputFieldOption(
                    input_field=dict_input_field, description="this is dict input field"
                ),
            )
        )

        text = ft.Text()
        page.add(option, text)

        async def on_click(e):
            if data := (await option.get_assistant_data(return_meta=True)):
                key = data[0]
                if isinstance(data[1], list):
                    data = "\n".join(repr(data[1]))
                if isinstance(data[1], dict):
                    pprint.pformat(data[1], indent=4)

            text.value = data or "NOTHING"
            page.update()

        page.add(ft.Button("Select all file", on_click=on_click))

    app = ft.app(main, export_asgi_app=True)
    import uvicorn

    uvicorn.run(app, port=5555)
