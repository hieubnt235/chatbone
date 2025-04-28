from typing import Optional

from dotenv import find_dotenv
from pydantic import field_serializer, BaseModel, PositiveInt, Field
from pydantic_settings import SettingsConfigDict

from utilities.settings import Settings, Config


class SearchWebConfig(BaseModel):
	"""
	Initialization parameters of TavilySearch that can pass by invoking (LLM can do that).
	So now don't need to config it.
		search_depth: Optional[Literal["basic", "advanced"]] = "basic"
		include_domains: Optional[List[str]] = None
		exclude_domains: Optional[List[str]] = None
		include_images: Optional[bool] = False
		time_range: Optional[Literal["day", "week", "month", "year"]] = None
		topic: Optional[Literal["general", "news", "finance"]] = "general"
		include_raw_content: Optional[bool] = False
		include_image_descriptions: Optional[bool] = False
	"""
	max_results: Optional[int] = 5
	max_length:PositiveInt=Field(1000,description="Maximum number of char length of results. The remain results is drop.")
	include_answer: Optional[bool] = False

class SearchDocsConfig(BaseModel):
	pass

class SearchConfig(BaseModel):
	path:str ='/search'
	"""Path to mount mcp app."""

	web: SearchWebConfig
	docs:SearchDocsConfig

class MathConfig(BaseModel):
	path:str='/math'


class ToolsConfig(Config):
	mcp_path:str = '/mcp'
	"""Path for client accessing to mcp server."""

	search: SearchConfig
	math: MathConfig


class ToolsSettings(Settings):
	model_config = SettingsConfigDict(env_prefix='tools_', env_file=find_dotenv('.env.tools'))

	config: ToolsConfig
	service_name = 'tools'

	tavily_api_key: str

	@field_serializer('tavily_api_key')
	def secret(self,value:str):
		assert isinstance(value,str)
		return '***TAVILY_API_KEY***'


# noinspection PyArgumentList
tools_settings= ToolsSettings()

__all__=['tools_settings']