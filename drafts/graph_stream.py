import asyncio

from langgraph.graph import StateGraph, MessagesState, START,END
import threading
import time
import os

class State(MessagesState):
    pass

def cpu_bound():
    """For debugging, it will make coroutines easy to see in tasks graph."""
    time.sleep(0.25)

def info():
    return f"PID[{os.getpid()}] - [{threading.get_native_id()}] "


t = 0.5
n = 5



def coro(s:str):
    async def c(state):
        asyncio.current_task().set_name(f"{s} {info()}")
        for i in range(n):
            print(f"{info()}:{s}")
            cpu_bound()
            await asyncio.sleep(t)
        return dict(messages= [f'{s}'])
    return c

def func(s:str):
    def f(state):
        for i in range(n):
            print(f"{info()}:{s}")
            time.sleep(1)
        return dict(messages=[f'{s}'])
    return f

async def non_graph_coro():
    asyncio.current_task().set_name(f"NONE-GRAPH-CORO {info()}")
    for i in range(n):
        print(f"{info()}NON-GRAPH-CORO")
        cpu_bound()
        await asyncio.sleep(t)

builder = StateGraph(State)

builder.add_node('node_1',coro('coro1'))
builder.add_node('node_2',coro('coro2'))
builder.add_node('node_3',func('func3'))
builder.add_node('node_4',func('func4'))

builder.add_edge(START,'node_1')
builder.add_edge(START,'node_2')
builder.add_edge(START,'node_3')
builder.add_edge(START,'node_4')

builder.add_edge('node_1',END)
builder.add_edge('node_2',END)
builder.add_edge('node_3',END)
builder.add_edge('node_4',END)

graph = builder.compile()
# print(graph.get_graph().draw_mermaid())



async def async_main(m):
    asyncio.create_task(non_graph_coro())

    async for node in graph.astream(m):
        print(node)

def main(m):
    for node in graph.stream(m):
        print(node)

if __name__=="__main__":
    m = State(messages=["Hello"])

    asyncio.run(async_main(m))

    # Cannot run because nodes is not all sync func.
    # main(m)

# If using stream, all node must be synchronous function, if there is async task, wrap it with sync.
# All parallel branches will be executed in separated threads.

# If using astream, node can be function (sync func) or coroutine (async func).
# All sync func in parallel branches will be executed in separated threads, all async one will be executed in the same loop.
# Note that astream must be call in a loop (ex: asyncio.run). And this loop will run all async func in graph along with others
# non-graph async funcs.

# Rule of thump: use astream
# gunicorn, nginx, ...