from chatbone.assistants.workflows import WorkflowState
from langchain_core.messages import AnyMessage, SystemMessage


class SummarizationInput(WorkflowState):
	messages: list[AnyMessage]

class SummarizationState(WorkflowState):
	clusters: list[list[AnyMessage]]

class SummarizationOutput(WorkflowState):
	summary: SystemMessage