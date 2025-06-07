import asyncio
import os

from langchain.chat_models import init_chat_model
from langgraph.graph import StateGraph
from pydantic import BaseModel, ConfigDict

from utilities.logger import logger


class MyState(BaseModel):
    model_config = ConfigDict(extra="allow")
    topic: str
    joke: str = ""
print(os.environ["GOOGLE_API_KEY"])
llm = init_chat_model(model="google_genai:gemini-2.0-flash")

async def call_model(state: MyState):
    """Call the LLM to generate a joke about a topic"""
    logger.info("START")
    llm_response = await llm.ainvoke(
        [
            {"role": "user", "content": f"Tell me a joke about {state.topic}"}
        ]
    )
    # for i in range(10):
    #     await asyncio.sleep(1)
    #     print(f"<{i}>",end="")
    logger.info("__end_node__")
    state.joke  = llm_response.content
    return state

async def node2(state):
    logger.info("__node2__")
    print(type(state))
    state.topic = "node2:" + state.topic
    return state

graph = (
    StateGraph(MyState)
    .add_node("node1",call_model)
    .add_node("node2",node2)
    .add_edge("node1","node2")
    .set_entry_point("node1")
    .compile()
)
async def main():
    async for message_chunk in graph.astream({"topic": "ice cream"},stream_mode="messages"):
        # if isinstance(message_chunk,dict):
        #     message_chunk = json.dumps(message_chunk,indent=4)
        print(message_chunk,end="\n<sep>\n")
        # if message_chunk.content:
        #     print("=========")
        #     # for k,v in metadata.items():
        #     #     print(k,":",v)
        #     print(message_chunk.content, end="|", flush=True)
        #     print("=========")
        await asyncio.sleep(1)
asyncio.run(main())