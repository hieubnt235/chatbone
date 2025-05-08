from langchain_core.messages import AnyMessage, SystemMessage

from chatbone.assistants.workflows import WorkflowState


class SummarizationInput(WorkflowState):
	messages: list[AnyMessage]


class SummarizationState(WorkflowState):
	clusters: list[list[AnyMessage]]


class SummarizationOutput(WorkflowState):
	summary: SystemMessage
