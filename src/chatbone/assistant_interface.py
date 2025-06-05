import asyncio
from abc import ABC
from contextlib import contextmanager
from contextvars import ContextVar
from enum import Enum
from inspect import isclass
from typing import AsyncGenerator, Type, ClassVar, Callable, Self, Any, get_args, Sequence, Literal, Union
from uuid import UUID

import filetype
import ray
import ray.serve.schema as ray_schema
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ConfigDict, model_validator, create_model, Field
from pydantic.fields import FieldInfo
from ray import serve
from ray.exceptions import RayTaskError, TaskCancelledError
from ray.serve.handle import DeploymentHandle
from uuid_extensions import uuid7

from chatbone.broker import WriteStream, ReadStream, UserData, StreamData
from chatbone.settings import OBJ_STORAGE, CONFIG
from utilities.logger import logger

CHATBONE_ASSISTANT_APP_POSTFIX = "_chatbone_assistant"

AssistantDataType_T: tuple[type] = ()
"""Assistant datatype in tuple format, use this to test with isinstance()."""

AssistantDataType_U: Union[type] = None
"""Assistant datatype in union format."""

def assistant_datatype(cls_type):
	global AssistantDataType_T, AssistantDataType_U
	assert isclass(cls_type)
	type_list = list(AssistantDataType_T)
	type_list.append(cls_type)
	AssistantDataType_T = tuple(type_list)
	AssistantDataType_U = AssistantDataType_U|cls_type if AssistantDataType_U is not None else cls_type
	return cls_type

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

@assistant_datatype
class ImageObject(MediaObject):
	type = MediaType.IMAGE
	matcher = filetype.image_match

@assistant_datatype
class VideoObject(MediaObject):
	type = MediaType.VIDEO
	matcher = filetype.video_match

@assistant_datatype
class AudioObject(MediaObject):
	type = MediaType.AUDIO
	matcher = filetype.audio_match

@assistant_datatype
class DocumentObject(MediaObject):
	type = MediaType.DOCUMENT
	matcher = filetype.document_match

@assistant_datatype
class TextStream(BaseModel):
	"""For messages or text stream."""
	id: UUID | None = None
	"""Stream id, all chunks with the same id are belong to others and should be concat. If None, chunk acts like an entire message."""
	chunk: str

@assistant_datatype
class Selection(BaseModel):
	"""This type is for querying user selections."""
	options: dict[str, str]
	"""name:description"""

@assistant_datatype
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

@assistant_datatype
class Status(BaseModel):
	code: AssistantStatusCode
	detail: str | None = None

assistant_datatype_strings = [t.__name__ for t in AssistantDataType_T]

# TODO, support multiple files, with the count depend on user. Dont need to change this code, change media instead.
class AssistantData(StreamData):
	# T means tuple, U means Union
	T:ClassVar[Any] = AssistantDataType_T
	U:ClassVar[Any] = AssistantDataType_U
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
	def _validate_schema(cls,schema:dict[str,Any]):
		for field in schema.values():
			t = field[0] if isinstance(field,Sequence) else field  # extract typehint, ignore default value
			args = get_args(t)
			t = list(args) if args else [t]
			for arg in args:
				if not issubclass(arg, cls.U|None):
					raise ValueError(f"Does not support field definition {field}.Type hint must be AssistantDataType or None.")

	@classmethod
	def _get_model_name(cls):
		return uuid7(as_type="str").replace("-",cls.__name__)

	@classmethod
	def _get_module_name(cls):
		return cls.__module__

	@classmethod
	def create_model(cls, schema: dict[str, Any] ) -> type["AssistantData"]:
		"""
		Create a data model dynamically.
		Args:
			schema: Values of schema must be AssistantDataType, AssistantDataType|None
		Returns:
		"""
		cls._validate_schema(schema)
		return create_model(cls._get_model_name(), __base__= AssistantData,__module__=cls._get_module_name(), **schema)

	@classmethod
	def create_request(cls,schema:dict[str,Any])->"RequestInput":
		"""
		Args:
			schema:
		Returns:
			RequestInput instance.
		"""
		request_model = cls.create_model(schema)
		uid = UUID(request_model.__name__.replace(super().__class__.__name__,"-"))
		return RequestInput(id=uid,data_type=request_model)

class RequestInput(StreamData):
	"""This class is used for request input from user. User also send this class instance as response."""
	model_config = ConfigDict(arbitrary_types_allowed=True,validate_assignment=True)
	id: UUID = Field(frozen=True)
	data_type: Type[AssistantData] = Field(frozen=True)
	data: AssistantData|None=None

	@model_validator(mode="after")
	def check_data(self)->Self:
		assert isinstance(self.data,(self.data_type,None)) # None means no response.
		return self

assistant_streams: ContextVar[tuple[WriteStream, ReadStream]] = ContextVar("assistant_streams")

@contextmanager
def _stream_cm( write_stream:ReadStream, read_stream:WriteStream):
	token = assistant_streams.set((WriteStream, ReadStream))
	yield token
	assistant_streams.reset(token)

def format_doc(func):
	func.__doc__ = func.__doc__.format(assistant_datatype_strings= assistant_datatype_strings)
	return func

@format_doc
async def request_user_input(request_schema:dict[str,tuple[str,str,Literal["optional","required"]]])->AssistantData|None:
	"""
	Request some input object from the user with specified object name, object type, and description.

	Args:
		request_schema: a dictionary with keys as a string type represent the short name of the request object, for example "math_document", "cat_picture".
		 Values of a dict, according to the keys, is tuple of length 3, both are strings.
		  - The first value of the tuple is type of requested object, it must be in this list: {assistant_datatype_strings}.
		  - The second is the text represent description or hint to show to user. If description is not given, it must be the blank string "".
		  - The third must be "optional" or "require", user has only two options, give all the object marked as "require" or refuse to give any information.

	Returns:
		AssistantData object containing all user inputs, or None if user refuse to give.
	"""
	def _make_field():
		for k,v in request_schema.items():
			t, desc, opt = v
			field:FieldInfo = Field()
			if (dtype:= globals().get(t)) is None:
				raise ValueError(f"Does not support type '{t}'.")
			if opt == "optional":
				dtype = dtype|None
				field.default = None
			elif opt!="required":
				raise ValueError("Third value of tuple must be 'optional' or 'required'.")
			field.description = desc
			request_schema[k] = (dtype,field)

	schema = await asyncio.to_thread(_make_field)
	request_input: RequestInput = await asyncio.to_thread(AssistantData.create_request,schema)

	write_stream, read_stream = assistant_streams.get()
	logger.info(f"Sending input request to user through stream with key '{write_stream.key}'...")
	stream_id = await write_stream.write(request_input)
	logger.info(f"Sent input request to user, request stored with stream id '{stream_id}'.")

	# wait for get valid requested input object, or until setting.config.request_user_input_timeout
	async def _wait_task():
		try:
			async for data in read_stream.bind("$"):
				for d in data:
					if isinstance(data,RequestInput):
						if data.id == request_input.id:
							# Note: return only the first reach valid data came after the time of waiting, it's enough I thought. =))
							return data.data
						logger.warning(f"Got RequestInput object but not match with the id of the object sent. Ignore and continue waiting.")
			raise RuntimeError(f"This Exception is not expected to raise in run time, the stream some how be broken while iterating.")
		except asyncio.CancelledError:
			logger.debug("The task of waiting for requested user input is cancelled.")
			return None
	try:
		logger.info(f"Waiting for stream with key '{read_stream.key}' for requested input object.")
		return await asyncio.wait_for(_wait_task(),CONFIG.request_user_input_timeout)
	except TimeoutError:
		logger.info("Not received any requested input object for the amount of time, reached timeout.")
		return None


class BaseAssistant(ABC):
	"""This class is the base class of assistant app."""
	graph: CompiledStateGraph = None

	def __init__(self):
		assert isinstance(self.graph,CompiledStateGraph)
		self.schema: Type[AssistantData] = self.graph.builder.schema
		assert issubclass(self.schema, AssistantData)

	async def get_schema(self) -> Type[AssistantData]:
		return self.schema

	@classmethod
	async def get_app(cls) -> serve.Application:
		return serve.deployment(cls)().bind()

	async def handle_cancellation(self):
		"""Optional handling after cancellation."""

	async def _graph_stream(self, data: AssistantData)->AsyncGenerator[AssistantData]:
		async for chunk in self.graph.astream(data):
			if not isinstance(chunk,AssistantData):
				raise ValueError("The returned of graph is not the instance of 'AssistantData'. ")
			yield chunk

	async def __call__(self, data_input: AssistantData, write_stream: WriteStream, read_stream: ReadStream):
		try:
			assert isinstance(data_input,self.schema)
			with _stream_cm(write_stream, read_stream) as token:
				async for data in self._graph_stream(data_input):
					await write_stream.write(data)

		except asyncio.CancelledError as e:
			await write_stream.write(AssistantData(status=Status(code=AssistantStatusCode.CANCELING)))
			await self.handle_cancellation()
			await write_stream.write(AssistantData(status=Status(code=AssistantStatusCode.CANCELED)))
		except Exception as e:
			await write_stream.write(AssistantData(status=Status(code=AssistantStatusCode.ERROR, detail=str(e))))
		finally:
			await write_stream.write(AssistantData(status=Status(code=AssistantStatusCode.DONE)))

class AssistantInterface:
	"""Chat app uses this class to communicate with assistant app.
	"""

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