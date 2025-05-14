import asyncio

from uuid_extensions import uuid7

from chatbone.broker import REDIS,UserData, ChatSessionData


def session(id, n):
	return {"id"      : str(id),
	        "messages": [{"role": "assistant", "content": f"you are an assistant {id} and message i {i}"} for i in
	                     range(n)]}


uid2 = "0196c494-ce60-73b4-8db7-67137988f322"
data2 = {"id": uid2, "username": "hieu2", "chat_sessions": {i: session(i, 100) for i in range(1000)}
         # 100 chat session with 1000 messages
         }


def session( n_messages):
	uid = uuid7()
	return {"id"      : uid,
	        "messages": [{"role": "assistant", "content": f"you are an assistant {uid} and message i {i}"} for i in range(n_messages)]}


def create_userdata(n_sessions, n_messages):
	return UserData.model_validate({"id": uuid7(), "username": "hieu2", "chat_sessions": {i: session( n_messages) for i in range(n_sessions)}})


async def main():
	userdata1 = create_userdata(100,20)
	userdata2 = create_userdata(100,20)



# await REDIS.delete("test_json")
#
# print(3,await REDIS.json().get("test_json", '.'))
# print(4, await REDIS.get("test_json"))

asyncio.run(main())
