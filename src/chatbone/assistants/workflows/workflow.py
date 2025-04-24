__all__ = ["Node", "Edge", "WorkflowSetup", "WorkflowSetupException", "Workflow", "WorkflowState"]

from abc import ABC, abstractmethod
from typing import Annotated, Sequence, AsyncGenerator

from chatbone_utils.utils import BaseMethodException, handle_exception
from langgraph.graph import StateGraph
from pydantic import BaseModel, ConfigDict, Field, field_validator
from ray.serve import Application, deployment


class WorkflowSetupException(BaseMethodException):
	pass


class WorkflowState(BaseModel):
	pass


class Node(BaseModel):
	"""
	Note: Nodes are not deployment object, so all operations should be the async one.
	"""
	model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)
	name: str
	@abstractmethod
	async def __call__(self, state: WorkflowState):
		pass


class Edge(BaseModel):
	start: str | list[str]
	end: str


class Workflow:
	"""
	langgraph.Graph wrapper. Nodes of graph must be coroutines.
	If sync function need to be used, users Worker, wrap it with async function and wait for results.
	Declare behavior.
	"""

	def __init__(self, *, builder: StateGraph, compile_kwargs: dict):
		self._builder = builder
		self._compile_kwargs = compile_kwargs

	async def __call__(self,*args,compile_kwargs:dict, **kwargs) -> AsyncGenerator:
		graph = self._builder.compile(**compile_kwargs)
		async for state in graph.astream(*args, **kwargs):
			yield state


class WorkflowSetup(BaseModel, ABC):
	"""Assistant has responsibility to set up workflow."""
	model_config = ConfigDict(arbitrary_types_allowed=True)
	name: str
	nodes: Sequence[Node]
	edges: Sequence[Edge]

	# StateGraph init
	state_schema: type | None = None
	config_schema: type | None = None
	input: type | None = None
	output: type | None = None

	deployment_kwargs: Annotated[dict, Field(default_factory=dict)] # ray.serve.deployment

	@field_validator("nodes", mode="before")
	@classmethod
	@handle_exception(WorkflowSetupException, message="Node name are not unique.")
	def check_node_names(cls, nodes: Sequence[Node]):
		names = [n.name for n in nodes]
		if len(set(names)) != len(names):
			raise
		return nodes

	def __init__(self, **kwargs):
		super().__init__(**kwargs)
		self._builder = StateGraph(**self.model_dump(include={"state_schema", "config_schema", "input", "output"}))
		self._add_nodes()
		self._add_edges()

	def make_workflow_app(self) -> Application:
		return deployment(**self.deployment_kwargs)(Workflow).bind(builder=self._builder)

	def _add_nodes(self):
		for node in self.nodes:
			self._builder.add_node(node.name, node)

	def _add_edges(self):
		for edge in self.edges:
			self._builder.add_edge(edge.start, edge.end)

# a= Workflow
#
# # class WfMessagesState(WorkflowState):
# #     messages: Annotated[list[AnyMessage],Field(default_factory=list),add_messages]
# #
# class ProcessStream:
#     pass
#
# class TextStream:
#     pass
