from typing import AsyncGenerator, Callable, Annotated

from langchain.chat_models import init_chat_model
from langchain_core.messages import AnyMessage
from langgraph.graph import StateGraph, add_messages
from pydantic import BaseModel
from ray import serve

from chatbone.assistant_interface import (AssistantInputData, Text, TextStream, Status, AssistantStatusCode,
                                          BaseAssistant, AssistantStreamer, AssistantOutputData, )
from utilities import logger


class DataInput(AssistantInputData):
	message: Text
	others: list[Text]


class DataOutput(AssistantOutputData):
	content: TextStream


def get_streamer() -> Callable[[DataInput], AsyncGenerator[DataOutput, None]]:

	class State(BaseModel):
		messages: Annotated[list[AnyMessage], add_messages]
		data_input: DataInput

	builder = StateGraph(State)

	async def node1(data_input: DataInput):
		state = State(
			data_input=data_input,
			messages=data_input.message.model_dump(include={"role", "content"}),
		)

		llm = init_chat_model(model="google_genai:gemini-2.0-flash")
		llm_response = await llm.ainvoke(state.messages)

		state.messages = llm_response

		return state

	builder.add_node("node1", node1).set_entry_point("node1").set_finish_point("node1")
	graph = builder.compile()

	async def streamer(data: DataInput):
		assert data is not None
		# async for chunk in graph.astream(data,stream_mode=):
		async for chunk, meta in graph.astream(data, stream_mode="messages"):
			if isinstance(chunk, str):
				yield DataOutput(
					content=TextStream(id=meta["langgraph_node"], chunk=chunk),
					status=Status(code=AssistantStatusCode.PROCESSING),
				)

	return streamer


class DummyAssistant(BaseAssistant):
	streamer: AssistantStreamer = get_streamer()
	input_schema: type[AssistantInputData] = DataInput
	name: str | None = "Dummy Assistant"

	async def handle_cancellation(self):
		logger.info(f"{self.__class__.__name__} handling cancellation.")


app = DummyAssistant.get_app()

if __name__=="__main__":
	serve.run(app,blocking=True,route_prefix=None, name="dummy")
