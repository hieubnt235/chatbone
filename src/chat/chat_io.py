import asyncio
import itertools
import time
from abc import ABC, abstractmethod
from bisect import bisect_left
from contextlib import AsyncExitStack, asynccontextmanager, ExitStack
from copy import deepcopy
from datetime import timedelta, datetime, timezone
from enum import Enum
from functools import partial
from inspect import iscoroutinefunction, isclass
from math import floor
from pprint import pformat
from types import NoneType, UnionType
from typing import Any, List, Optional, Tuple, Union, Unpack
from typing import (
    Callable,
    get_origin,
    Annotated,
    Self,
    Awaitable,
    AsyncIterator,
    get_args,
    Sequence,
    Iterable,
    Generator,
    TypedDict,
)
from uuid import UUID

import anyio
import flet as ft
from anyio.streams.memory import MemoryObjectSendStream, MemoryObjectReceiveStream
from flet.core.animation import AnimationValue
from flet.core.badge import BadgeValue
from flet.core.blur import Blur
from flet.core.box import (
    BoxShadow,
)
from flet.core.buttons import RoundedRectangleBorder
from flet.core.container import ContainerTapEvent
from flet.core.control import OptionalNumber
from flet.core.file_picker import (
    FilePickerResultEvent,
    FilePickerUploadEvent,
    FilePickerFile,
)
from flet.core.gradients import Gradient
from flet.core.tooltip import TooltipValue
from flet.core.types import (
    OptionalControlEventCallable,
    OptionalEventCallable,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    TypeAdapter,
    field_validator,
    Field,
    ValidationError,
)

from chatbone.src.assistant_interface import (
    AssistantDataType_U,
    AnyMediaObject,
    MediaObject,
    InvalidFileExtension,
    InvalidBinaryFile,
    AssistantInputData,
    Text,
    Selection,
    AssistantOutputData,
    AssistantStatusCode,
)
from chatbone.src.broker import DisplayMessage, DisplayableMessage
from chatbone.src.chat.svc import AssistantApp
from utilities.src.utilities.func import utc_now
from utilities.src.utilities.logger import logger
from utilities.src.utilities.misc import UniversalLock, SyncList, SyncListObject

arbitrary_types_allowed_config = ConfigDict(arbitrary_types_allowed=True)


class ContainerArgs(TypedDict):
    padding: Optional[ft.PaddingValue]
    margin: Optional[ft.MarginValue]
    alignment: Optional[ft.Alignment]
    bgcolor: Optional[ft.ColorValue]
    gradient: Optional[Gradient]
    blend_mode: Optional[ft.BlendMode]
    border: Optional[ft.Border]
    border_radius: Optional[ft.BorderRadiusValue]
    shape: Optional[ft.BoxShape]
    clip_behavior: Optional[ft.ClipBehavior]
    ink: Optional[bool]
    image: Optional[ft.DecorationImage]
    ink_color: Optional[ft.ColorValue]
    animate: Optional[AnimationValue]
    blur: Union[None, float, int, Tuple[Union[float, int], Union[float, int]], Blur]
    shadow: Union[None, BoxShadow, List[BoxShadow]]
    url: Optional[str]
    url_target: Optional[ft.UrlTarget]
    theme: Optional[ft.Theme]
    dark_theme: Optional[ft.Theme]
    theme_mode: Optional[ft.ThemeMode]
    color_filter: Optional[ft.ColorFilter]
    ignore_interactions: Optional[bool]
    foreground_decoration: Optional[ft.BoxDecoration]
    on_click: OptionalControlEventCallable
    on_tap_down: OptionalEventCallable["ContainerTapEvent"]
    on_long_press: OptionalControlEventCallable
    on_hover: OptionalControlEventCallable
    #
    # ConstrainedControl and AdaptiveControl
    #
    ref: Optional[ft.Ref]
    key: Optional[str]
    width: OptionalNumber
    height: OptionalNumber
    left: OptionalNumber
    top: OptionalNumber
    right: OptionalNumber
    bottom: OptionalNumber
    expand: Union[None, bool, int]
    expand_loose: Optional[bool]
    col: Optional[ft.ResponsiveNumber]
    opacity: OptionalNumber
    rotate: Optional[ft.RotateValue]
    scale: Optional[ft.ScaleValue]
    offset: Optional[ft.OffsetValue]
    aspect_ratio: OptionalNumber
    animate_opacity: Optional[AnimationValue]
    animate_size: Optional[AnimationValue]
    animate_position: Optional[AnimationValue]
    animate_rotation: Optional[AnimationValue]
    animate_scale: Optional[AnimationValue]
    animate_offset: Optional[AnimationValue]
    on_animation_end: OptionalControlEventCallable
    tooltip: Optional[TooltipValue]
    badge: Optional[BadgeValue]
    visible: Optional[bool]
    disabled: Optional[bool]
    data: Any
    rtl: Optional[bool]
    adaptive: Optional[bool]


class BaseInputField(ABC, ft.Container):

    def __init__(self, *args, **kwargs: Unpack[ContainerArgs]):
        self._able_lock = UniversalLock()

        self._snackbar: ft.SnackBar | None = None
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
        Should not implement logic for sub InputField, which will be done by cleanup() method instead.
        """
        pass

    @property
    @abstractmethod
    def sub_input_fields(self) -> Iterable["BaseInputField"]:
        """This property return sub input fields (not self), used to do cleanup.
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


# noinspection PyTypeChecker
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
            self.media_object: AnyMediaObject | None = None

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
        **kwargs: Unpack[ContainerArgs],
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
        kwargs["border"] = ft.border.all(1)
        super().__init__(column, **kwargs)

        self._button_state_lock = UniversalLock()

    async def get_assistant_data(
        self, **kwargs
    ) -> AssistantDataType_U | List[AssistantDataType_U] | None:
        """
        Returns:
            If allow_multiple, return a list of MediaObject else return only one MediaObject if files exist. or None.
        """
        if not self._allow_multiple:
            assert len(self._file_names) <= 1
            data = (
                (await self.get_file_preview_row(self._file_names[0])).media_object
                if len(self._file_names) == 1
                else None
            )
            if data:
                await self.save()
                return data
            else:
                return None

        async with self._file_index_lock:
            if not self._file_names:
                return None
            else:
                data = [
                    f.media_object
                    for f in self._file_list.controls
                    if isinstance(f, MediaInputField._FilePreviewRow)
                    and f.media_object is not None
                ]
                if data:
                    await self.save()
                    return data
                else:
                    return None

    async def save(self):
        """Save all current choosen files, marked so that unselect not delete file in storage.
        This method should call after success response to persist data.
        """
        await self._unselect_all(cancel=False)

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

    async def _unselect_all(self, e=None, *, cancel=True):
        async with self._file_index_lock:
            for filename in deepcopy(self._file_names):
                await self._unselect(filename, cancel=cancel, update=False, lock=False)
            self.page.update()

    async def _unselect(
        self, filename, *, cancel: bool = True, update: bool = True, lock: bool = True
    ):
        should_lock = lock
        async with AsyncExitStack() as stack:
            if lock:
                await stack.enter_async_context(self._file_index_lock)
                should_lock = False
        if cancel:
            await self._file_picker.cancel(filename)
        await self.remove_file_review_row(filename, should_lock)
        logger.debug(f"Unselect file with cancel={cancel}, num files now: {self._file_names}.")
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
    def __init__(self, text_type: type[Text], **kwargs: Unpack[ContainerArgs]):
        self._text_type = text_type
        self._textfield = ft.TextField(
            input_filter=text_type.input_filter, on_change=self._on_change
        )
        self._notice_text = ft.Text(value=self._textfield.value)

        column = ft.Column([self._textfield, self._notice_text])
        super().__init__(column, **kwargs)

    async def _on_change(self, e):
        val = await self._validate()
        if val is None:
            self._notice_text.value = "Invalid input"
        else:
            self._notice_text.value = None
        self.page.update(self._textfield, self._notice_text)

    async def _validate(self):
        try:
            if iscoroutinefunction(self._text_type.input_validator):
                val = await self._text_type.input_validator(self.value)
            else:
                val = await asyncio.to_thread(
                    self._text_type.input_validator, self.value
                )
            if val is None:
                return None
            return str(val)
        except Exception as e:
            logger.warning(e)
            return None

    @property
    def value(self) -> str | None:
        return self._textfield.value

    @value.setter
    def value(self, v: str | None):
        self._textfield.value = v

    async def get_assistant_data(
        self, **kwargs
    ) -> AssistantDataType_U | List[AssistantDataType_U] | None:
        r = self._text_type(role="user", content=self.value) if self.value else None
        if r:
            self.value= None
            self._textfield.value = None
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

    def __init__(
        self, selection_type: type[Selection], **kwargs: Unpack[ContainerArgs]
    ):
        """
        Args:
            options: dict with keys are option keys, values is the description.
            **kwargs:
        """
        assert selection_type.options is not None
        self._selection_type = selection_type
        
        self._dd = ft.Dropdown(
            options=[ft.DropdownOption(key=k) for k in selection_type.options.keys()]
        )

        self._desc = ft.Text(f"Hint:{pformat(selection_type.options)}:{selection_type.__doc__}")

        content = ft.Column([self._dd, self._desc])

        super().__init__(content, **kwargs)

    async def get_assistant_data(
        self, **kwargs
    ) -> AssistantDataType_U | List[AssistantDataType_U] | None:
        if (v := self._dd.value) is None:
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
        self,
        input_field_options: dict[str, InputFieldOption],
        **kwargs: Unpack[ContainerArgs],
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

        super().__init__(content, **kwargs)

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
        self, return_meta: bool = False, c: AssistantDataType_U = None
    ) -> (
        AssistantDataType_U
        | list[AssistantDataType_U]
        | None
        | tuple[str, AssistantDataType_U | list[AssistantDataType_U] | None]
    ):
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


# noinspection PyTypeChecker
class ListInputField(BaseInputField):

    class _SavedField(ft.Row):
        def __init__(
            self,
            input_field: BaseInputField,
            list_input_field: "ListInputField",
            **kwargs: Unpack[ContainerArgs],
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
        if not iscoroutinefunction(input_field_factory.factory):
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
        try:
            await self._content_lock.aacqurie()  # Lock until dismiss
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
            if await self._content_lock.alocked:
                await self._content_lock.arelease()
            logger.exception(e)
            self._close_sheet()
            self.notice_user("Server error when open input sheet.")

    async def _on_open_edit_sheet(self, e, *, current_saved_field: _SavedField):
        try:
            await self._content_lock.aacqurie()  # Lock until dismiss
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
            if await self._content_lock.alocked:
                await self._content_lock.arelease()
            logger.exception(e)
            self._close_sheet()
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
        assert (await self._content_lock.alocked) and (
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
        """IMPORTANT: This method MUST be called before close sheet if you don't want to clean input field ( for success case).
        And MUST NOT be called for case when input field is expected to clean (ex: close sheet without saving intentionally).
         See _on_dismiss_sheet for details."""
        self._sheet_input_field = None
        self._sheet_index_field.value = None
        self._sheet_content = None

    def _close_sheet(self):
        """The on_dismiss_sheet will be called after this method.
        Note that if not _clean_sheet first, it will clean up the input field."""
        self.page.close(self._sheet)

    async def _on_dismiss_sheet(self, e=None):
        assert (
            await self._content_lock.alocked
        )  # lock must be aquired when sheet open, so when dismiss, must be locked.
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

    async def _on_remove_all(self, e=None):
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
        """
        Notes:
            Because _refresh already cleanup all sub input fields, so do not need the sub_input_field attribute.
            See Also: self.cleanup()
        """
        await self._on_remove_all()

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

    def __init__(
        self, input_field_factory: InputFieldFactory, **kwargs: Unpack[ContainerArgs]
    ):

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
        try:
            await self._content_lock.aacqurie()  # Lock until dismiss
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
            if await self._content_lock.alocked:
                await self._content_lock.arelease()
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

    async def _on_remove_all(self, e=None):
        async with self._content_lock:
            while len(self._saved_field_list.saved_fields.list) > 0:
                await self._on_remove_saved_field(
                    current_saved_field=self._saved_field_list.saved_fields.list[0],
                    lock=False,
                    update=False,
                )
            self.page.update()


class TupleInputField(BaseInputField):

    def __init__(
        self, input_fields: Sequence[BaseInputField], **kwargs: Unpack[ContainerArgs]
    ):
        super().__init__(**kwargs)

        self.content = ft.ListView(list(input_fields))

    @property
    def input_fields(self) -> list[BaseInputField]:
        return self.content.controls

    async def get_assistant_data(
        self, **kwargs
    ) -> tuple[AssistantDataType_U | List[AssistantDataType_U], ...] | None:
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

    def __init__(
        self, schema: dict[str, InputFieldInfo], **kwargs: Unpack[ContainerArgs]
    ):
        """
        Args:
            schema: keys are field name
            **kwargs:
        """
        self._panels = []
        for field_name, field_info in schema.items():
            self._panels.append(
                ft.ExpansionPanel(
                    header=ft.Text(field_name),
                    can_tap_header=True,
                    content=ft.Column(
                        [ft.Text(field_info.description), field_info.input_field]
                    ),
                )
            )

        # panel_list = ft.ListView(
        #     []
        # )  # wrap to listview to scroll

        self._lock = UniversalLock()

        super().__init__(content=ft.ExpansionPanelList(self._panels), **kwargs)

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

    def _iter_panels(self) -> Generator[ft.ExpansionPanel, None, None]:
        with self._lock:
            for c in self._panels:
                assert isinstance(c, ft.ExpansionPanel)
                yield c

    async def get_assistant_data(
        self, include_none: bool = True, **kwargs
    ) -> dict[str, AssistantDataType_U | List[AssistantDataType_U] | None] | None:
        """This output of this method is intentionally to be used to construct AssistantDataInput object.

        Args:
            include_none: If this is True, always return a dict. Else it will return None when any value is None.
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


class UserInputData(BaseModel):
    assistant_name: str | None = None
    data: AssistantInputData | None = None


class ChatInputField(ft.Container):
    """
    from uuid import UUID

    from pydantic import Field

    import flet as ft
    from chatbone.assistant_interface import (
        AssistantInputData,
        ImageObject,
        VideoObject,
        Text,
        BaseSelection,
        DocumentObject,
    )
    from chatbone.chat.chat_io import ChatInputField
    from chatbone.chat.svc import AssistantApp
    from utilities.logger import logger


    class Selection(BaseSelection):
        options = {"opt 1": "this is option 1", "opt 2": "this is option 2"}


    class LimitText(Text):
        validator = lambda v: v if len(v) < 10 else None


    class DataInput(AssistantInputData):
        image: VideoObject | list[ImageObject] | None
        texts: list[LimitText] | dict[str, Selection] = Field(
            description="texts description"
        )
        select: Selection


    async def main(page: ft.Page):
        uid = "0197a813-57b5-7dfa-aad4-7d36a58a62e7"
        input_field = ChatInputField(
            assistant_apps=dict(
                dummy=AssistantApp(
                    schema=DataInput, description="This is dummy", app_name="dummy app"
                )
            ),
            username="hieu",
            user_id=UUID(uid),
            width=500,
            height=500,
        )
        text = ft.Text()

        async def on_click(e):
            data = await input_field.get_input_data()
            if data:
                text.value = f"{repr(data)}"
            else:
                text.value = "NOTHING"
            page.update()

        button = ft.Button("select", on_click=on_click)
        page.add(button, ft.Divider(thickness=5), input_field, text)


    ft.app(main, view=ft.AppView.WEB_BROWSER)

    """

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
        send_button: ft.Control | None = None,
        **kwargs: Unpack[ContainerArgs],
    ):
        """Parse assistant input to input field.
        Args:
            assistant_apps: get from ChatAssistantSVC.assistant_names
            **kwargs:
        """
        assert isinstance(assistant_apps, dict)

        self._apps = assistant_apps
        self._username = username
        self._user_id = user_id
        self._send_button = send_button
        self._dropdown = ft.Dropdown(
            label="Assistant options",
            options=[],
            on_change=self._on_change,
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
                self._add_assistant(name, app.input_schema, app.description, lock=False)
            # self._dropdown.value = self._stack_sync_list.assistant_names[0]
            # self._current_assistant =

        super().__init__(**kwargs)
        self.content = ft.Column(
            [
                ft.ListView([self._stack], expand=True),
                ft.Divider(height=1, color=ft.Colors.BLUE, thickness=1),
                (
                    ft.Row(
                        [self._dropdown, self._send_button],
                        alignment=ft.MainAxisAlignment.END,
                    )
                    if self._send_button
                    else self._dropdown
                ),
            ],
        )

    def build(self):
        self._dropdown.width = self.page.width * 0.2

    async def get_input_data(
        self, raise_if_validate_fail: bool = False
    ) -> UserInputData:
        """todo: support validate with default (change all input fields to receive default data. and parser inject that.)
        Args:
            raise_if_validate_fail: If False, return None if validate fail.
        Returns:
            UserInputData.
        """
        async with self._stack_lock:
            if (name := self._current_assistant) is None:
                return UserInputData()
            try:
                data = await self._get_input_field(name).get_assistant_data()
                logger.debug(f"get_input_data got: {repr(data)}")
                data = self._apps[name].input_schema.model_validate(data)
                data._username = self._username

                return UserInputData(
                    assistant_name=name,
                    data=data,
                )
            except ValidationError as e:
                
                logger.info(f"Error when get_input_data: {e}")
                if raise_if_validate_fail:
                    raise
                return UserInputData(assistant_name=name)

    @property
    def _current_assistant(self):
        return self._stack_sync_list.current_assistant

    @_current_assistant.setter
    def _current_assistant(self, v: str | None):
        self._stack_sync_list.current_assistant = v

    async def _on_change(self, e):
        async with self._stack_lock:
            if self._current_assistant is not None:
                await self._disable_assistant(
                    self._current_assistant, lock=False, update=False
                )
                self._current_assistant = None

            ex = self._get_expansion(self._dropdown.value)
            ex.disabled = False
            ex.visible = True
            self._get_input_field(expansion=ex).enable()
            self._current_assistant = self._dropdown.value
            self.page.update()

    def _get_expansion(self, assistant_name) -> ft.ExpansionTile:
        expansion = self._stack_sync_list.get_values_by_value(
            "assistant_names", assistant_name, ["input_fields"]
        )["input_fields"]
        assert isinstance(expansion, ft.ExpansionTile)
        return expansion

    def _get_input_field(
        self, assistant_name: str = None, *, expansion: ft.ExpansionTile = None
    ) -> SchemaInputField:
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
        input_field = expansion.controls[
            0
        ]  # see _add_assistant" for details about expansion structure.
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
                title=ft.Text("Input form"),
                subtitle=ft.Text(description),
                controls=[schema_field],
                disabled=True,
                visible=False,
            )
            self._stack_sync_list.append(
                input_fields=ex_title,
                dropdowns=ft.DropdownOption(assistant_name),
                assistant_names=assistant_name,
            )

    async def cleanup(self):
        """clean all pending input fields"""
        async with self._stack_lock:
            for name in self._stack_sync_list.assistant_names:
                await self._disable_assistant(name, lock=False, update=False)
            self.page.update()
            logger.info("ChatInputField cleaned up.")

    async def remove_assistant(
        self, assistant_name: str, *, lock: bool = True, update: bool = True
    ):
        async with AsyncExitStack() as stack:
            if lock:
                await stack.enter_async_context(self._stack_lock)
                lock = False
            await self._disable_assistant(assistant_name, lock=lock, update=False)
            await asyncio.to_thread(
                self._stack_sync_list.remove, assistant_names=assistant_name
            )
            if update:
                self.page.update()

    async def _disable_assistant(
        self, assistant_name: str, *, lock: bool = True, update: bool = True
    ):
        """Disable and cleanup assistant"""
        async with AsyncExitStack() as stack:
            if lock:
                await stack.enter_async_context(self._stack_lock)
            ex = self._get_expansion(assistant_name)
            ex.visible = False
            ex.disabled = True
            await self._get_input_field(expansion=ex).disable().cleanup()
            if update:
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

            if issubclass(ann, Selection):
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


class RequestInputField(ft.Container):
    def __init__(
        self, input_field: ChatInputField, on_send, **kwargs: Unpack[ContainerArgs]
    ):
        super().__init__(**kwargs)
        self.content = ft.Column(
            [input_field, ft.IconButton(ft.Icons.SEND, on_click=on_send)]
        )


class ChatOutputField(ft.Container):
    # todo, rerender this UI

    def __init__(
        self,
        *,
        username: str,
        user_id: UUID,
        cs_uid: UUID,
        cs_base64: str,
        **kwargs: Unpack[ContainerArgs],
    ):

        self._username = username
        self._user_id = user_id
        self._cs_uid = cs_uid
        self._cs_base64 = cs_base64

        self._message_list = ft.ListView([], expand=True)

        self._list_lock = UniversalLock()

        column = ft.Column(
            [ft.Text(f"Chat session id:{self._cs_base64}"), self._message_list]
        )
        super().__init__(content=column, **kwargs)

    # noinspection PyTypeChecker
    @property
    def message_list(self) -> list[ft.ExpansionTile]:
        return self._message_list.controls

    @asynccontextmanager
    async def stream_message(
        self, chat_context_id: UUID
    ) -> AsyncIterator[MemoryObjectSendStream[AssistantOutputData]]:
        # This is not thread safe, only use in this function.

        class TextStream:
            """Below examples show append with list of string give better performance. More longer the string, more perforamce gap
            1166 if j in range 10000. But the append time is always 0.01 for j in range 10000. So dont need to use thread here.

            a = list("" for i in range(5) )
            b = list([] for i in range(5))
            import time
            import itertools
            start = time.time()
            for i in range(5):
                    for j in range(1000):
                            a[i]+="a"*1000
            s="".join(a)
            print(t1:=(time.time()-start))
            start = time.time()
            for i in range(5):
                    for j in range(1000):
                            b[i].append("b"*1000)
            ss="".join(itertools.chain.from_iterable(b))
            print(len(s), len(ss))
            print(t2:=(time.time()-start))
            print(t1/t2)

            # OUTPUT
            0.09939241409301758
            5000000 5000000
            0.0022478103637695312
            44.21743742044973

            """

            logger.debug(
                f"Start streaming message with chat_context_id={chat_context_id}"
            )

            def __init__(self):
                self._text_streams: list[list[str]] = []
                self._stream_place: list[int] = []

            def append_text(self, place: int, value: str) -> int:
                """
                Args:
                    place: place holder of the stream in the message
                    value: value to concat to the stream
                Returns:
                    index of the value in the stream place
                """
                # all values on the left of below index is smaller than place value
                place_idx = bisect_left(self._stream_place, place)
                chunk_idx = None
                # If place already exist, value of that index must be equal to original value.
                try:
                    if self._stream_place[place_idx] == place:
                        self._text_streams[place_idx].append(value)
                        chunk_idx = len(self._text_streams[place_idx]) - 1
                        logger.debug(f"Chunk index: {chunk_idx}")
                        return chunk_idx
                except IndexError:
                    logger.debug(f"No stream place {place}. Create new one.")

                # this code only run when raise IndexError or if block fails.
                self._stream_place.insert(place_idx, place)
                self._text_streams.insert(place_idx, [value])
                logger.debug(f"Chunk index: {0}")
                return 0

            @property
            def text(self):
                return "".join(itertools.chain.from_iterable(self._text_streams))

        send_stream, read_stream = anyio.create_memory_object_stream[
            AssistantOutputData
        ](0)

        async def _push_task(
            read_stream: MemoryObjectReceiveStream[AssistantOutputData],
        ):
            markdown: ft.Markdown | None = None  # For now support only markdown.
            text_stream: TextStream | None = None

            async with read_stream as reader:
                async for data in reader:
                    assert isinstance(data, AssistantOutputData)
                    assert data.chat_context_id == chat_context_id
                    logger.debug(
                        f"Receive data={repr(data)}, chat_context_id={data.chat_context_id}, assistant_name={data.assistant_name}, role = {data.default_role}"
                    )

                    if data.status.code == AssistantStatusCode.ERROR:
                        logger.error(
                            f"There is an error from assistant. {data.status.detail}"
                        )
                        break  # TODO, handle more status code

                    if data.status.code == AssistantStatusCode.PROCESSING:
                        chunk_order = data.chunk_order
                        logger.debug(
                            f"Status code is processing and chunk order={chunk_order}."
                        )
                        display_message = await data.get_display_message()

                        # Override when get display message through stream.
                        display_message.role = "assistant"
                        if display_message.sender is None:
                            display_message.sender = data.assistant_name

                        start = time.time()  # for debug

                        if markdown is None:
                            assert text_stream is None

                            markdown = await self.__push(display_message)
                            assert isinstance(markdown, ft.Markdown)

                            text_stream = TextStream()
                            idx = text_stream.append_text(
                                data.stream_place, display_message.content
                            )
                            assert idx == chunk_order
                        else:
                            idx = text_stream.append_text(
                                data.stream_place, display_message.content
                            )
                            assert idx == chunk_order
                            markdown.value = text_stream.text
                            markdown.update()

                        end = time.time() - start
                        logger.debug(f"Pushed new markdown in {end} seconds.")
                        if end > 0.1:
                            logger.warning(
                                f"Pushing new markdown took {end} more than 0.1 seconds."
                                f" It may seriously block the main thread. Consider to use a new thread."
                            )
            logger.debug("_push_task done.")

        async with self._list_lock:
            t = asyncio.create_task(_push_task(read_stream))
            async with send_stream as sender:
                try:
                    yield sender
                except Exception as e:
                    t.cancel()
                    raise e

    async def push_messages(self, messages: list[DisplayMessage]):
        async with self._list_lock:
            for message in messages:
                logger.debug(f"Trying to push message: {repr(message)}")
                try:
                    m = await message.get_display_message()
                    logger.debug(f"Displayable message {repr(m)}")
                    if isinstance(m, DisplayableMessage):
                        if isinstance(message, AssistantInputData):
                            m.role = "user"
                            m.sender = m.sender or self._username
                        elif isinstance(message, AssistantOutputData):
                            m.role = "assistant"
                            m.sender = m.sender or "Assistant"
                        else:
                            if m.role not in ["user", "assistant"]:
                                logger.warning(
                                    f"Message without role cannot be display. "
                                    f"{repr(m)}"
                                )
                                continue

                        await self.__push(m, update=False)
                    else:
                        logger.error(
                            f"get_display_message() of {repr(message)} does not return 'DisplayableMessage' object, got {type(m)}."
                        )
                except Exception as e:
                    logger.error(f"Got exception when call get_display_message(): {e}.")
            self.page.update()

    async def __push(
        self, m: DisplayableMessage, *, update: bool = True
    ) -> ft.Control | ft.Markdown:
        """Push no lock"""
        role = m.role
        assert role in ["user", "assistant"]
        assert m.sender is not None

        if role == "user":
            title = ft.Text(m.sender, text_align=ft.TextAlign.RIGHT)
            ex_title_kwargs = dict(
                affinity=ft.TileAffinity.TRAILING,
                expanded_alignment=ft.alignment.top_right,
            )
        else:
            title = ft.Text(m.sender, text_align=ft.TextAlign.LEFT)
            ex_title_kwargs = dict(
                affinity=ft.TileAffinity.LEADING,
                expanded_alignment=ft.alignment.top_left,
            )

        # noinspection PyTypeChecker
        control = await asyncio.to_thread(self._render, m)
        ex_title = ft.ExpansionTile(
            title,
            controls=[ft.Container(control)],
            initially_expanded=True,
            **ex_title_kwargs,
        )
        self.message_list.append(ex_title)
        if update:
            self.page.update()
        return control

    def _render(self, data: DisplayableMessage, **kwargs) -> ft.Control | ft.Markdown:
        try:
            # for future general supported formats
            control = getattr(self, f"_render_{data.type}")(data.content)
        except Exception as e:
            logger.error(
                f"Cannot call render with type '{data.type}'. Exception {e}.\n"
                f"Backup with markdown render."
            )
            control = self._render_markdown(data.content)
        assert isinstance(control, ft.Control)
        return control

    def _render_html(self, content: str, **kwargs) -> ft.Control:
        raise NotImplementedError

    def _render_markdown(self, content: str, **kwargs) -> ft.Control:
        return ft.Markdown(
            content,
            selectable=True,
            extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
            on_tap_link=lambda e: self.page.launch_url(e.data),
            expand=True,
        )
