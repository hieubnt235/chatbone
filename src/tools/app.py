from fastapi import FastAPI
from starlette.routing import Mount

from tools.math import math_mcp
from tools.mcp_server import MCP_APP_SUFFIX
from tools.search import search_mcp
from tools.settings import tools_settings

config = tools_settings.config
tools_app = FastAPI()
tools_app.mount(config.search.path, search_mcp.app(config.mcp_path), name=search_mcp.app_name)
tools_app.mount(config.math.path, math_mcp.app(config.mcp_path), name=math_mcp.app_name)


@tools_app.get('/list_mcp_apps')
async def list_apps()->dict:
	"""
	List all mcp apps of this tools app.

	Returns:
	 	A dict with app names as keys and url formats as values.
	"""
	ret = {}
	for r in tools_app.routes:
		if isinstance(r,Mount) and r.name.endswith(MCP_APP_SUFFIX):
			ret[r.name] = f"ws://{{host_and_port_or_domain}}{r.path}{config.mcp_path}"
	return ret

if __name__ == '__main__':
	# import uvicorn
	# uvicorn.run(tools_app)

	# ray.init()

	from ray import serve
	@serve.deployment(num_replicas=3)
	@serve.ingress(tools_app)
	class ToolsApp:
		pass


	serve.run(ToolsApp.bind(), blocking=True)
#