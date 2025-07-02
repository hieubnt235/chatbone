from typing import AsyncGenerator, Callable, Annotated

from langchain.chat_models import init_chat_model
from langchain_core.messages import AnyMessage, HumanMessage, AIMessageChunk
from langgraph.graph import StateGraph, add_messages
from pydantic import BaseModel, Field
from uuid_extensions import uuid7

from chatbone.assistant_interface import (
    AssistantInputData,
    Text,
    AssistantOutputData,
    ImageObject,
    VideoObject,
    BaseAssistant,
    AssistantStreamer,
)
from chatbone.broker import DisplayableMessage
from utilities import logger


class DataInput(AssistantInputData):
    message: Text = Field(description="say what ever you want")
    others: list[Text] | None = Field(None, description="add what ever")
    image: ImageObject | list[Text] | VideoObject | None = None
    
    async def _compose_displayable_data(self) -> DisplayableMessage:
        return DisplayableMessage(role="user",content=self.message.content)


class DataOutput(AssistantOutputData):
    text: Text
    image: ImageObject|None=None
    
    async def _compose_displayable_data(self) -> DisplayableMessage:
        content = self.text.content
        if self.image is not None:
            url = await self.image.get_preview_url()
            content+=f"""
            ![My image]({url})
            """
        
        return DisplayableMessage(
            role="assistant", type="markdown", content=content, sender=self.assistant_name
        )


def get_streamer() -> Callable[[DataInput], AsyncGenerator[DataOutput, None]]:

    class State(BaseModel):
        # noinspection PyTypeHints
        messages: Annotated[list[AnyMessage], add_messages]
        data_input: DataInput

    builder = StateGraph(DataInput)

    async def node1(data_input: DataInput):
        m = HumanMessage.model_validate(
            data_input.message,
            from_attributes=True,
        )
        state = State(
            data_input=data_input,
            messages=[m],
        )

        llm = init_chat_model(model="google_genai:gemini-2.0-flash")
        llm_response = await llm.ainvoke(state.messages)
        
        # noinspection PyTypeChecker
        state.messages = llm_response

        return state

    builder.add_node("node1", node1).set_entry_point("node1").set_finish_point("node1")
    graph = builder.compile()

    async def streamer(data: DataInput):
        assert data is not None
        logger.info(repr(data))
        # async for chunk in graph.astream(data,stream_mode=):
        stream_id = uuid7()

        async for chunk, meta in graph.astream(data, stream_mode="messages"):
            assert isinstance(chunk, AIMessageChunk)
            yield DataOutput(
                text=Text(content=chunk.content),
            )
        if isinstance(data.image, ImageObject):
            yield DataOutput(
                text= Text(content = "This is addition content outside the LLM"),
                image= data.image
            )

    return streamer


class DummyAssistant(BaseAssistant):
    streamer: AssistantStreamer = get_streamer()
    input_schema: type[AssistantInputData] = DataInput
    name: str | None = "Dummy Assistant"

    async def handle_cancellation(self):
        logger.info(f"{self.__class__.__name__} handling cancellation.")


app = DummyAssistant.get_app()

if __name__ == "__main__":
    # serve.run(app,blocking=True,route_prefix=None, name="dummy")
    import asyncio

    async def main():
        streamer = get_streamer()
        data_input = DataInput(
            message=Text(role="user", content="tell me a short story about cats.")
        )

        async for data in streamer(data_input):
            print(await data.get_display_message())

    asyncio.run(main())
