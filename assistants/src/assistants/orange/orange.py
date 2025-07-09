import asyncio
import time
from typing import AsyncGenerator

from langchain.chat_models import init_chat_model
from langchain_core.messages import (
    HumanMessage,
    AIMessageChunk,
    SystemMessage,
    AIMessage,
    BaseMessage,
)
from langgraph.graph import StateGraph
from pydantic import Field, BaseModel

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

# This is the name which will be shown to user.
ASSISTANT_NAME = "Orange Assistant"


class DataInput(AssistantInputData):
    message: Text = Field(description="Say what ever you want.")
    images: list[ImageObject] | None = Field(
        None,
        description="If you give me images, I have nothing to do with them now,"
        " So I just resend it.",
    )

    async def _compose_displayable_data(self) -> DisplayableMessage:
        """Show your text and original images"""
        content = self.message.content
        if self.images:
            content += f"""
            You sent {len(self.images)} images.
            """
        return DisplayableMessage(content=content)


class InputSchema(BaseModel):
    data_input: DataInput
    context: str | None = None


class DataOutput(AssistantOutputData):
    text: Text
    images: list[ImageObject] | None = None

    async def _compose_displayable_data(self) -> DisplayableMessage:
        content = self.text.content
        if self.images:
            for image in self.images:
                try:
                    url = await image.get_preview_url()
                    content += f"""
                    ![My image]({url})
                    """
                except Exception as e:
                    logger.error(e)

        return DisplayableMessage(content=content)


class CustomDataSegment(DataSegment):
    segment_summary: str = ""


class CustomDisplayMessage(CompositeDisplayMessage):
    """Basically concat all message chunk into a complete message"""

    async def _compose_displayable_data(self) -> DisplayableMessage:
        contents = []
        async for m in self.iter_displayable_messages():
            contents += m.content
        return DisplayableMessage(content="".join(contents))


llm = init_chat_model(model="google_genai:gemini-2.0-flash")
builder = StateGraph(InputSchema)


async def compose_context(input_schema: InputSchema) -> InputSchema:
    """Capture the latest conversation chunks, which contains all AssistantData in the same chat context.
    Then make data segments and save."""

    # capture 1000 latest stream chunks to compose context
    capture_context_list = await capture_chat_context(from_latest=True, count=1000)
    logger.debug(f"Captured context list: {capture_context_list}")

    # Skip if it has nothing ( case when count =1 but data_only =True for example)
    if capture_context_list:
        last_conversation_data = capture_context_list[0]
        assert len(last_conversation_data) != 0
        logger.debug(f"Last conversation data:\n{last_conversation_data[:10]}")

        data_segment = CustomDataSegment()
        output_display_message = CustomDisplayMessage(
            default_role="assistant",
            default_sender=ASSISTANT_NAME,
            default_type="markdown",
        )

        # Compose data segment.
        for data in last_conversation_data:
            if isinstance(data, AssistantInputData):
                data.default_sender = data.username
                data.default_role = "user"
                data.default_type = "markdown"
                data_segment.messages.append(data)
                continue

            assert isinstance(data, AssistantOutputData)
            output_display_message.append(data)  # Append the chunk

        # Append the complete output data
        data_segment.messages.append(output_display_message)
        input_content = (await data_segment.messages[0].get_display_message()).content
        output_content = (await data_segment.messages[1].get_display_message()).content
        logger.debug(f"input content:\n{input_content}")
        logger.debug(f"output content:\n{output_content}")
        messages = [
            SystemMessage(
                content="""This is conversations of a human and a chat bot.
                Make the short summary of this conversation.
                Point out the target of each message and information of the sender such as name, age, habit,...
                Keep it short, clean, ideally not exceed 50 words."""
            ),
            HumanMessage(content=input_content),
            AIMessage(content=output_content),
        ]

        # GEMINI FREE IS DUMP AS FUK, IF YOU NOT DO BELOW, SUMMARY IS NONE.
        n = 3
        summary=""
        for i in range(n):
            summary = (await llm.ainvoke(messages)).content
            if summary:
                break
            logger.debug(f"Summary return nothing, try again {i+1}")
        
        if not summary:
            logger.debug(f"Call summary {n} time but the result still nothing. Try to call and wait")
            summary = (await llm.ainvoke(messages)).content
            await asyncio.sleep(n)
        
        if not summary:
            logger.debug(f"Cannot call LLM to do summary context. Use concat message instead")
            summary = "\n".join(m.model_dump_json() for m in messages)

        logger.debug(f"Saving data_segment summary:\n" f"{summary}")
        data_segment.segment_summary = summary
        await save_data_segments([data_segment])
        logger.debug("Saved segments")

    return input_schema


async def collect_context(input_schema: InputSchema) -> InputSchema:
    """Collect the context of previous history, or you can do anything else to compose context, such as search google."""

    context = ""

    segments = await get_data_segments(3)  # get 3 latest data segments
    logger.debug(f"Get data segment: {segments}")

    for segment in segments:
        assert isinstance(segment, CustomDataSegment)
        context += segment.segment_summary

    if context != "":
        context = f"""
        This is the summary of the current context of the conversation.
        You can use this to gain more information about user information, context,...
        Note that you don't need to show this to user again, if you use this, just say something like "as you said..." or "depend on previous chat..."
        {context}
        """

        logger.debug(f"Collected context:\n" f"{context}")
    input_schema.context = context
    return input_schema


async def chat(input_schema: InputSchema) -> InputSchema:
    content = (await input_schema.data_input.get_display_message()).content
    messages: list[BaseMessage] = [HumanMessage(content=content)]
    if input_schema.context:
        messages.insert(0, SystemMessage(content=input_schema.context))
    start = time.time()
    print("chat start call")
    llm_response = await llm.ainvoke(messages)
    print(f"chat call finished in {time.time()-start } seconds.")

    return input_schema


(
    builder.add_node(compose_context)
    .add_node(collect_context)
    .add_node(chat)
    .set_entry_point("compose_context")
    .add_edge("compose_context", "collect_context")
    .add_edge("collect_context", "chat")
    .set_finish_point("chat")
)

graph = builder.compile()


async def streamer(data: DataInput) -> AsyncGenerator[DataOutput, None]:
    assert data is not None
    logger.debug(f"{ASSISTANT_NAME} streamer receive data input\n" f"{repr(data)}")
    input_schema = InputSchema(data_input=data)

    async for chunk, meta in graph.astream(input_schema, stream_mode="messages"):
        assert isinstance(chunk, AIMessageChunk)
        node = meta["langgraph_node"]
        # Yield only chat node llm.
        if node == "chat":
            yield DataOutput(
                text=Text(content=chunk.content),
            )
            logger.debug(f"Stream returned from yield")
    
    if data.images:
        yield DataOutput(
            text=Text(content="---Images from user---"),
            images=data.images
        )
        
        
class OrangeAssistant(BaseAssistant):
    async def handle_cancellation(self):
        logger.info(f"{self.__class__.__name__} handling cancellation.")


# noinspection PyTypeChecker
orange_assistant = OrangeAssistant(
    name=ASSISTANT_NAME, input_schema=DataInput, streamer=streamer
)
