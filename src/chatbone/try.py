import asyncio

from chatbone.broker import ChatSessionData, UserData, REDIS

def session(id, n):
	return {"id": str(id), "messages": [{"role": "assistant", "content": f"you are an assistant {id} and message i {i}"} for i in range(n)] }

uid2 = "0196c494-ce60-73b4-8db7-67137988f322"
data2 = {"id": uid2,
        "username": "hieu2",
        "chat_sessions": {i:session(i,100) for i in  range(1000)} # 100 chat session with 1000 messages
        }

async def main():
	await REDIS.json().set("test_json",'.',{})
	print(1,await REDIS.json().get("test_json",'.'))
	# print(2,await REDIS.get("test_json"))

	await REDIS.delete("test_json")

	print(3,await REDIS.json().get("test_json", '.'))
	print(4, await REDIS.get("test_json"))

asyncio.run(main())