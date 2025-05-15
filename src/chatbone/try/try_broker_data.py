import asyncio

from uuid_extensions import uuid7

from chatbone.broker import REDIS,UserData, ChatSessionData


def session(uid, n_messages):
	return {"id"      : uid,
	        "messages": [{"role": "assistant", "content": f"you are an assistant {uid} and message i {i}"} for i in range(n_messages)]}


def create_userdata(n_sessions, n_messages,uid=None):
	useruid = uid or uuid7()
	chat_sessions={}
	for i in range(n_sessions):
		csid = uuid7()
		chat_sessions[csid]=session(csid,n_messages)
	return UserData.model_validate({"id": useruid,
	                                "username": f"hieu:{useruid}",
	                                "password":"mypassword",
	                                "chat_sessions": chat_sessions})
uid1 = "0196cd4a-c93c-7b44-b00c-8dd6fdb695bb"
uid2 = "0196cd4a-f224-7531-a923-a46be56a2e0e"

userdata1 = create_userdata(2,2,uid1)
userdata2 = create_userdata(2,2,uid2)

async def main():
	print(await userdata1.delete()) # 0 or 1
	print( await userdata1.save()) # True

	print(await userdata1.save(expire_seconds=100) ) # skip but still expire, return None
	print(await REDIS.ttl(userdata1.rkey))  # -2 means not exist, -1 means not 'expire', this will return 100

	print(await userdata1.save(skip_if_exist=False) ) # True
	print(await REDIS.ttl(userdata1.rkey))  # -2 means not exist, -1 means not 'expire'

	print(len(await userdata1.all_sub_rkeys))

	len(userdata1.chat_sessions)
	new = await userdata1.refresh(exclude={"chat_sessions"})
	print(new.model_dump_json(indent=4))

async def main2():
	try:
		token = await userdata2.get_encrypted_token()
	except KeyError:
		await userdata2.save()
		token = await userdata2.get_encrypted_token()

	userdata = await UserData.verify_encrypted_token(token)
	print(userdata._encrypted_token == token) # True
	new_token = await userdata.get_encrypted_token()
	print(new_token==token) # True

	new_token = await userdata.get_encrypted_token(skip_if_exist=False)
	print(new_token==token)# False, new token

	try:
		new_userdata = await UserData.verify_encrypted_token(token)
	except Exception:
		new_userdata = await UserData.verify_encrypted_token(new_token)

	print(await new_userdata.get_encrypted_token()== new_token) # True

	print(await REDIS.ttl(new_userdata.rkey), await REDIS.ttl(new_userdata.encrypted_token_rkey) )
	await new_userdata.expire(30)
	print(await REDIS.ttl(new_userdata.rkey), await REDIS.ttl(new_userdata.encrypted_token_rkey) )

	await userdata1.save(expire_seconds=10)
	token1 = await userdata1.get_encrypted_token()
	print(await REDIS.ttl(userdata1.rkey), await REDIS.ttl(userdata1.encrypted_token_rkey) )


async def main3():
	csids = [uid for uid in userdata1.chat_sessions.keys()]
	cs_0 = userdata1.chat_sessions[csids[0]]

	await userdata1.save(skip_if_exist=False)
	print(userdata1)

	token = await userdata1.get_encrypted_token()

	userdata11 = await UserData.verify_encrypted_token(token)
	print(userdata11)

	for k in await userdata11.all_sub_rkeys:
		print(k)

	chatsessions = await userdata11.get_chat_sessions([csids[0]]) # get one

	print(chatsessions[csids[0]].model_dump_json()== cs_0.model_dump_json())
	print(userdata11.chat_sessions)

	for cs in userdata11.chat_sessions.values():
		print(cs._base_rkey, cs._jsonpath) # already set.


	chatsessions = await userdata11.get_chat_sessions(csids) # get all
	print(len(userdata11.chat_sessions)== len(csids))
	print(userdata11.chat_sessions)

async def main4():
	await userdata1.save()
	token = await userdata1.get_encrypted_token()
	userdata11 = await UserData.verify_encrypted_token(token,lazy_load=False) # good
	print(userdata11.chat_sessions)
	cs = None
	for cs in userdata11.chat_sessions.values():
		print(cs._base_rkey, cs._jsonpath) # already set.
		cs = cs
	a = await cs.append("summaries",["sum1", "sum2"]) # good =))
	print(a)

	print(await REDIS.ttl(userdata11.rkey), await REDIS.ttl(userdata11.encrypted_secret_rkey) )
	await userdata11.expire(30)
	print(await REDIS.ttl(userdata11.rkey), await REDIS.ttl(userdata11.encrypted_secret_rkey) )

	await userdata1.save(expire_seconds=100)
	token1 = await userdata1.get_encrypted_token()
	print(token1==token)
	print(await REDIS.ttl(userdata11.rkey), await REDIS.ttl(userdata11.encrypted_secret_rkey) )

	await asyncio.sleep(10)
	await userdata11.delete() # good, delete both token and rkey.

m = main4()

asyncio.run(m)