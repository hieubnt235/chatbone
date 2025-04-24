from langchain_core.embeddings import Embeddings
from langchain_huggingface import HuggingFaceEmbeddings, HuggingFaceEndpointEmbeddings
from langchain_openai import ChatOpenAI




class AIModel:
	"""deployment"""
	pass

class AIModelsProxy:
	"""deployment and ingression"""
	pass



# client
EmbeddingModel= HuggingFaceEndpointEmbeddings
ChatModel = ChatOpenAI

class AIModelsClient:
	"""Can call proxy or other server."""
	pass


