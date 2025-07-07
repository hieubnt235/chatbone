from types import ModuleType

from chatbone.assistant.assistant_interface import *
from chatbone.assistant.assistant_interface import _assistant_stream_context, _stream_cm


# noinspection PyTypeChecker
class AssistantAppFactory(BaseModel):
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
        import importlib
        importlib.import_module()
        ModuleType
        
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
        context = _assistant_stream_context.get()
        write_stream = context.stream_pair.write_stream
        context_id = context.chat_context_id

        status_data = AssistantOutputData()
        status_data._chat_context_id = context_id
        status_data._status = Status(code=code, detail=detail)
        status_data._assistant_name = self.name

        await write_stream.write(status_data)

def __getattr__(name):

