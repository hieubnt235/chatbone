# Dummy MCP server for testing

import asyncio
import time

from fastapi import FastAPI
from starlette.routing import Mount

from utilities.logger import logger
from tools.mcp_server import MCPServer, MCP_APP_SUFFIX

"""
According fastmcp/utilities/func_metadata.py line 67:
 - Async function will called with await, normal function will be called.
 - Normal function will called WITHOUT THREAD. 
=> Custom MCP will wrap normal function with a thread.

If there's very cpu high load. run it in another process (task queue, processing, ray,...)
"""

MCP_PATH = "/mcp"

dummy_mcp = MCPServer(name='dummy')

@dummy_mcp.tool()
async def async_task(name:str, repeat:int):
	logger.info("async_task started:")
	start = time.time()
	assert repeat>0
	for i in range(repeat):
		await asyncio.sleep(1)
		logger.debug(f"async_task-\'{name}\': {i}/{repeat}")
	m =  f"async_task-\'{name}\': repeated {repeat} times in {time.time()-start} seconds."
	logger.info(f"async_task done after {time.time()-start} seconds.")
	return m

@dummy_mcp.tool()
def threaded_task(name:str, repeat:int):
	logger.info("threaded_task started:")
	assert repeat>0
	start = time.time()
	for i in range(repeat):
		for k in range(10**7):
			assert k>=0
		time.sleep(1)
		logger.debug(f"threaded_task-\'{name}\': {i}/{repeat}")
	m = f"threaded_task-\'{name}\': repeated {repeat} times in {time.time()-start} seconds."
	logger.info(f"threaded_task done after {time.time()-start} seconds.")
	return m

tools_app = FastAPI()
tools_app.mount('/dummy', dummy_mcp.app(MCP_PATH), name=dummy_mcp.app_name)


@tools_app.get('/list_mcp_apps')
async def list_apps()->dict:
	"""
	List all mcp apps of this tools app. The values of the returned dict are used to access through client.
	Returns: A dict with app names as keys and url formats as values.
	"""
	ret = {}
	for r in tools_app.routes:
		if isinstance(r,Mount) and r.name.endswith(MCP_APP_SUFFIX):
			ret[r.name] = f"ws://{{host_and_port_or_domain}}{r.path}{MCP_PATH}"
	return ret

from ray import serve

@serve.deployment(name='dummy_tools_app',num_replicas=3)
@serve.ingress(tools_app)
class DummyToolsApp:
	pass

# import uvicorn
# uvicorn.run(tools_app)
serve.run(DummyToolsApp.bind(),blocking=True)