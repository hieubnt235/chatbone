from langchain_core.embeddings import Embeddings
from ray import serve
from sentence_transformers import SentenceTransformer

"""
support sentence transformer api 
switching between model

client app

Should it be a manager for all AI models ?
How client is use.
"""
bge_small = 'BAAI/bge-small-en-v1.5'  # 384 dim
bge_base = 'BAAI/bge-base-en-v1.5'  # 768 dim
bge_large = 'BAAI/bge-large-en-v1.5'  # 1024 dim


class ChatBoneEmbeddings(Embeddings):


@serve.deployment
class EmbeddingModel:
	def __init__(self):
		self.st = SentenceTransformer(model_name_or_path,
		                              )


class ChatBoneEmbedding(Embedding)