from tools.mcp_server import MCPServer

math_mcp = MCPServer(name='math')


@math_mcp.tool()
def add(a: float, b: float) -> float:
	"""
	Add two numbers and return the result.
	Args:
		a:
		b:
	Returns: Summary of a and b.
	"""
	return a + b
