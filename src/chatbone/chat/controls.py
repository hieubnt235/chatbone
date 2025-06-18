import asyncio
from abc import ABC, abstractmethod
from contextlib import AsyncExitStack
from copy import deepcopy
from datetime import timedelta
from enum import Enum
from math import floor
from typing import Any, Callable, List
from uuid import UUID

import flet as ft
from flet.core.file_picker import (FilePickerResultEvent, FilePickerUploadEvent, FilePickerFile, )
from pydantic import BaseModel, ConfigDict

from chatbone.assistant_interface import (AssistantDataType_U, AnyMediaObject, MediaObject, ImageObject, )
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


class BaseInputField(ABC):

    @abstractmethod
    def get_assistant_data(
        self,
    ) -> AssistantDataType_U | List[AssistantDataType_U] | None:
        pass


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

    async def upload(self, picked_files: List[FilePickerFile]):
        """
        Args:
                picked_files: It should input as name, but use FilePickerFile because of Flet convention.

        Returns:
        """

        files: list[ft.FilePickerUploadFile] = []
        for file in picked_files:
            url = await self._create_upload_url(file.name)
            files.append(
                ft.FilePickerUploadFile(file.name, url)
            )  # todo: wtf FilePickerUploadFile.id used for?
        super().upload(files)

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
        return self._username + "_" + str(self._user_id) + "/" + file_name

class MediaInputField(BaseInputField, ft.Container):
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
                ft.ProgressRing(0.0,scale=0.8),
                ft.Text(f"{filename[:10]}+...+{filename[-10:]}",size=12,text_align=ft.TextAlign.LEFT),
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
            scale = 0.8
        )
        self._unselect_all_button = ft.IconButton(
            ft.Icons.CANCEL_PRESENTATION_OUTLINED,
            tooltip="Unselect all",
            on_click=self._unselect_all,
            disabled=True,visible=False,
        )
        self._file_index_lock = UniversalLock()
        self._file_names: list[str] = []
        self._file_list = ft.ListView([],height=250,width=320)

        column = ft.Column([
            ft.Row([self._select_button, self._unselect_all_button],alignment=ft.MainAxisAlignment.START,spacing=0),
            self._file_list,
        ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
            width=320
        )

        super().__init__(column,border=ft.border.all(5))

    async def get_assistant_data(
        self,
    ) -> AssistantDataType_U | List[AssistantDataType_U] | None:
        """
        Returns:
            If allow_multiple, return a list of MediaObject or a blank list. Else return only one MediaObject or None.
        """
        if self._allow_multiple:
            assert len(self._file_names) <= 1
            return (await self.get_file_preview_row(self._file_names[0])).media_object if len(self._file_names) == 1 else None

        async with self._file_index_lock:
            if not self._file_names:
                return []
            else:
                return [ f.media_object for f in self._file_list.controls if isinstance(f, MediaInputField._FilePreviewRow) and f.media_object is not None ]

    def build(self):
        self.page.overlay.append(self._file_picker)

    async def _on_result(self, e: ft.FilePickerResultEvent):
        """Add files to selected file list. Do not override."""
        if e.files is not None:
            # If not allow multiple, unselect the old and load the new.
            if not self._allow_multiple:
                assert len(self._file_names) <= 1
                await self._unselect_all()

            # If filename already available, unselect the old and load the new.
            for file in e.files:
                if file.name in self._file_names:
                    await self._unselect(file.name)

            await self._file_picker.upload(e.files)
            await asyncio.to_thread(self.make_file_preview_rows, e.files)
        self._change_unselect_all_button_state()
        self.page.update()

    async def _on_upload(self, e: ft.FilePickerUploadEvent):
        if e.error:
            await self._unselect(e.file_name, update=False)
            logger.info(f"Error happened during uploading file: '{e.error}'")
            self._notice_user(
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
                except TypeError:
                    await self._unselect(e.file_name, update=False)
                    self._notice_user(
                        f"File type must the '{self._datatype.type.title()}'. Unselect file '{e.file_name}'."
                    )
            else:
                await self.update_progress(e.file_name, e.progress, media_object)

    def _notice_user(self, text: str):
        self.page.open(ft.SnackBar(ft.Text(text)))

    async def _unselect_all(self, e=None):
        for filename in deepcopy(self._file_names):
            await self._unselect(filename, update=False)
        self.page.update()

    async def _unselect(self, filename, update: bool = True):
        await self._file_picker.cancel(filename)
        await self.remove_file_review_row(filename)
        if update:
            self.page.update()

    def _change_unselect_all_button_state(self):
        if self._file_names:
            self._unselect_all_button.disabled = False
            self._unselect_all_button.visible = True
        else:
            self._unselect_all_button.disabled = True
            self._unselect_all_button.visible = False

    async def update_progress(self, filename: str, progress: float, media_object=None):
        async with self._file_index_lock:
            row = await self.get_file_preview_row(filename,lock=False)
            await row.update_progress(progress, media_object)

    async def get_file_preview_row(
        self, filename: str, lock:bool=True
    ) -> "MediaInputField._FilePreviewRow":
        async with AsyncExitStack() as stack:
            if lock:
                await stack.enter_async_context(self._file_index_lock)
            index = self._file_names.index(filename)
            return self._file_list.controls[index]

    async def remove_file_review_row(
        self, filename: str
    ) -> "MediaInputField._FilePreviewRow":
        async with self._file_index_lock:
            index = self._file_names.index(filename)
            self._file_names.pop(index)
            fr = self._file_list.controls.pop(index)
            self._change_unselect_all_button_state()
            return fr

    def make_file_preview_rows(self, picked_files: list[FilePickerFile]):
        for file in picked_files:
            with self._file_index_lock:  # with for run in another thread.
                self._file_list.controls.append(
                    MediaInputField._FilePreviewRow(file.name, self)
                )
                self._file_names.append(file.name)
                self._change_unselect_all_button_state()

if __name__ == "__main__":

    uuid = UUID("0cab9030-a5d5-49a8-ab90-30a5d519a818")
    print(ImageObject.extensions)

    async def main(page: ft.Page):
        page.vertical_alignment = ft.MainAxisAlignment.CENTER
        page.horizontal_alignment = ft.CrossAxisAlignment.CENTER

        media_input_field = MediaInputField(
            "hieu",
            uuid,
            ImageObject,
            allow_multiple=True,
        )
        page.add(media_input_field)

    app = ft.app(main, export_asgi_app=True)
    import uvicorn

    uvicorn.run(app, port=5555)
