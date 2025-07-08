from typing import AsyncGenerator, Annotated

from langchain.chat_models import init_chat_model
from langchain_core.messages import AnyMessage, HumanMessage, AIMessageChunk
from langgraph.graph import StateGraph, add_messages
from pydantic import BaseModel, Field

from chatbone.assistant import (
    AssistantInputData,
    Text,
    AssistantOutputData,
    ImageObject,
    BaseAssistant,
    capture_chat_context,
    get_data_segments,
    save_data_segments,
    DisplayableMessage,
    DataSegment,
    CompositeDisplayMessage,
)
from utilities import logger


class DataInput(AssistantInputData):
    message: Text = Field(description="say what ever you want")

    async def _compose_displayable_data(self) -> DisplayableMessage:
        return DisplayableMessage(content=self.message.content)


class DataOutput(AssistantOutputData):
    text: Text
    image: ImageObject | None = None

    async def _compose_displayable_data(self) -> DisplayableMessage:
        content = self.text.content
        if self.image is not None:
            url = await self.image.get_preview_url()
            content += f"""
            ![My image]({url})
            """
        return DisplayableMessage(content=content)


class State(BaseModel):
    # noinspection PyTypeHints
    messages: Annotated[list[AnyMessage], add_messages]
    data_input: DataInput


builder = StateGraph(DataInput)


async def node1(data_input: DataInput):

    segments = await get_data_segments()
    logger.debug("Node 1: All history segments display")
    for ds in segments:
        print("START DS=================================")
        for m in ds.messages:
            if m := (await m.get_display_message()):
                print(m.content, sep="")
            else:
                logger.error("Cannot get displayable message in segment")
        print("END DS===================================")

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


async def node2(state: State):
    logger.debug("ENTER NODE 2")

    chat_context_list = await capture_chat_context()
    logger.debug(f"Node2 capture context:\n" f"{chat_context_list}")

    class CustomDisplayMessage(CompositeDisplayMessage):
        async def _compose_displayable_data(self) -> DisplayableMessage:
            contents = []
            async for m in self.iter_displayable_messages():
                contents += m.content
            return DisplayableMessage(content="".join(contents))

    class CustomDataSegment(DataSegment):
        total_stream_token: int | None = None  # anything

    data_segment = CustomDataSegment()

    context = chat_context_list[0]  # The latest conversation context.
    output_display_message = CustomDisplayMessage(
        default_role="assistant", default_sender="Dummy", default_type="markdown"
    )

    # Compose data segment.
    for data in context:
        assert isinstance((m := await data.get_display_message()), DisplayableMessage)
        # Append only display message, in input messags
        if isinstance(data, AssistantInputData):
            data.default_sender = data.username
            data.default_role = "user"
            data.default_type = "markdown"
            data_segment.messages.append(data)
            continue

        assert isinstance(data, AssistantOutputData)
        output_display_message.append(data)
    # Append output message
    data_segment.messages.append(output_display_message)
    data_segment.total_stream_token = len(context)

    logger.debug(f"Saving data_segment:\n" f"{repr(data_segment)}")

    await save_data_segments([data_segment])
    logger.debug("Saved segments")
    return state


(
    builder.add_node("node1", node1)
    .set_entry_point("node1")
    .add_node("node2", node2)
    .add_edge("node1", "node2")
    .set_finish_point("node2")
)

graph = builder.compile()


async def streamer(data: DataInput) -> AsyncGenerator[DataOutput, None]:
    assert data is not None
    logger.debug(f"DUMMY streamer receive data input")
    logger.debug(repr(data))

    async for chunk, meta in graph.astream(data, stream_mode="messages"):
        assert isinstance(chunk, AIMessageChunk)
        yield DataOutput(
            text=Text(content=chunk.content),
        )


class Dummy2Assistant(BaseAssistant):
    async def handle_cancellation(self):
        logger.info(f"{self.__class__.__name__} handling cancellation.")

# noinspection PyTypeChecker
dummy2_assistant = Dummy2Assistant(
    name="Dummy2 Assistant", input_schema=DataInput, streamer=streamer
)
