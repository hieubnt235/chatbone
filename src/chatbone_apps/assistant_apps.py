from typing import AsyncIterator

from chatbone.assistant.assistant_interface import *
from chatbone_apps.commons import _make_deployment_name_from_real_import_path
from utilities import logger
from utilities.func import base64_decode


# noinspection PyTypeChecker
class AssistantAppFactory:

    def __init__(self, module_name: str, assistant_instance_name: str):
        super().__init__()
        import os
        import threading
        import importlib
        from utilities import logger
        from chatbone.assistant.assistant_interface import (
            _assistant_stream_context,
            _stream_cm,
        )

        self._assistant_stream_context = _assistant_stream_context
        self._stream_cm = _stream_cm

        m = importlib.import_module(module_name)
        assistant = getattr(m, assistant_instance_name)
        assert isinstance(assistant, BaseAssistant)

        if not isinstance(sr := assistant.streamer(None), AsyncGenerator):
            m = f"Assistant.stream(...) return type must be type AsyncGenerator[AssistantOutputData,None], got {type(sr)}."
            raise ValueError(m)
        self.assistant: BaseAssistant = assistant

        logger.info(
            f"(PID={os.getpid()} ThreadID={threading.get_native_id()}): Assistant named {assistant.name},"
            f" instance of '{self.assistant.__class__.__name__}' was initialized."
        )
        logger.debug(repr(assistant))

    def get_schema(self):
        return self.assistant.input_schema

    def get_name(self) -> str:
        return self.assistant.name

    @property
    def name(self) -> str:
        return self.get_name()

    @property
    def input_schema(self) -> Type[AssistantInputData]:
        return self.get_schema()

    @classmethod
    def get_app(cls, real_import_path: str) -> serve.Application:
        path = real_import_path.split(":")
        assert len(path) == 2 and path[0] and path[1]
        module_name, assistant_instance_name = path

        return serve.deployment(
            name=_make_deployment_name_from_real_import_path(real_import_path)
        )(cls).bind(module_name, assistant_instance_name)

    async def _stream(
        self, data: AssistantInputData
    ) -> AsyncIterator[AssistantOutputData]:
        logger.debug(f"{self.__class__.__name__} start stream with data {repr(data)}.")
        chunk_index: dict[int, int] = {}
        async for chunk in self.assistant.streamer(data):
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

        with self._stream_cm(context) as token:
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
                    await self.assistant.handle_cancellation()
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
        context = self._assistant_stream_context.get()
        write_stream = context.stream_pair.write_stream
        context_id = context.chat_context_id

        status_data = AssistantOutputData()
        status_data._chat_context_id = context_id
        status_data._status = Status(code=code, detail=detail)
        status_data._assistant_name = self.name

        await write_stream.write(status_data)


def __getattr__(app_name: str):
    class_import_path = base64_decode(app_name)  # which is encoded by cli.build
    app = AssistantAppFactory.get_app(class_import_path)
    logger.debug(f"Created Ray serve application {repr(app)}.")
    return app


# dummy_app = AssistantAppFactory.get_app("assistants:dummy_assistant")
# dummy2_app = AssistantAppFactory.get_app("assistants:dummy2_assistant")
# from ray import serve
# serve.run(dummy_app)
# serve.deployment
