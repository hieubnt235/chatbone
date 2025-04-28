import pytest
from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph import START, END
from langgraph.graph.state import CompiledStateGraph
from uuid_extensions import uuid7

from assistants.workflows import (WorkflowSetup, Node, Edge, WorkflowSetupException, WfMessagesState,
                                  Workflow)
##TODO Serve graph with ray

async def anode(state: WfMessagesState)->WfMessagesState:
	#All below return methods are the same. Refer WfMessageState for clarity as well as validation.
	# If Message role is not clearly defined, it will be converted to HumanMessages automatically.
	m = f"M: {str(uuid7())}"
	# return WfMessagesState(messages=[AIMessage(m)])
	# return {"messages": m} # auto convert to HumanMessage
	# return {"message": [m]}
	state.messages = [m]
	return state

def node():
	"""For test"""
	pass

@pytest.fixture(scope="module")
def workflow()->tuple[Workflow,int]:
	n=5
	nodes = [Node(name=str(i), action=anode) for i in range(n)]
	edges = [Edge(start=START, end=nodes[0].name)]
	edges.extend([Edge(start=nodes[i].name, end=nodes[i + 1].name) for i in range(len(nodes) - 1)])
	edges.append(Edge(start=nodes[-1].name, end=END))

	setup = WorkflowSetup(name="wf", nodes=nodes, edges=edges, state_schema=WfMessagesState)
	wf = Workflow(setup)
	assert isinstance(wf._graph,CompiledStateGraph)
	logger.debug(f"MERMAID DIAGRAM:\n{wf._graph.get_graph().draw_mermaid()}")

	return wf,n


def test_workflow_setup():
	# Test accept only coroutine function.
	assert isinstance(Node(name="", action=anode), Node)
	with pytest.raises(WorkflowSetupException):
		# noinspection PydanticTypeChecker
		Node(name="node", action=node)

	# Test unique node names
	assert isinstance(WorkflowSetup(edges=[Edge(start="", end="")], name="",
	                                nodes=[Node(name="a", action=anode), Node(name="b", action=anode)]), WorkflowSetup)
	with pytest.raises(WorkflowSetupException):
		WorkflowSetup(edges=[Edge(start="", end="")], name="",
		              nodes=[Node(name="a", action=anode), Node(name="a", action=anode)])



@pytest.mark.asyncio(loop_scope="module")
async def test_workflow(workflow):
	wf,n = workflow

	first_m = WfMessagesState(messages=[AIMessage("this is first message.")])
	async for m in wf._graph.astream(first_m):
		logger.debug(m)

	me = (await wf._graph.ainvoke(first_m))
	from langgraph.pregel.io import AddableValuesDict
	assert isinstance(me,dict)
	assert isinstance(me,AddableValuesDict)
	for m in me["messages"]:
		assert isinstance(m,BaseMessage)


	logger.debug(f"\n{"\n".join([m.pretty_repr() for m in me["messages"]])}" )

	assert len(me["messages"] ) ==(n+1)
	contents = [m.content for m in me["messages"]]

	assert len(set(contents)) == len(contents)




