from typing import AsyncGenerator, Callable, Annotated, Type

from langchain.chat_models import init_chat_model
from langchain_core.messages import AnyMessage
from langgraph.graph import StateGraph, add_messages
from pydantic import Field
from utilities.logger import logger

from chatbone.assistant_interface import BaseAssistant, AssistantData, TextStream, AssistantStreamer


class SampleInputSchema(AssistantData):
	messages: Annotated[list[AnyMessage], add_messages] = Field(default_factory=list)

def get_streamer() -> Callable[[SampleInputSchema], AsyncGenerator[AssistantData, None]]:
	builder = StateGraph(SampleInputSchema)

	async def node1(state: SampleInputSchema):
		llm = init_chat_model(model="google_genai:gemini-2.0-flash")
		llm_response = await llm.ainvoke(state.messages)
		state.messages = llm_response
		return state

	builder.add_node("node1", node1).set_entry_point("node1").set_finish_point("node1")
	graph = builder.compile()

	TextStreamData = AssistantData.create_model({"content": TextStream})

	async def streamer(data: AssistantData):
		# async for chunk in graph.astream(data,stream_mode=):
		async for chunk, meta in graph.astream(data, stream_mode="messages"):
			if isinstance(chunk, str):
				yield TextStreamData(content=TextStream(id=meta["langgraph_node"], chunk=chunk))

	return streamer

streamer = get_streamer()

class SampleAssistant(BaseAssistant):
	streamer: AssistantStreamer = streamer
	input_schema: Type[AssistantData] = SampleInputSchema

	async def handle_cancellation(self):
		logger.info(f"{self.__class__.__name__} handling cancellation.")

app = SampleAssistant.get_app()

if __name__=="__main__":
	from ray import serve
	serve.run(app,blocking=True)