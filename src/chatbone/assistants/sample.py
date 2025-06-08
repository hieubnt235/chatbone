from typing import AsyncGenerator, Callable, Type

from langchain.chat_models import init_chat_model
from langgraph.graph import StateGraph
from pydantic import Field

from chatbone.assistant_interface import BaseAssistant, AssistantData, TextStream, AssistantStreamer, ManyMessages, \
	Status, AssistantStatusCode
from utilities.logger import logger


class SampleInputSchema(AssistantData):
	messages: ManyMessages = Field(default_factory=list)

def get_streamer() -> Callable[[SampleInputSchema], AsyncGenerator[AssistantData, None]]:
	builder = StateGraph(SampleInputSchema)

	async def node1(state: SampleInputSchema):
		llm = init_chat_model(model="google_genai:gemini-2.0-flash")
		llm_response = await llm.ainvoke(state.messages)
		state.messages = llm_response
		return state

	builder.add_node("node1", node1).set_entry_point("node1").set_finish_point("node1")
	graph = builder.compile()

	TextStreamData = AssistantData.create_model({"content": TextStream}, doc="Data tokens stream")

	async def streamer(data: AssistantData):
		assert data is not None
		# async for chunk in graph.astream(data,stream_mode=):
		async for chunk, meta in graph.astream(data, stream_mode="messages"):
			if isinstance(chunk, str):
				yield TextStreamData(content=TextStream(id=meta["langgraph_node"], chunk=chunk),
				                     status=Status(code=AssistantStatusCode.PROCESSING))

	return streamer

def foo(a):
	return "a"+str(a)

class SampleAssistant(BaseAssistant):
	streamer: AssistantStreamer = foo
	input_schema: Type[AssistantData] = SampleInputSchema

	async def handle_cancellation(self):
		logger.info(f"{self.__class__.__name__} handling cancellation.")

app = SampleAssistant.get_app()

if __name__=="__main__":
	from ray import serve
	serve.run(app,blocking=True)