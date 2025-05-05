from abc import ABC, abstractmethod
from typing import Self, AsyncGenerator, Any

import ray
from pydantic import BaseModel, ConfigDict, model_validator
from ray import ObjectRef, serve
from ray.serve.handle import DeploymentHandle


class AssistantInput(BaseModel):
	model_config = ConfigDict(arbitrary_types_allowed=True)
	summaries: ObjectRef|None=None
	chats: ObjectRef|None=None
	chat_summaries: ObjectRef|None=None

class AssistantChatInput(AssistantInput):
	query:str


class Assistant(BaseModel,ABC):
	"""
	Don't like Workflow, assistant will interact with object_ref.
	Like Workflow, Assistant is also Deployment.
	"""
	model_config = ConfigDict(arbitrary_types_allowed=True)
	input_schema: type[BaseModel]
	input_schema_obj_ref: ObjectRef

	@model_validator(mode="after")
	def put_objects(self)->Self:
		self.input_schema = ray.put(self.input_schema)
		return self


	async def get_input_schema(self)->ObjectRef:
		return self.input_schema

	async def __call__(self, assistant_input: ObjectRef,user_histories:ObjectRef[dict[str,Any]], chat_svc_app_name:str)->AsyncGenerator:
		chat_svc_handle: DeploymentHandle = serve.get_app_handle(chat_svc_app_name)
		async for output in self.process(assistant_input,user_histories, chat_svc_handle):
			yield output

	@abstractmethod
	async def process(self,assistant_input:ObjectRef, chat_svc_app: DeploymentHandle)->AsyncGenerator:
		...


class CasualChatAssistant(Assistant,ABC):
	"""
	Base class for "text in text out" assistant.
	"""

