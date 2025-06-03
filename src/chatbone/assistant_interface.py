import asyncio
from abc import ABC, abstractmethod
from enum import Enum
from typing import AsyncGenerator, Type, ClassVar, Callable, Self, Any, get_args, Sequence, Literal
from uuid import UUID

import filetype
import ray
import ray.serve.schema as ray_schema
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ConfigDict, model_validator, create_model
from ray import serve
from ray.exceptions import RayTaskError, TaskCancelledError
from ray.serve.handle import DeploymentHandle

from chatbone.broker import WriteStream, ReadStream, UserData, StreamData
from chatbone.settings import OBJ_STORAGE
from utilities.logger import logger

CHATBONE_ASSISTANT_APP_POSTFIX = "_chatbone_assistant"


class MediaType(str, Enum):
	IMAGE = "IMAGE"
	VIDEO = "VIDEO"
	AUDIO = "AUDIO"
	DOCUMENT = "DOCUMENT"


class MediaObject(BaseModel):
	"""Assistant input is the collection of these objects. User must give all required media object to call assistant."""
	type: ClassVar[MediaType]
	matcher: ClassVar[Callable[..., filetype.Type]]
	model_config = ConfigDict(frozen=True)

	object_name: str
	mime: str

	@classmethod
	async def object_validate(cls, object_name: str, remove_if_validate_fail: bool = True) -> Self:
		"""
		Validate the object stored in server.
		Args:
			object_name:
			remove_if_validate_fail:
		Raises:
			TypeError: If the object's type is not a correct type.
		Returns: MediaObject instance
		"""
		magic = await OBJ_STORAGE.get_object(object_name, length=8192)
		try:
			mime = await cls.get_mime(magic)
			return cls(object_name=object_name, mime=mime)
		except TypeError as e:
			if remove_if_validate_fail:
				await OBJ_STORAGE.remove_object(object_name)
			raise

	@classmethod
	async def put_object(cls, object_name: str, data) -> Self:
		"""
		Put the raw bytes data object on storage.
		Args:
			object_name:
			data:
		Raises:
			TypeError: If the object is not supported type.
		Returns: MediaObject instance
		"""
		mime = await cls.get_mime(data)
		await OBJ_STORAGE.put_object(object_name, data, mime)
		return cls(object_name=object_name, mime=mime)

	@classmethod
	async def get_mime(cls, data) -> str:
		"""
		Get mime of the "bytes" data.
		Args:
			data:
		Raises:
			TypeError: If data is not supported.
		Returns:
			mime string.
		"""
		if (m := await asyncio.to_thread(cls.matcher(data, cls.type))) is None:
			raise TypeError(f"Object is not instance of type {cls.type}.")
		return m.mime

	async def get_object(self) -> bytes:
		"""Get the binary object from server."""
		return await OBJ_STORAGE.get_object(self.object_name)

	async def remove_object(self):
		"""Remove the binary object from server"""
		return await OBJ_STORAGE.remove_object(self.object_name)


class ImageObject(MediaObject):
	type = MediaType.IMAGE
	matcher = filetype.image_match


class VideoObject(MediaObject):
	type = MediaType.VIDEO
	matcher = filetype.video_match


class AudioObject(MediaObject):
	type = MediaType.AUDIO
	matcher = filetype.audio_match


class DocumentObject(MediaObject):
	type = MediaType.DOCUMENT
	matcher = filetype.document_match


class TextStream(BaseModel):
	"""For messages or text stream."""
	id: UUID | None = None
	"""Stream id, all chunks with the same id are belong to others and should be concat. If None, chunk acts like an entire message."""
	chunk: str


class Selection(BaseModel):
	"""This type is for querying user selections."""
	options: dict[str, str]
	"""name:description"""


class UserPreviousData(BaseModel):
	"""This input type should be set by service, not by user."""
	userdata: UserData | None = None
	chat_session_id: UUID | None = None


class AssistantStatusCode(str, Enum):
	START = "start"
	DONE = "done"
	SUCCESS="success"
	ERROR="error"
	CANCELED = "canceled"
	CANCELING = "canceling"
	PROCESSING = "processing"


class Status(BaseModel):
	code: AssistantStatusCode
	detail: str | None = None

class InputRequest(BaseModel):
	id: UUID
	types: Type["AssistantData"]

class InputResponse(BaseModel):
	id: UUID
	data: "AssistantData"

# TODO, support multiple files, with the count depend on user. Dont need to change this code, change media instead.
class AssistantData(StreamData):
	# T means tuple, U means Union
	T:ClassVar[Any] = (ImageObject, VideoObject, AudioObject, DocumentObject, TextStream, Selection, UserPreviousData,Status, InputRequest, InputResponse)
	U:ClassVar[Any] = ImageObject | VideoObject | AudioObject | DocumentObject | TextStream | Selection | UserPreviousData | Status| InputRequest| InputResponse
	status: Status|None=None

	@model_validator(mode='before')
	@classmethod
	def check_schema(cls,data:dict):
		for field in cls.model_fields.values():
			ann = field.annotation
			args = get_args(ann)
			t = list(args) if args else [args]
			for arg in args:
				if not issubclass(arg, cls.U | None):
					raise ValueError(
						f"Does not support field definition {field}.Type hint must be AssistantDataType or None.")
		return data

	@classmethod
	def create_model(cls,model_name: str, schema: dict[str, Any] ) -> type[Self]:
		"""
		Create a data model dynamically.
		Args:
			model_name: class name of a pydantic model, it should be PascalCase
			schema: Values of schema must be AssistantDataType, AssistantDataType|None
		Returns:
		"""
		for field in schema.values():
			t = field[0] if isinstance(field,Sequence) else field  # extract typehint, ignore default value
			args = get_args(t)
			t = list(args) if args else [t]
			for arg in args:
				if not issubclass(arg, cls.U|None):
					raise ValueError(f"Does not support field definition {field}.Type hint must be AssistantDataType or None.")

		return create_model(model_name, __base__= AssistantData, **schema)

	@classmethod
	def create_request(cls, model_name: str, schema: dict[str, Any])->Self:
		pass



class BaseAssistant(ABC):
	"""This class is the base class of assistant app."""
	graph: CompiledStateGraph = None

	def __init__(self):
		assert isinstance(self.graph,CompiledStateGraph)
		self.schema: Type[AssistantData] = self.graph.builder.schema
		assert isinstance(self.schema, AssistantData)

	async def get_schema(self) -> Type[AssistantData]:
		return self.schema

	@classmethod
	async def get_app(cls) -> serve.Application:
		return serve.deployment(cls)().bind()

	async def graph_stream(self, data: AssistantData)->AsyncGenerator[AssistantData,AssistantData]:
		async for chunk in self.graph.astream(data):
			yield chunk

	async def handle_cancellation(self):
		pass

	async def _wait_for_input_response(self, input_request: AssistantData, read_stream: ReadStream):
		pass

	async def __call__(self, data: AssistantData, write_stream: WriteStream, read_stream: ReadStream):
		try:
			assert type(data) is self.schema
			async for chunk in self.graph_stream():
				chunk.status = Status(code=AssistantStatusCode.PROCESSING)
				await write_stream.write(chunk)
				if input_requests:=chunk.get_request_input:
					await self._wait_for_input_response()


		except asyncio.CancelledError as e:
			await write_stream.write(AssistantData(status=Status(code=AssistantStatusCode.CANCELING)))
			await self.handle_cancellation()
			await write_stream.write(AssistantData(status=Status(code=AssistantStatusCode.CANCELED)))
		except Exception as e:
			await write_stream.write(AssistantData(status=Status(code=AssistantStatusCode.ERROR, detail=str(e))))
		finally:
			await write_stream.write(AssistantData(status=Status(code=AssistantStatusCode.DONE)))


class AssistantInterface:
	"""Chat app uses this class to communicate with assistant app."""

	def __init__(self):
		self._handle: DeploymentHandle = None
		self._assistant_name: str = None

	@staticmethod
	async def get_assistant_names() -> list[str]:
		"""
		Get all current healthy assistant app names
		Returns: list of assistant app name as string.
		"""
		await asyncio.to_thread(AssistantInterface._get_healthy_assistant_app_names)

	@staticmethod
	async def get_assistant_schema(assistant_name: str) -> Type[AssistantData]:
		handle: DeploymentHandle = await AssistantInterface.get_assistant_app_handle(assistant_name)
		schema = await handle.get_schema.remote()
		assert issubclass(schema, AssistantData)
		return schema

	@staticmethod
	async def get_assistant_app_handle(assistant_name: str) -> DeploymentHandle:
		return await asyncio.to_thread(AssistantInterface._get_assistant_app_handle, assistant_name)

	@staticmethod
	async def call(name, data: AssistantData, write_stream: WriteStream, read_stream: ReadStream) -> asyncio.Task:
		"""
		Call assistant and return the asyncio.Task
		Args:
			name:
			data:
			write_stream:
			read_stream:

		Returns:
			asyncio.Task: This can be used for cancel the call task.
		"""
		handle = await AssistantInterface.get_assistant_app_handle(name)
		task = asyncio.create_task(AssistantInterface._call_task(handle, write_stream, read_stream))
		return task

	@staticmethod
	async def _call_task(handle: DeploymentHandle, data: AssistantData, write_stream: WriteStream, read_stream: ReadStream):
		task = handle.remote(data, write_stream, read_stream)
		try:
			await task
		except asyncio.CancelledError:
			ray.cancel(task)
			try:
				await task
			except RayTaskError as e:
				if not isinstance(e.cause,TaskCancelledError):
					raise e

	async def send(self, data: AssistantData):
		pass

	async def receive(self) -> AsyncGenerator[AssistantData, None]:
		pass

	@staticmethod
	def _get_assistant_app_handle(assistant_name: str) -> DeploymentHandle:
		assert assistant_name.endswith(CHATBONE_ASSISTANT_APP_POSTFIX)
		return serve.get_app_handle(assistant_name)

	@staticmethod
	def _get_healthy_assistant_app_names() -> list[str]:
		assistants = []
		apps = serve.status().applications
		for name, status in apps.items():
			if not name.endswith(CHATBONE_ASSISTANT_APP_POSTFIX):
				continue
			if status.status == ray_schema.ApplicationStatus.RUNNING:
				for deployment_status in status.deployments.values():
					if deployment_status.status == ray_schema.DeploymentStatus.HEALTHY and deployment_status.status_trigger == ray_schema.DeploymentStatusTrigger.CONFIG_UPDATE_COMPLETED and deployment_status.replica_states == ray_schema.ReplicaState.RUNNING:
						assistants.append(name)
			else:
				logger.warning(f"Something maybe not as expected with assistant :\n{apps}")


if __name__ == "__main__":
	import cloudpickle
	from pathlib import Path
	import time
	start = time.time()
	# Test create assistant data model


	if not Path("instance").exists():
		print("dump")

		model = AssistantData.create_model("MyModel", dict(picture=ImageObject, choose=(Selection | None, None),))
		with open("instance", mode="wb") as f:
			obj = model(picture=ImageObject(object_name="as", mime="sa"),
			            # choose=Selection(options={"asd": "sda"}),
			            status=Status(code="done"))
			cloudpickle.dump(obj, f)
		with open("class",mode="wb") as f:
			cloudpickle.dump(model,f)

	with open("instance", mode="rb") as f:
		with open("class",mode="rb") as f1:
			obj = cloudpickle.load(f)
			print(type(obj))
			for data in obj:
				print(data)
			print(obj.__class__.model_fields)

			cls:BaseModel = cloudpickle.load(f1)
			print(cls.__name__, cls.model_fields)

	print(time.time()-start)

	##