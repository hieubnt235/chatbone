import asyncio
from copy import deepcopy

from uuid_extensions import uuid7

from chatbone.broker import REDIS, UserData, ChatSessionData, UserNotFoundError, RedisKeyError, UserToken
from utilities.func import utc_now, get_expire_date


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
	                                # "user_token": {
		                            #     "id": uuid7(),
		                            #     "created_at":utc_now(),
		                            #     "expires_at":utc_now()
	                                # },
	                                "chat_sessions": chat_sessions})
uid1 = "0196cd4a-c93c-7b44-b00c-8dd6fdb695bb"
uid2 = "0196cd4a-f224-7531-a923-a46be56a2e0e"

userdata1 = create_userdata(2,2,uid1)
userdata2 = create_userdata(2,2,uid2)

async def main():
	print( await userdata1.save()) # True
	userdata11 = await userdata1.refresh()

	print(await userdata11.save(expire_seconds=100) ) # skip but still expire, return None
	print(await REDIS.ttl(userdata11.rkey))  # -2 means not exist, -1 means not 'expire', this will return 100

	print(await userdata11.save() ) # True
	print(await REDIS.ttl(userdata11.rkey))  # -2 means not exist, -1 means not 'expire'

	print(len(await userdata11.all_sub_rkeys))

	len(userdata11.chat_sessions)
	new = await userdata11.refresh(exclude={"chat_sessions"})
	print(new.model_dump_json(indent=4))

async def main2():
	try:
		token = await userdata2.get_encrypted_token()
	except UserNotFoundError:
		await userdata2.save()
		token = await userdata2.get_encrypted_token()

	userdata = await UserData.verify_encrypted_token(token)

	print(userdata.encrypted_secret_token == token) # True
	new_token = await userdata.get_encrypted_token()
	print(new_token==token) # True

	new_token = await userdata.get_encrypted_token(skip_if_exist=False)
	print(new_token==token)# False, new token

	try:
		new_userdata = await UserData.verify_encrypted_token(token)
	except Exception:
		new_userdata = await UserData.verify_encrypted_token(new_token)

	print(await new_userdata.get_encrypted_token()== new_token) # True

	print(await REDIS.ttl(new_userdata.rkey), await REDIS.ttl(new_userdata.encrypted_secret_rkey) )
	await new_userdata.expire(30)
	print(await REDIS.ttl(new_userdata.rkey), await REDIS.ttl(new_userdata.encrypted_secret_rkey) )

	await userdata1.save(expire_seconds=10)

	token1 = await userdata1.get_encrypted_token()
	print(await REDIS.ttl(userdata1.rkey), await REDIS.ttl(userdata1.encrypted_secret_rkey) )


async def main3():
	csids = [uid for uid in userdata1.chat_sessions.keys()]
	cs_0 = userdata1.chat_sessions[csids[0]]

	await userdata1.save()
	print(userdata1)

	token = await userdata1.get_encrypted_token()

	userdata11 = await UserData.verify_encrypted_token(token,lazy_load_chat_sessions=True)
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
	userdata11 = await UserData.verify_encrypted_token(token,lazy_load_chat_sessions=False) # good
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

	await asyncio.sleep(3)
	new_user_obj = UserData(username=userdata1.username,
	                        password=userdata1.password,
	                        id=userdata1.id
	                        )
	try:
		await new_user_obj.delete()
	except RedisKeyError:
		print("Caught") # good
		new_user_obj = await new_user_obj.refresh()
		print(await new_user_obj.delete())


	# await userdata11.delete() # good, delete both token and rkey.


async def main5():

	userdata = await userdata1.save()
	async def trigger_valid_token():
		await asyncio.sleep(3)
		await userdata.set("user_token",UserToken(id=uuid7(),created_at=utc_now(),expires_at=get_expire_date(10)))
		print("Set new valid token.")

	asyncio.create_task(trigger_valid_token())
	token = await userdata.verify_valid_user(10,1) # work
	print(token)

async def main6():
	# stream
	pass

# asyncio.run(main())
# asyncio.run(main2())
# asyncio.run(main3())
# asyncio.run(main4())
asyncio.run(main5())
