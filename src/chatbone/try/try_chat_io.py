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
	validator = lambda v: v if len(v)<10 else None

class DataInput(AssistantInputData):
	image: VideoObject | list[ImageObject]|None
	texts: list[LimitText] | dict[str, Selection] = Field(description="texts description")
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
	page.add(
		button,
		ft.Divider(thickness=5),
		input_field,
		text
	)


ft.app(main, view=ft.AppView.WEB_BROWSER)
