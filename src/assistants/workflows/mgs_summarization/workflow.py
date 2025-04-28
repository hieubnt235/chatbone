"""
Workflow to summarize content of messages.
"""

from assistants.workflows import WorkflowSetup
from .node import ClusterNode

cluster_node = ClusterNode(name="cluster_node",
                           embeddings=)

class MessagesSummarizationSetup(WorkflowSetup):
	top_k:int = 3

