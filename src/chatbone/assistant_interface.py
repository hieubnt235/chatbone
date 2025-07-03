import asyncio
import dataclasses
import os
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta, datetime
from enum import Enum
from types import NoneType, UnionType
from typing import (
    AsyncGenerator,
    Type,
    ClassVar,
    Callable,
    Self,
    Any,
    get_args,
    Sequence,
    Literal,
    Annotated,
    get_type_hints,
    get_origin,
    Generator,
    Awaitable,
    AsyncIterator,
)
from uuid import UUID

import filetype
import ray.serve.schema as ray_schema
from filetype import match
from filetype.types import document, IMAGE, VIDEO, AUDIO, archive
from filetype.types.image import Jpeg
from pydantic import (
    BaseModel,
    ConfigDict,
    model_validator,
    create_model,
    Field,
    TypeAdapter,
    ValidationError,
    NonNegativeInt,
)
from pydantic.fields import FieldInfo, PrivateAttr
from ray import serve
from ray.exceptions import TaskCancelledError
from ray.serve._private.common import ReplicaState
from ray.serve.exceptions import RequestCancelledError
from ray.serve.handle import DeploymentHandle
from uuid_extensions import uuid7

from chatbone.broker import (
    StreamData,
    StreamPair,
    DisplayMessage,
    DataSegment,
    UserData,
    ChatSessionData,
)
from chatbone.settings import OBJ_STORAGE, CONFIG
from utilities.func import utc_now
from utilities.logger import logger
from utilities.misc import UniversalLock
from utilities.settings.objest_storage import ObjectStorageSettings

CHATBONE_ASSISTANT_APP_PREFIX = "<Chatbone_Assistant>"
CHATBONE_ASSISTANT_APP_POSTFIX = "<Chatbone_Assistant>"


class Only(str, Enum):
    OUTPUT = "output"
    INPUT = "input"
    NONE = "none"


class BaseAssistantType(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    only: ClassVar[Only] = Only.NONE
    """User cannot provide the class has only = "output". Or assistant developer cannot send the class with only="input". """

    to_user: bool = True
    """Data hold this status is intentionally for user. Set it false if data is just use to saved, not to show.
    This attribute only has affect in AS2CS, will be ignore in CS2AS."""


class MediaType(str, Enum):
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    AUDIO = "AUDIO"
    DOCUMENT = "DOCUMENT"


class InvalidFileTypeException(Exception):
    pass


class InvalidFileExtension(InvalidFileTypeException):
    def __init__(self, m="", allowed_ex=None, received_ex=None, filename=None):
        self.al_ex = allowed_ex
        self.re_ex = received_ex
        self.filename = filename
        if self.al_ex:
            m += f"Allowed extension: {allowed_ex}. "
        if self.re_ex:
            m += f"Got {received_ex}. "
        super().__init__(m)


class InvalidBinaryFile(InvalidFileTypeException):
    pass


class MediaObject(BaseAssistantType):
    """Assistant input is the collection of these objects. User must give all required media object to call assistant.
    Notes:
            1. The get_upload_url
    """

    object_storage: ClassVar[ObjectStorageSettings] = OBJ_STORAGE
    type: ClassVar[MediaType] = None
    matchers: ClassVar[Sequence[filetype.Type]] = None
    mimes: ClassVar[list[str]] = None
    extensions: ClassVar[list[str]] = None

    model_config = ConfigDict(frozen=True)
    object_name: str
    mime: str

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        assert cls.type in MediaType
        cls.mimes = []
        cls.extensions = []
        for m in cls.matchers:
            assert isinstance(m, filetype.Type)
            cls.mimes.append(m.mime)
            cls.extensions.append(m.extension)

    @classmethod
    async def get_upload_url(
        cls,
        object_name: str,
        extension: str = None,
        expires: timedelta = timedelta(days=7),
        *,
        tagging: dict[str, str] | None = None,
    ) -> str:
        """
        This method will infer content-type using filename extension (if extension not provided) and the class.type .

        Args:
                object_name:
                expires:
                extension:
                tagging:
        Raises:
                InvalidFileExtension: When cannot infer extension or extension is not supported.
        Returns:
                Upload url. Call 'PUT' to push object to storage server
        """

        def _validate_extension() -> str:
            if extension is None:
                if "." in object_name:
                    ex = object_name.rsplit(".", 1)[-1]
                else:
                    raise InvalidFileExtension(
                        f"Cannot infer extension from object name. There is no separator '.' "
                    )
            else:
                assert isinstance(extension, str)
                ex = extension
            for i, ext in enumerate(cls.extensions):
                if ex == ext:
                    return cls.mimes[i]
            raise InvalidFileExtension(
                "Extension is not supported. ", cls.extensions, ex
            )

        mime = await asyncio.to_thread(_validate_extension)
        response_headers = {"response-content-type": "image/png"}
        return await OBJ_STORAGE.get_upload_url(
            object_name,
            expires,
            response_headers=response_headers,
            content_type=mime,
            tagging=tagging,
        )

    @classmethod
    async def validate_object(
        cls, object_name: str, remove_if_validate_fail: bool = True
    ) -> Self:
        """
        Validate the object stored in server. This method should be call after object is put to server.
        Args:
                object_name:
                remove_if_validate_fail:
        Raises:
                InvalidBinaryFile: If the object's type is not a correct type.
        Returns: MediaObject instance
        """
        magic = await OBJ_STORAGE.get_object(object_name, length=8192)
        try:
            mime = await cls.get_mime(magic)
            return cls(object_name=object_name, mime=mime)
        except InvalidBinaryFile as e:
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
                InvalidBinaryFile: If the object is not supported type.
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
                InvalidBinaryFile: If data is not supported.
        Returns:
                mime string.
        """
        if (m := await asyncio.to_thread(match, data, cls.matchers)) is None:
            raise InvalidBinaryFile(
                f"Binary object is not instance of type {cls.type}. No matter of its extension."
            )
        return m.mime

    async def get_preview_url(self, expires: timedelta = timedelta(days=7)):
        return await OBJ_STORAGE.get_download_url(
            self.object_name,
            expires,
            response_headers={  # DEFAULT disposition is inline.
                "response-content-disposition": "inline",
                "response-content-type": self.mime,
            },
        )

    async def get_object(self) -> bytes:
        """Get the binary object from server."""
        return await OBJ_STORAGE.get_object(self.object_name)

    async def remove_object(self):
        """Remove the binary object from server"""
        return await OBJ_STORAGE.remove_object(self.object_name)


# noinspection PyTypeChecker
AssistantDataType_T: tuple[Type[BaseAssistantType]] = ()
"""Assistant datatype in tuple format, use this to test with isinstance()."""

AssistantDataType_U: Type[BaseAssistantType] = BaseAssistantType
"""Assistant datatype in union format."""

AnyMediaObject: Type[MediaObject] = MediaObject
"""Media object union."""


def assistant_datatype(cls_type):
    """Decorator to assign assistant datatype.
    This type is the one stream to app, so it should be pickleable and clear purpose to show to user.
    Or to be user input type.
    """
    global AssistantDataType_T, AssistantDataType_U, AnyMediaObject
    assert issubclass(cls_type, BaseAssistantType) and cls_type != BaseAssistantType

    if AssistantDataType_U == BaseAssistantType:
        AssistantDataType_U = cls_type
    else:
        AssistantDataType_U = AssistantDataType_U | cls_type

    AssistantDataType_T = AssistantDataType_T + (cls_type,)

    if issubclass(cls_type, MediaObject):
        if AnyMediaObject == MediaObject:
            AnyMediaObject = cls_type
        else:
            AnyMediaObject = AnyMediaObject | cls_type
    return cls_type


@assistant_datatype
class ImageObject(MediaObject):
    # TODO: the filetype library is broke, should fork and make a new one.
    class _Jpeg(filetype.Type):
        EXTENSION = "jpeg"
        MIME = "image/jpeg"

        def __init__(self):
            self._jpeg = Jpeg()
            super().__init__(self.MIME, self.EXTENSION)

        def match(self, buf):
            return self._jpeg.match(buf)

    type = MediaType.IMAGE
    matchers = IMAGE + (_Jpeg(),)


@assistant_datatype
class VideoObject(MediaObject):
    type = MediaType.VIDEO
    matchers = VIDEO


@assistant_datatype
class AudioObject(MediaObject):
    type = MediaType.AUDIO
    matchers = AUDIO


@assistant_datatype
class DocumentObject(MediaObject):
    type = MediaType.DOCUMENT
    matchers = (
        document.Doc(),
        document.Docx(),
        document.Ppt(),
        archive.Pdf(),
        archive.Epub(),
    )  # TODO: support txt


@dataclasses.dataclass
class InputFilter:
    regex_string: str
    allow: bool = True
    replacement_string: str = ""
    multiline: bool = False
    case_sensitive: bool = True
    unicode: bool = False
    dot_all: bool = False


@assistant_datatype
class Text(BaseAssistantType):
    input_filter: ClassVar[InputFilter | None] = None
    """Filter the input of user. This is prevent user typing"""

    input_validator: ClassVar[Callable[[str], str | None | Awaitable[str | None]]] = (
        lambda v: v
    )

    content: str

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        if cls.input_filter:
            assert isinstance(cls.input_filter, InputFilter)


@assistant_datatype
class BaseSelection(BaseAssistantType):
    __adapter: ClassVar[TypeAdapter] = TypeAdapter(dict[str, str | None])

    only = Only.INPUT
    options: ClassVar[dict[str, str | None]] = None
    """option dict, where keys are option keys and values are description to show to user."""
    _options: ClassVar[list[str]] = None
    selection: str

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        _ = cls.__adapter.validate_python(cls.options)
        cls._options = list(cls.options.keys())

    @classmethod
    @model_validator(mode="before")
    def _check_selection(cls, v: dict) -> Self:
        if (val := v["selection"]) not in cls._options:
            raise ValidationError(f"'selection' must be in {cls._options}. Got {val}")
        return v


assistant_datatype_strings = [t.__name__ for t in AssistantDataType_T]


# NOT SUPPORT ANYMORE
# @assistant_datatype
class BaseForm(BaseAssistantType):
    """For all arbitrary basic type (int, float,str,bool) and their container, nesting,...
    NOTE: NOT SUPPORT ANYMORE.
    """

    Supported_T: ClassVar[Any] = (
        str,
        int,
        float,
        bool,
    )

    @classmethod
    def fields(cls) -> Generator[tuple[str, FieldInfo], None, None]:
        for name, field in cls.model_fields.items():
            if get_origin(field.annotation) == ClassVar or name == "to_user":
                continue
            else:
                yield name, field

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        for name, field in cls.model_fields.items():
            ann = field.annotation
            if get_origin(ann) == ClassVar or name == "to_user":
                continue
            if field.metadata:
                ann = Annotated[ann, *field.metadata]
            cls._validate_type(ann)

    @classmethod
    def _validate_type(cls, ann):
        org = get_origin(ann)
        if org == Annotated:
            cls._validate_type(get_args(ann)[0])
        if org is None:
            if ann is None:
                raise ValueError(
                    f"Does not support standalone None like 'list[None]', should be 'list[int|None]' for example."
                )
            if ann not in cls.Supported_T:
                raise ValueError(
                    f"Only accept types {cls.Supported_T} or composition of them. Got '{ann}'."
                )
        elif org in (list, UnionType, Literal, tuple, dict):
            new_anns = list(get_args(ann))
            if NoneType in new_anns:
                assert len(new_anns) > 1
                new_anns.remove(NoneType)
            for new_ann in new_anns:
                new_ann = type(new_ann) if org == Literal else new_ann
                cls._validate_type(new_ann)


# noinspection PyTypeChecker
class AssistantData(StreamData, DisplayMessage):

    model_config = ConfigDict(validate_default=True, validate_assignment=True)
    _is_input_schema: ClassVar[bool] = False
    _default_exclude_attrs: ClassVar[list[str]] = list(
        DisplayMessage.model_fields.keys()
    )
    """Attributes from DisplayMessage"""

    _exclude_attrs: ClassVar[list[str]] = None

    # T means tuple, U means Union
    T: ClassVar[Any] = AssistantDataType_T
    U: ClassVar[Any] = AssistantDataType_U

    _chat_context_id: UUID = PrivateAttr(default_factory=uuid7)
    """All data including input, status code, request input and output data in one chat unique uuid.
    This is set by app, not user or dev.
    """
    _created_at: datetime = PrivateAttr(default_factory=utc_now)

    @property
    def chat_context_id(self):
        assert self._chat_context_id is not None
        return self._chat_context_id

    @property
    def created_at(self):
        assert self._created_at is not None
        return self._created_at

    @classmethod
    def iter_data_fields(cls) -> Generator[tuple[str, FieldInfo], None, None]:
        for name, field_info in cls.model_fields.items():
            if (
                get_origin(field_info.annotation) == ClassVar
                or name in cls._exclude_attrs
            ):
                continue
            else:
                yield name, field_info

    @classmethod
    def create_model(
        cls, model_schema: dict[str, Any], doc: str | None = None
    ) -> Type["AssistantData"]:
        """
        todo: is this method necessary? or just directly inherit ? NO IT IS USED TO DYNAMICALLY GEN BY LLM.
        Create a data model dynamically.
        Args:
                model_schema: dictionary with keys as name and
                doc
        Returns:
                Instance of a subclass of AssistantData
        """
        cls._validate_model(model_schema)
        return create_model(
            cls._get_model_name(),
            __base__=cls,
            __module__=cls._get_module_name(),
            __doc__=doc,
            **model_schema,
        )

    @classmethod
    def __pydantic_init_subclass__(cls):
        cls._exclude_attrs = cls._exclude_attrs or []
        if cls._default_exclude_attrs is not None:
            cls._exclude_attrs.extend(cls._default_exclude_attrs)
        fields: dict[str, FieldInfo] = cls.model_fields
        for name, field_info in fields.items():
            ann = field_info.annotation
            if (
                get_origin(field_info.annotation) == ClassVar
                or name in cls._exclude_attrs
            ):
                continue
            if field_info.metadata:
                ann = Annotated[ann, *field_info.metadata]
            cls._validate_schema(name, ann)

    @classmethod
    def _validate_schema(cls, name: str, ann: Type[Any]):
        # General supported type examples: ImageObject, list[ImageObject]|VideoObject, ImageObject|VideoObject|None
        # validate recursively through list.
        org = get_origin(ann)
        if org in (
            None,
            Annotated,
        ):  # Annotated is only supported for the annotation type in cls.T
            if not ann in cls.T and not issubclass(ann, cls.T):
                m = f"Does not support field annotation '{ann.__name__}' of '{cls.__name__}.{name}'.Type hint must be in {[t.__name__ for t in cls.T]}."
                raise ValueError(m)
            if cls._is_input_schema:
                assert issubclass(ann, BaseAssistantType)
                if ann.only == Only.OUTPUT:
                    m = f"Input schema can not contain output-only type '{ann.__name__}' of {cls.__name__}.{name}'."
                    raise ValueError(m)
        else:
            if issubclass(org, (list, UnionType)):
                new_anns = list(get_args(ann))
                if NoneType in new_anns:
                    assert len(new_anns) > 1
                    new_anns.remove(NoneType)
                for ann in new_anns:
                    cls._validate_schema(name, ann)

    @classmethod
    def _get_model_name(cls):
        return uuid7(as_type="str").replace("-", cls.__name__)

    @classmethod
    def _get_module_name(cls):
        return cls.__module__

    @classmethod
    def _validate_model(cls, schema: dict[str, Any]):
        for name, field in schema.items():
            # If not tuple, create simple field for compatible with the latest pydantic versions. While old version not support non-tuple.
            if not isinstance(field, Sequence):
                schema[name] = (field, Field())
            ann = schema[name][0]  # extract annotation, ignore default value
            cls._validate_schema(name, ann)

    @classmethod
    def _create_request(
        cls, schema: dict[str, Any], doc: str | None = None
    ) -> "RequestInput":
        """
        Args:
                schema:
                doc:
        Returns:
                RequestInput instance.
        """
        request_model = cls.create_model(schema, doc=doc)
        uid = UUID(request_model.__name__.replace(super().__class__.__name__, "-"))
        return RequestInput(id=uid, data_type=request_model)


class ContextCollector:
    """ """

    # todo


class AssistantInputData(AssistantData):
    # class attrs
    _exclude_attrs = ["context", "username"]
    _is_input_schema = True

    _username: str
    _context: Any = None
    """Get from context collector"""

    @property
    def username(self) -> str:
        return self._username

    @property
    def context(self):
        return self._context


class AssistantStatusCode(str, Enum):
    START = "start"
    DONE = "done"
    SUCCESS = "success"
    ERROR = "error"
    CANCELED = "canceled"
    CANCELING = "canceling"
    PROCESSING = "processing"


class Status(BaseModel):
    code: AssistantStatusCode
    detail: str | None = None


class AssistantOutputData(AssistantData):
    _exclude_attrs = ["stream_place"]
    stream_place: int = 0

    # These are set by app.
    _assistant_name: str | None = PrivateAttr(None)
    _status: Status | None = PrivateAttr(None)
    _chunk_order: NonNegativeInt | None = PrivateAttr(None)

    @property
    def status(self):
        assert self._status is not None
        return self._status

    @property
    def assistant_name(self):
        return self._assistant_name

    @property
    def chunk_order(self):
        assert self._chunk_order is not None
        return self._chunk_order


class RequestInput(StreamData):
    """This class is used for request input from user. User also send this class instance as response.
    Note: This class is used when assistant request input from user while running.
    """

    request_prompt: str  # todo: formatted type string like md or html

    request_schema: ClassVar[type[AssistantInputData]] = None

    model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)

    id: UUID = Field(frozen=True, default_factory=uuid7)
    """The receiver will check for this id to know if it is a response for the request"""

    _data: AssistantInputData | None = None

    @property
    def data(self):
        assert isinstance(self._data, AssistantInputData)
        return self._data

    def set_response_data(self, data_response: Any):
        self._data = self.request_schema.model_validate(data_response)

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        assert issubclass(cls.request_schema, AssistantInputData)


class AssistantStreamContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    stream_pair: StreamPair
    chat_context_id: UUID
    cs_id: UUID
    userdata: UserData

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._lock = UniversalLock() # for pickable


assistant_stream_context: ContextVar[AssistantStreamContext] = ContextVar(
    "assistant_stream_context"
)


@contextmanager
def _stream_cm(context: AssistantStreamContext):
    token = assistant_stream_context.set(context)
    logger.debug(f"Context:\n" f"{repr(context)}")
    yield token
    assistant_stream_context.reset(token)


# Note: request_user_input is tool call, so it should have nice docstring, also argument should be serialized as
# type string for LLM can init them.


def format_doc(func):
    func.__doc__ = func.__doc__.format(
        assistant_datatype_strings=assistant_datatype_strings
    )
    return func


@format_doc
async def request_user_input(
    request_schema: dict[str, tuple[str, str, Literal["optional", "required"]]],
) -> AssistantData | None:
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
        for k, v in request_schema.items():
            t, desc, opt = v
            field: FieldInfo = Field()
            if (dtype := globals().get(t)) is None:
                raise ValueError(f"Does not support type '{t}'.")
            if opt == "optional":
                dtype = dtype | None
                field.default = None
            elif opt != "required":
                raise ValueError(
                    "Third value of tuple must be 'optional' or 'required'."
                )
            field.description = desc
            request_schema[k] = (dtype, field)

    schema = await asyncio.to_thread(_make_field)
    request_input: RequestInput = await asyncio.to_thread(
        AssistantData._create_request, schema
    )

    write_stream, read_stream = assistant_stream_context.get()
    logger.info(
        f"Sending input request to user through stream with key '{write_stream.key}'..."
    )
    stream_id = await write_stream.write(request_input)
    logger.info(
        f"Sent input request to user, request stored with stream id '{stream_id}'."
    )

    # wait for get valid requested input object, or until setting.config.request_user_input_timeout
    async def _wait_task():
        try:
            async for data in read_stream.bind("$"):
                for d in data:
                    if isinstance(data, RequestInput):
                        if data.id == request_input.id:
                            # Note: return only the first reach valid data came after the time of waiting, it's enough I thought. =))
                            return data.data
                        logger.warning(
                            f"Got RequestInput object but not match with the id of the object sent. Ignore and continue waiting."
                        )
            raise RuntimeError(
                f"This Exception is not expected to raise in run time, the stream some how be broken while iterating."
            )
        except asyncio.CancelledError:
            logger.debug("The task of waiting for requested user input is cancelled.")
            return None

    try:
        logger.info(
            f"Waiting for stream with key '{read_stream.key}' for requested input object."
        )
        return await asyncio.wait_for(_wait_task(), CONFIG.request_user_input_timeout)
    except TimeoutError:
        logger.info(
            "Not received any requested input object for the amount of time, reached timeout."
        )
        return None


async def capture_chat_context(
    from_latest: bool = True, count: int | None = None, data_only: bool = True
) -> list[list[AssistantData]]:
    """Retrieve latest data,
    Args:
        from_latest: The latest group of data which has the same chat_context_id will be in the first list.
        count: The number of data retrieved from stream ( Not the data after filter by status code.)
        data_only: If false, return both data input and status code.

    Returns: a list as matrix with row is list of all data that has the same chat_context_id.

    IMPORTANT:
        All data that have the same chat_context_id must be next to each others.
    """

    read_stream = assistant_stream_context.get().stream_pair.read_stream
    all_data = await read_stream.capture(from_latest, count)
    logger.debug(f"All data captured: \n" f"{all_data}")

    chat_context_list: list[list[AssistantData]] = []
    context_dict: dict[UUID, list[AssistantData] | None] = {}

    def _do():
        current_id: UUID | None = None
        for data in all_data:
            assert isinstance(data, AssistantData)
            if (
                isinstance(data, AssistantOutputData)
                and data.status.code != AssistantStatusCode.PROCESSING
                and data_only
            ):
                logger.debug(
                    f"Captured AssistantOutputData but status is not PROCESSING, and be skipped because of data_only:\n"
                    f"{data}"
                )
                continue

            if data.chat_context_id != current_id:
                assert data.chat_context_id not in context_dict

                if current_id is not None:
                    if from_latest:
                        context_dict[current_id].reverse()
                    chat_context_list.append(context_dict[current_id])
                    # None means mark it done, so any uuid exist in the future will raise error
                    context_dict[current_id] = None
                context_dict[data.chat_context_id] = [data]
                current_id = data.chat_context_id
            else:
                context_dict[current_id].append(data)

        # Save the last context, which is not triggered because there is no more satisfy data.chat_context_id != current_id
        if current_id:
            if from_latest:
                context_dict[current_id].reverse()
            chat_context_list.append(context_dict[current_id])
            logger.debug("Saved last context.")

    await asyncio.to_thread(_do)
    logger.debug(f"returned chat_context_list: \n{chat_context_list}")
    return chat_context_list


async def get_data_segments() -> list[DataSegment]:
    context = assistant_stream_context.get()
    cs = (await context.userdata.get_chat_sessions([context.cs_id]))[context.cs_id]
    data_segments = []
    for encoded in cs.data_segments:
        ds = await asyncio.to_thread(DataSegment.decode, encoded)
        assert isinstance(ds, DataSegment)
        data_segments.append(ds)
    return data_segments


async def save_data_segments(data_segments: list[DataSegment], *, persist: bool = True):
    context = assistant_stream_context.get()
    encoded_segs: list[str] = []
    async with context._lock:
        cs = (await context.userdata.get_chat_sessions([context.cs_id]))[context.cs_id]
        for ds in data_segments:
            encoded = await asyncio.to_thread(ds.encode)
            encoded_segs.append(encoded)
        await cs.append("data_segments", encoded_segs)

        if persist:
            logger.warning("Persist not implementation.")
            # TODO


async def get_user_facts() -> list[str]:
    context = assistant_stream_context.get()
    return context.userdata.summaries


async def save_user_facts(facts: list[str], *, persist: bool = True):
    context = assistant_stream_context.get()
    async with context._lock:
        await context.userdata.append("summaries", facts)
    if persist:
        logger.warning("Persis not implementation.")
        # todo


AssistantStreamer = Callable[
    [AssistantInputData], AsyncGenerator[AssistantOutputData, None]
]


# noinspection PyTypeChecker
class BaseAssistant(BaseModel):
    """This class is the base class of assistant app."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True, validate_default=True, frozen=True
    )
    streamer: AssistantStreamer
    input_schema: Type[AssistantInputData]

    name: str | None = None
    """assistant name that will be shown to user frontend."""

    assistant_classes: ClassVar[list["BaseAssistant"]] = []

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs):
        type_hints = get_type_hints(cls)
        fields = cls.model_fields

        if (st := fields["streamer"].annotation) != AssistantStreamer:
            m = f"Typehint of 'streamer' must be 'AssistantStreamer'. Got '{st}'."
            raise TypeError(m)
        # Strict for not allow re define typehint
        if (it := fields["input_schema"].annotation) not in (
            type[AssistantInputData],
            Type[AssistantInputData],
        ):
            m = f"Typehint of 'input_schema' must be 'Type[AssistantInputData]'. Got '{it}'."
            raise TypeError(m)

        cls.assistant_classes.append(cls)

    def __init__(self):
        """
        Because type hint compare of callable in init_subclass does not check for internal, now check it.
        Does not accept any arguments, so all arguments must initialize as default.
        """
        super().__init__()
        if not isinstance(sr := self.streamer(None), AsyncGenerator):
            m = f"streamer return type must be type AsyncGenerator[AssistantOutputData,None], got {type(sr)}."
            raise ValueError(m)

        from utilities.logger import logger

        logger.info(
            f"(PID={os.getpid()} ThreadID={threading.get_native_id()}): '{self.__class__.__name__}' was initialized."
        )

    def get_schema(self):
        return self.input_schema

    def get_name(self) -> str:
        return str(self.name)

    @classmethod
    def get_app(cls) -> serve.Application:
        return serve.deployment(
            name=f"{CHATBONE_ASSISTANT_APP_PREFIX}{cls.__name__}{CHATBONE_ASSISTANT_APP_POSTFIX}"
        )(cls).bind()

    async def handle_cancellation(self):
        """Optional handling after cancellation maybe for shutdown or cancel some task, call some APIs,..."""
        pass

    async def get_context(self):
        pass

    async def _stream(
        self, data: AssistantInputData
    ) -> AsyncIterator[AssistantOutputData]:
        logger.debug(f"{self.__class__.__name__} start stream with data {repr(data)}.")

        chunk_index: dict[int, int] = {}
        async for chunk in self.streamer(data):
            if not isinstance(chunk, AssistantOutputData):
                raise ValueError(
                    "The returned of graph is not the instance of 'AssistantOutputData'."
                )

            if chunk.stream_place in chunk_index:
                chunk_index[chunk.stream_place] += 1
            else:
                chunk_index[chunk.stream_place] = 0

            chunk._chunk_order = chunk_index[chunk.stream_place]

            logger.debug(
                f"Assistant yield chunk {repr(chunk)}, chunk_order={chunk.chunk_order}"
            )
            yield chunk

        logger.info("Done stream BaseAssistant")

    async def __call__(
        self,
        data_input: AssistantInputData,
        stream_pair: StreamPair,
        userdata: UserData,
        cs_id: UUID,
    ):
        logger.info(f"{self.name} called with {repr(data_input)}.")

        # Interface or app must handle all of these assertions, it's app role, not user or dev role.
        assert isinstance(data_input, self.input_schema)

        chat_context_id = data_input.chat_context_id
        logger.debug(f"chat_context_id={data_input.chat_context_id}")

        context = AssistantStreamContext(
            stream_pair=stream_pair,
            chat_context_id=chat_context_id,
            userdata=userdata,
            cs_id=cs_id,
        )

        with _stream_cm(context) as token:
            try:
                await stream_pair.write_stream.write(data_input)  # Ping
                await self._write_status(code=AssistantStatusCode.START)

                async for data in self._stream(data_input):
                    assert isinstance(data, AssistantOutputData)

                    data._assistant_name = self.name
                    data._chat_context_id = chat_context_id
                    data._status = Status(code=AssistantStatusCode.PROCESSING)

                    await stream_pair.write_stream.write(data)
                    logger.debug(
                        f"Wrote data {repr(data)}, chat_context_id: {data.chat_context_id}, status: {data.status}"
                    )

                await self._write_status(code=AssistantStatusCode.SUCCESS)

            except asyncio.CancelledError as e:
                try:
                    await self._write_status(code=AssistantStatusCode.CANCELING)
                    await self.handle_cancellation()
                except Exception as e:
                    await self._write_status(
                        code=AssistantStatusCode.ERROR, detail=str(e)
                    )
                finally:
                    await self._write_status(code=AssistantStatusCode.CANCELED)

            except Exception as e:
                logger.exception(e)
                await self._write_status(code=AssistantStatusCode.ERROR, detail=str(e))
                # raise e # Not expected error, hot fix by logger.exception() for now.
            finally:
                await self._write_status(AssistantStatusCode.DONE)

    # noinspection PyMethodMayBeStatic
    async def _write_status(
        self,
        code: AssistantStatusCode,
        detail: str | None = None,
    ):
        context = assistant_stream_context.get()
        write_stream = context.stream_pair.write_stream
        context_id = context.chat_context_id

        status_data = AssistantOutputData()
        status_data._chat_context_id = context_id
        status_data._status = Status(code=code, detail=detail)
        status_data._assistant_name = self.name

        await write_stream.write(status_data)


class UserInputData(BaseModel):
    assistant_name: str | None = None
    data: AssistantInputData | None = None


class AssistantInterface:
    """Chat app uses this class to communicate with assistant app."""

    @staticmethod
    async def get_assistant_names() -> dict[str, str]:
        """

        Returns:
            A dict with format (assistant_name, app_name) 'app_name' are serve app_name, for internal use to get DeploymentHandle,
            'assistant_name' is the one show to app or user.
        """

        names = {}
        app_names = await asyncio.to_thread(
            AssistantInterface._get_healthy_assistant_app_names
        )
        for appname in app_names:
            handle = await AssistantInterface.get_assistant_app_handle(appname)
            as_name = await handle.get_name.remote()
            names[as_name] = appname
        return names

    @staticmethod
    async def get_assistant_schema(assistant_app_name: str) -> Type[AssistantInputData]:
        handle: DeploymentHandle = await AssistantInterface.get_assistant_app_handle(
            assistant_app_name
        )
        schema = await handle.get_schema.remote()
        assert issubclass(schema, AssistantInputData)
        return schema

    @staticmethod
    async def get_assistant_app_handle(assistant_app_name: str) -> DeploymentHandle:
        return await asyncio.to_thread(
            AssistantInterface._get_assistant_app_handle, assistant_app_name
        )

    @staticmethod
    async def call(
        app_name,
        user_input: UserInputData,
        stream_pair: StreamPair,
        userdata: UserData,
        cs_id: UUID,
    ):
        """Call ray task and block until success"""
        handle = await AssistantInterface.get_assistant_app_handle(app_name)
        task = handle.remote(user_input.data, stream_pair, userdata, cs_id)

        logger.debug(
            f"AssistantInterface called assistant {user_input.assistant_name}. chat_context_id = {user_input.data.chat_context_id}"
        )

        try:
            await task
        except asyncio.CancelledError as e:
            logger.debug(f"Assistant call cancelling...")
            task.cancel()
            try:
                await task
            except RequestCancelledError as e:
                if not isinstance(e, TaskCancelledError):
                    logger.exception(e)
                    raise e
                logger.debug("Ray call cancelled successfully.")

    @staticmethod
    def _get_assistant_app_handle(assistant_name: str) -> DeploymentHandle:
        return serve.get_app_handle(assistant_name)

    @staticmethod
    def _get_healthy_assistant_app_names() -> list[str]:
        assistants = []
        apps = serve.status().applications
        print(f"serve.status().applications return {apps}")
        for name, status in apps.items():
            if status.status == ray_schema.ApplicationStatus.RUNNING:
                # Check healthy for all deployments and detect one name has assistant postfix
                has_assistant_postfix: bool = False
                has_one_deployment_not_healthy: bool = False
                for depl_name, depl_status in status.deployments.items():
                    if depl_name.endswith(
                        CHATBONE_ASSISTANT_APP_POSTFIX
                    ) and depl_name.startswith(CHATBONE_ASSISTANT_APP_PREFIX):
                        has_assistant_postfix = True
                    if not (
                        depl_status.status == "HEALTHY"
                        and depl_status.status_trigger == "CONFIG_UPDATE_COMPLETED"
                        and depl_status.replica_states[ReplicaState.RUNNING] > 0
                    ):
                        has_one_deployment_not_healthy = True
                        break

                if has_assistant_postfix and not has_one_deployment_not_healthy:
                    assistants.append(name)
                elif has_assistant_postfix:
                    logger.info(
                        f"Detected assistant app '{name}' but it's not healthy."
                    )
        return assistants
