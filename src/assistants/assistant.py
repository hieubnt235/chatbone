from abc import ABC, abstractmethod

from dotenv import find_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

from assistants.workflows import Workflow

# who is compile workflow.

# Process is multiple workflows, monitor, storage,..

# Each workflow scale independently ?
# Who monitor edge? who monitor workflow.

class AssistantSettings(BaseSettings):
	"Setting all workflow, ex: model API..."
	model_config = SettingsConfigDict(env_file= find_dotenv(),
                                      env_file_encoding='utf-8',
                                      extra='ignore',
                                      validate_assignment=True,
                                      validate_default=True,
                                      nested_model_default_partial_update=True,
                                      env_nested_delimiter='__'
                                      )

class Assistant(ABC):
	"""
	Assistant take care of authenticate, storage, validate, stream, preprocess before and after workflow.
	Take care of format messages (audio, image, text,...)
	Monitor process.
	Can have multiples workflow.
	This is the deployment instannce(chatbone, assistant, llms).
	"""
	def __init__(self, workflows: list[Workflow]):
		self._workflows = workflows

	async def __call__(self, *args, **kwargs):
		# Stream the workflow steps
		# Stream the
		# async for wf in self._workflows:


	@abstractmethod
	async def _preprocess(self):
		pass

	@abstractmethod
	async def _post_process(self):
		pass

	@abstractmethod
	async def _mid_process(self):
		pass

	@abstractmethod
	async def _process(self):
		pass




class CasualChatAssistant(Assistant,ABC):
	"""
	Base class for "text in text out" assistant.
	"""

