import typing
from typing import Sequence, Union, Any, Callable, Optional, Iterator

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool

from drafts.core.providers.chat_models.chatbase import ChatBase


class ChatHFLocal(ChatBase):
    """

    """

    def _generate(self, messages: list[BaseMessage], stop: Optional[list[str]] = None,
                  run_manager: Optional[CallbackManagerForLLMRun] = None, **kwargs: Any) -> ChatResult:
        pass

    def _stream(self, messages: list[BaseMessage], stop: Optional[list[str]] = None,
                run_manager: Optional[CallbackManagerForLLMRun] = None, **kwargs: Any) -> Iterator[ChatGenerationChunk]:
        pass

    @property
    def _llm_type(self) -> str:
        return 'hf_local'

    def bind_tools(self, tools: Sequence[
        Union[typing.Dict[str, Any], type, Callable, BaseTool]  # noqa: UP006
    ], **kwargs: Any) -> Runnable[LanguageModelInput, BaseMessage]:
        pass
