__all__=["Node","Edge",
         "WorkflowSetup","WorkflowSetupException","Workflow","WorkflowState"]
import inspect
from typing import Callable, Any, Awaitable, Annotated, Sequence

from langchain_core.messages import AnyMessage
from langgraph.graph import StateGraph, add_messages
from pydantic import BaseModel, ConfigDict, Field, field_validator
from ray import serve

from chatbone.utils import BaseMethodException, handle_exception


class WorkflowSetupException(BaseMethodException):
    pass

class Node(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    name:str
    action: Callable[...,Awaitable] =Field(exclude=True)

    @field_validator("action",mode="before")
    @classmethod
    @handle_exception(WorkflowSetupException,message="Node.action only accept coroutine function.")
    def check_coro_func(cls,f:Any):
        if not inspect.iscoroutinefunction(f):
            raise
        return f


class Edge(BaseModel):
    start: str|list[str]
    end: str


class WorkflowSetup(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    name:str
    nodes: Sequence[Node]
    edges: Sequence[Edge]

    #StateGraph init
    state_schema: type|None=None
    config_schema:type|None=None
    input:type|None=None
    output:type|None=None

    @field_validator("nodes",mode="before")
    @classmethod
    @handle_exception(WorkflowSetupException,message="Node name are not unique.")
    def check_node_names(cls,nodes: Sequence[Node]):
        names = [n.name for n in nodes]
        if len(set(names)) != len(names):
            raise
        return nodes


class WorkflowState(BaseModel):
    pass

# class WfMessagesState(WorkflowState):
#     messages: Annotated[list[AnyMessage],Field(default_factory=list),add_messages]
#
class ProcessStream:
    pass

class TextStream:
    pass

@serve.deployment
class Workflow(StateGraph):
    """
    langgraph.Graph wrapper. Nodes of graph must be coroutines.
    If sync function need to be used, users Worker, wrap it with async function and wait for results.
    """
    def __init__(self,setup: WorkflowSetup):
        self.setup = setup
        self.name = setup.name
        super().__init__(**setup.model_dump(include={"state_schema","config_schema","input","output"}))
        self._add_nodes()
        self._add_edges()

    def _add_nodes(self):
        for node in self.setup.nodes:
            self.add_node(node.name, node.action)

    def _add_edges(self):
        for edge in self.setup.edges:
            self.add_edge(edge.start,edge.end)

