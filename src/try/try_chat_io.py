from uuid import UUID

import flet as ft
from pydantic import Field

from chatbone.src.assistant_interface import (AssistantInputData, ImageObject, VideoObject, Text, Selection,
                                              AssistantOutputData, DataFormat, Status, AssistantStatusCode, )
from chatbone.src.chat.chat_io import ChatInputField, ChatOutputField
from chatbone.src.chat.svc import AssistantApp


class Selection(Selection):
    options = {"opt 1": "this is option 1", "opt 2": "this is option 2"}


class LimitText(Text):
    validator = lambda v: v if len(v) < 10 else None


class DataInput(AssistantInputData):
    image: VideoObject | list[ImageObject] | None
    texts: list[LimitText] | dict[str, Selection]|None = Field(
        default=[LimitText(role= "user", content = "default content if limit text")],
        description="texts description"
    )
    select: Selection
    # t : list[LimitText]| tuple[LimitText, LimitText, Selection|LimitText]
    
    async def get_data_format(self) -> DataFormat | None:
        
        md = f"""
        
* Image
    - {self.image}
    
* texts
    - {self.texts}
    
* select
    - {self.select}

```python
import flet
from flet import IconButton, Page, Row, TextField, icons

def main(page: Page):
    page.title = "Flet counter example"
    page.vertical_alignment = "center"

    txt_number = TextField(value="0", text_align="right", width=100)

    def minus_click(e):
        txt_number.value = int(txt_number.value) - 1
        page.update()

    def plus_click(e):
        txt_number.value = int(txt_number.value) + 1
        page.update()

    page.add(
        Row(
            [
                IconButton(icons.REMOVE, on_click=minus_click),
                txt_number,
                IconButton(icons.ADD, on_click=plus_click),
            ],
            alignment="center",
        )
    )

flet.app(target=main, port=8550)
```


        """
        return DataFormat(type="markdown",content=md)

class DataOutput(AssistantOutputData):
    text: Text = Text(role="assistant", content="this is dummy output text.")
    
    async  def get_data_format(self) -> DataFormat | None:
        return DataFormat(type="text", content = self.text.content)

async def main(page: ft.Page):
    uid = "0197a813-57b5-7dfa-aad4-7d36a58a62e7"
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    input_field = ChatInputField(
        assistant_apps=dict(
            dummy=AssistantApp(
                input_schema=DataInput,
                description="This is dummy",
                app_name="dummy app",
            )
        ),
        username="hieu",
        user_id=UUID(uid),
        width=page.width / 2,
        height=page.height*0.4,
        border=ft.border.all(1, color=ft.Colors.GREEN),
    )
    #
    text = ft.Text(None,width=page.width*0.3)
    output_field = ChatOutputField(username="hieu", user_id=UUID(uid),
                                   width=page.width/2,
                                   height = page.height*0.4,
                                   border=ft.border.all(1,color=ft.Colors.RED))

    async def on_click(e):
        data = await input_field.get_input_data()
        as_name, data = data
        if data:
            text.value = repr(data)
            await output_field.push(data)
            await output_field.push(DataOutput(assistant_name=as_name,status=Status(code=AssistantStatusCode.DONE)))
        else:
            text.value = "NOTHING"
        page.update()

    button = ft.Button("select", on_click=on_click)
    page.add(text, output_field, ft.Row([input_field,button,text],alignment=ft.MainAxisAlignment.CENTER))

ft.app(main, view=ft.AppView.WEB_BROWSER)
