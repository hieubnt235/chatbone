from typing import Literal, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from ray import ObjectRef


class JsonRPCSchema(BaseModel):
	jsonrpc: Literal['2.0']
	method: str
	params: tuple[str | Any] | dict[str, Any] | BaseModel
	id: int | UUID | str


class AssistantRequestFormat(JsonRPCSchema):
	"""
	Request that Assistant send to ChatAssistantSVC
	"""
	model_config = ConfigDict(arbitrary_types_allowed=True)

	# noinspection PyUnresolvedReferences
	response_schema: ObjectRef[type[BaseModel]]
	"""Schema for validate (model_validate) the body received from user. If not match, prompt user to send new correct body."""
