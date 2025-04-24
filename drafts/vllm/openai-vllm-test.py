from langchain_openai import ChatOpenAI

# Set OpenAI's API key and API base to use vLLM's API server.
openai_api_key = "EMPTY"
openai_api_base = "http://localhost:9999/v1"

llm = ChatOpenAI(model="qwen-0.5b", openai_api_key=openai_api_key, openai_api_base=openai_api_base,
                 max_tokens=1000, temperature=0, )

def add(x:float,y:float):
	"""
	Function that add two arguments and return their sum.
	Args:
		x: the first argument
		y: the second argument
	Returns: Summation of two argument x and y
	"""
	return x+y

messages1 = [{"role": "system", "content": "You are a good assistant."},
             {"role": "user", "content": "What is one plus one ?."}, ]

llm_tools = llm.bind_tools([add])
a =llm_tools.invoke(messages1)
print(a)
