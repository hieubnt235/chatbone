from langchain_tavily.tavily_search import TavilySearch, TavilySearchInput

from utilities.exception import handle_tools_exception
from utilities.logger import logger
from tools.mcp_server import MCPServer
from .settings import tools_settings

search_config = tools_settings.config.search

search_mcp = MCPServer(name='search')

ERROR_MESSAGE="""If the work does not really need this tool, so ignore and keep continue even though the result is somehow bad.
Or can notice to the user/client the situation, so that they will decide what to do next.
"""

@search_mcp.tool()
@handle_tools_exception(message=ERROR_MESSAGE)
async def search_web(search_input: TavilySearchInput) -> str:
		"""
		Search web and return the text result text related to the query.
		Args:
			search_input: TavilySearchInput parameter.
		Returns:
			Text related to the query. It will be the answer if query input is question, or it can be some related text with the input.
		"""
		tavily_search = TavilySearch(tavily_api_key=tools_settings.tavily_api_key,
		                             **search_config.web.model_dump())

		results = (await tavily_search.ainvoke(search_input.model_dump()))['results']
		logger.debug(results)

		ret = ""
		max_length = search_config.web.max_length
		for i,r in enumerate(results):
			if len(ret)<= max_length:
				ret = ret + f'Result {i+1}:\n' + r['content'] + '\n'
		logger.debug(ret)
		return ret

@search_mcp.tool()
@handle_tools_exception(message=ERROR_MESSAGE)
async def search_docs(query: str):

	# TODO, search docs and agent.
	return "not implement"+query


__all__ = ['search_mcp']
