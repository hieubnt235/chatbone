from typing import Callable, Coroutine

from chatbone.assistants.utils import messages2contents, cluster_messages, compose_messages
from chatbone.assistants.workflows import Node
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage

from .state import SummarizationState, SummarizationInput, SummarizationOutput


class ClusterNode(Node):
	"""
	Receive a state and return the list[int] of index label of topic for each message.
	"""
	embeddings: Embeddings
	clusterer: Callable[...,Coroutine[ list[list[float]], list[ list[int]] ] ]
	"""Function that take a list of embeddings, return an list of list of index. Each internal list represent the cluster
	 of messages."""

	async def __call__(self, state: SummarizationInput)->SummarizationState:
		contents:list[str] = await messages2contents(state.messages)
		clusters = await self.clusterer( await self.embeddings.aembed_documents(contents) )
		result=await cluster_messages(clusters, state.messages)

		return SummarizationState(clusters=result)


class SummaryNode(Node):
	summary_model: BaseChatModel
	prompt:str = """
	Here is the conversation between user and assistant. Please make a summary of this conversation.
	You can make more than one summary if the number of topics is more than one. Please list the summaries by indexes. 
	
	Note: If the messages is too discreate or not related to each others, make one simple summary with some 
	 keywords about discrete messages."""

	summary_format:str="""The summary of previous chat is \n{}. You can use it to take information of 
	current context or current user."""

	async def __call__(self, state: SummarizationState) -> SummarizationOutput:
		first_msg = SystemMessage(content=self.prompt)
		for c in state.clusters:
			c.insert(0,first_msg)
		summaries = await self.summary_model.abatch(state.clusters)
		contents = await messages2contents(summaries)
		return SummarizationOutput(summary= SystemMessage(content=await compose_messages(contents,self.summary_format)))

__all__ = ["ClusterNode",
           "SummaryNode"]