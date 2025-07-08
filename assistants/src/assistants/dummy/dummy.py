from typing import AsyncGenerator, Annotated

from langchain.chat_models import init_chat_model
from langchain_core.messages import AnyMessage, HumanMessage, AIMessageChunk
from langgraph.graph import StateGraph, add_messages
from pydantic import BaseModel, Field

from chatbone.assistant import (AssistantInputData, Text, AssistantOutputData, ImageObject, VideoObject, BaseAssistant,
                                capture_chat_context, get_data_segments, save_data_segments, Selection,
                                DisplayableMessage, DataSegment, CompositeDisplayMessage, AssistantStreamer, )
from utilities import logger
from utilities.misc import UniversalLock


# NewSelection = Selection[
#     dict(name="give me a name", value="what is your age", __doc__="this is the doc")
# ]
# assert issubclass(NewSelection,Selection)
# logger.debug(f"NewSelection = {NewSelection.options}")
# print(NewSelection.__name__)
# c = NewSelection.model_validate({"selection": "name"})
# try:
#     d = NewSelection(selection="abc")
# except ValueError as e:
#     print(e)
# print(c)
# print(c._dynamic_construction_class_args__)
# assert isinstance(c, Selection)
# b = cloudpickle.dumps(c)
# bb = base64.b64encode(b).decode()
# s = base64.b64decode(bb)
# cc = cloudpickle.loads(s)
#
# print(cc)
# print(cc.__class__, cc.__class__.__module__)
# print(cc.options)
# with open("dumpt", "rb") as f:
#     cc = cloudpickle.load(f)
#     print(cc)
#     print(cc.__class__,cc.__class__.__module__)
#     print(cc.options)

# b = cloudpickle.dumps(self)
# return base64.b64encode(b).decode()
# s = base64.b64decode(v)
# return cloudpickle.loads(s)


# YesNoSelection = Selection[{"Yes": "When you agree", "No": "When you dump","__doc__":"This is doc"}]

# TODO: NOT WORK
# logger.debug(f"Module: {__name__}")
# YesNoSelection = Selection[
#     {
#     "Yes": "When you agree",
#     "No": "When you dump",
#     "__doc__":"this is doc",
#     "__module__": __name__,
#     }
# ]


class YesNoSelection(Selection):
    options = {"Yes": "When you agree", "No": "When you dump"}


class DataInput(AssistantInputData):
    message: Text = Field(description="say what ever you want")
    others: list[Text] | None = Field(None, description="add what ever")
    image: ImageObject | list[Text] | VideoObject | None = None
    yes_no: YesNoSelection

    async def _compose_displayable_data(self) -> DisplayableMessage:
        return DisplayableMessage(
            content=self.message.content + f"\nSelection:{self.yes_no.selection}"
        )


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
        assert isinstance(
            (m := await data.get_display_message()), DisplayableMessage
        )
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

async def streamer(data: DataInput)->AsyncGenerator[DataOutput,None]:
    assert data is not None
    logger.debug(f"DUMMY streamer receive data input")
    logger.debug(repr(data))

    async for chunk, meta in graph.astream(data, stream_mode="messages"):
        assert isinstance(chunk, AIMessageChunk)
        yield DataOutput(
            text=Text(content=chunk.content),
        )
    if isinstance(data.image, ImageObject):
        yield DataOutput(
            text=Text(content="This is addition content outside the LLM"),
            image=data.image,
        )

    # return streamer
#
#
# streamer = get_streamer()


class DummyAssistant(BaseAssistant):
    # streamer: AssistantStreamer = streamer
    # input_schema: type[AssistantInputData] = DataInput
    # name: str = "Dummy Assistant"
    # lock: Uni
    lock: UniversalLock = UniversalLock()
    async def handle_cancellation(self):
        logger.info(f"{self.__class__.__name__} handling cancellation.")


# noinspection PyTypeChecker
dummy_assistant = DummyAssistant(
    name = "Dummy Assistant", input_schema=DataInput, streamer=streamer
)
#
# app = DummyAssistant.get_app()
# from ray.util import inspect_serializability
# print(inspect_serializability(DummyAssistant))

# if __name__ == "__main__":
#     # serve.run(app,blocking=True,route_prefix=None, name="dummy")
#     import asyncio
#
#     async def main():
#         streamer = get_streamer()
#         data_input = DataInput(
#             message=Text(role="user", content="tell me a short story about cats.")
#         )
#
#         async for data in streamer(data_input):
#             print(await data.get_display_message())
#
#     asyncio.run(main())

# class Data(AssistantInputData):
#     pass
# data = Data()
#
# print(data._role)
# e = data._encode()
#
# e = {f"{StreamData}".encode(): e[f"{StreamData}"]}
#
# d = StreamData._decode(e)
#
# assert isinstance(d,Data)
# print(d._role)
