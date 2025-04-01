"""
Workflow to summarize contect of messages
"""
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, SystemMessage

from assistants.workflows import Workflow, WorkflowState, WorkflowSetup, Node, Edge


class MessagesSummarizationSetup(WorkflowSetup):
	topic_classification_models: Any
	summarization_model: BaseChatModel


class MessagesSummarizationState(WorkflowState):
	messages: list[AnyMessage]

class MessageSummarizationOutput(WorkflowState):
	summary: SystemMessage



class MessagesSummarizationWorkflow(Workflow):
	pass