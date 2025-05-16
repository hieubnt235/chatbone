import asyncio

from redis.exceptions import LockError
from uuid_extensions import uuid7
from utilities.logger import logger
from chatbone.broker import REDIS, UserData, ChatSessionData, UserNotFoundError, RedisKeyError, UserToken, Message, \
	WriteStream, ReadStream, AS2CSData, RequestForm, TextUrlsFormat
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
	                                "chat_sessions": chat_sessions})
uid1 = "0196cd4a-c93c-7b44-b00c-8dd6fdb695bb"
uid2 = "0196cd4a-f224-7531-a923-a46be56a2e0e"
userdata1 = create_userdata(2,2,uid1)
userdata2 = create_userdata(2,2,uid2)

async def main1():
	#clean
	if await REDIS.exists(userdata1.rkey):
		userdata = await userdata1.refresh() # refresh to update cascade rkeys.
		await userdata.delete()

	userdata = await userdata1.save() # save new
	print(userdata)
	chatsessions = [cs for cs in userdata.chat_sessions.values()]
	cs = chatsessions[0]
	# await cs.save() # Not valid cs cannot save.
	try:
		await cs.append("messages",[Message(role="user",content=f"content:{i}") for i in range(3)])
	except ValueError as e:
		logger.error(e) #This embedding object haven't bound any base rkey.
		cs = (await userdata.get_chat_sessions([cs.id]))[cs.id]
		print(f"is bounded: {cs.is_bounded}")
		print(await cs.append("messages",[Message(role="user",content=f"content:{i}") for i in range(3)])) # 5, 2 for init and 3 news.

	print(await userdata.all_sub_rkeys)

	async with cs.get_stream('as2cs','as',) as stream:
		print(await REDIS.ttl(cs.as2cs_stream_rkey), await REDIS.ttl(cs.cs2as_stream_rkey))
		await userdata.expire(30)
		print(await REDIS.ttl(cs.as2cs_stream_rkey), await REDIS.ttl(cs.cs2as_stream_rkey))
		# work
		await userdata.delete()
		print(await REDIS.ttl(cs.as2cs_stream_rkey), await REDIS.ttl(cs.cs2as_stream_rkey))

async def main2():
	if await REDIS.exists(userdata1.rkey):
		userdata = await userdata1.refresh() # refresh to update cascade rkeys.
		await userdata.delete()
	userdata = await userdata1.save(expire_seconds=100) # save new

	chatsessions = [cs for cs in userdata.chat_sessions.values()]
	cs = chatsessions[0]
	cs = (await userdata.get_chat_sessions([cs.id]))[cs.id]

	async def write_stream():
		async with cs.get_stream('as2cs', 'as', ) as stream:
			n=1
			while n<6:
				print(f"Write stream 1 acquired lock for {n} seconds. {type(stream)}")
				n+=1
				await asyncio.sleep(1)

	async def write_stream2():
		await asyncio.sleep(2)
		try:
			async with cs.get_stream('as2cs', 'as',write_role_acquire_timeout=2 ) as stream:
				pass
		except LockError:
			logger.error("Caught lock error during acquire lock two times.")
	await asyncio.gather(write_stream(),write_stream2())

async def main3():
	if await REDIS.exists(userdata1.rkey):
		userdata = await userdata1.refresh() # refresh to update cascade rkeys.
		await userdata.delete()
	userdata = await userdata1.save(expire_seconds=100) # save new

	chatsessions = [cs for cs in userdata.chat_sessions.values()]
	cs = chatsessions[0]
	cs = (await userdata.get_chat_sessions([cs.id]))[cs.id]

	async def read_user_input():
		return await asyncio.to_thread(input,"Say something:")

	async def read_stream():
		async with cs.get_stream('as2cs', 'cs') as stream:
			assert isinstance(stream,ReadStream)
			async for data in stream:
				print(data)

	async def write_stream():
		async with cs.get_stream('as2cs', 'as' ) as stream:
			assert isinstance(stream,WriteStream)
			user_input = ""
			# Warning, need to handle shutdown, because the ctrl C shutdown does not release the lock
			while user_input!="exit()":
				user_input= await read_user_input()
				as2csdata = AS2CSData(request=RequestForm(request_id=uuid7(),message=TextUrlsFormat(text_fmt=f"This is user input :'{user_input}'")),state='processing')
				await stream.write(as2csdata)
	task2 = asyncio.create_task(read_stream())
	task3 = asyncio.create_task(write_stream())
	try:
		print(await asyncio.wait([task2,task3],return_when=asyncio.FIRST_COMPLETED))
	finally:
		await userdata.delete()
		print("finally")

# asyncio.run(main1())
# asyncio.run(main2())
asyncio.run(main3())
