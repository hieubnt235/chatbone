from typing import Any, Self

from fastapi import HTTPException, status, WebSocket

from chatbone.chat.settings import DATASTORE, CONFIG, REDIS
from chatbone.chat.lua import LUA
from utilities.exception import handle_http_exception
from utilities.func import utc_now
from utilities.settings.clients.datastore import *

ServerError = HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Something went wrong with server.")

def TooManySessionsError(max_sessions: int):
	return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Too many sessions exist. You have to delete"
	                                                                     f"some to create new one. Max sessions allowed: {max_sessions}")

class ChatSessionData(BaseModel):
	messages: MessagesReturn
	summaries: ChatSummariesReturn
	urls: list[AnyUrl]|None = Field(None,description="Addition data should be store in object storage and provide url.")

username = {
	"tokens": [
		{"id":1, "expired_at": get_expire_date(100000)},
		{"id":1, "expired_at": get_expire_date(100000)}# get expire date return expire at string.
	],
	"info": {
		# some info
	},
	"data": {
		# user data
	}
}

def _filter_valid_token(obj:Any)->Any:
	# TODO, make the valid atomic using lua
	valid_tokens = []
	for t in obj['tokens']:
		if datetime.strptime(t['expires_at']) > utc_now():
			valid_tokens.append(t)
	obj['tokens'] = valid_tokens

	# TODO DELETE
	return obj

async def _heartbeat_cache(key:str):
	while True:
		await REDIS.expire(key,CONFIG.chatbone_timeout.cache)
		await asyncio.sleep(CONFIG.chatbone_timeout.cache-10)

class UserData(BaseModel):
	chat_sessions:dict[UUID,ChatSessionData] = Field(description="dict with keys are chat_session_id.")
	summaries: UserSummariesReturn
	tokens: list[TokenInfoReturn]

	@classmethod
	def model_validate(cls,obj: Any,*,strict: bool | None = None,from_attributes: bool | None = None,context: Any | None = None,) -> Self:
		"""
		This method will be called each time the cache is get, use to filter, validation, ...
		"""
		obj = _filter_valid_token(obj)
		return super().model_validate(obj,strict=strict, from_attributes=from_attributes, context=context)

"""
Operations:
1. User do auth with frontend, frontend call service create_connection.
2. Service create connection by create the hash key as username, set the expire(which are set in setting).
 Which is persist if it still have at least one connection.
 
3. Frontend return html which has websocket embedded in it, map with username.
4. User connect to frontend and frontend connect to chat with valid token. Do operation. Any operation that need valid token, server will ask frontend
for it, set timeout, if valid token not provide under timeout, chatserver disconnect. If no connection for along time, username cache is clear.

"""




class ChatBoneSVC:
	"""
	- Load User history, info, summary to object storage and distribute it.
	"""
	@handle_http_exception(ServerError)
	async def create_connection(self, user_info: UserInfoReturn)->str:
		LUA['create_connection']

		if (await REDIS.exists(user_info.username))==0:
			await REDIS.hset()

		# Ensure one user can open one connection at a time.
		# If existed, reset the expiry date, else create a new one
		connection_id = await _encode_connection(user_info.username,user_info.id)
		if await REDIS.hgetall(connection_id) != {}:
			await REDIS.expire(connection_id,CONFIG.chatbone_timeout.cache)
		else:
			data = UserCacheData(connection_id=connection_id,user_info=user_info,auth=auth)
			await REDIS.hset(connection_id,data.model_dump(mode='json'))
			await REDIS.expire(connection_id,CONFIG.chatbone_timeout.cache)
		return connection_id


	@handle_http_exception(ServerError)
	async def connect_chat(self, ws:WebSocket, connection_id:str,session_id:UUID):
		heartbeat=None
		try:
			if (user_cache_data := await REDIS.hgetall(str(connection_id)) ) == {}:
				raise HTTPException(status_code=status.HTTP_407_PROXY_AUTHENTICATION_REQUIRED) # call create_connection somehow first
			user_cache_data = UserCacheData.model_validate(user_cache_data)
			heartbeat = asyncio.create_task(_heartbeat_cache(connection_id))



		except AuthExpiredException:
			raise HTTPException(status_code=status.HTTP_407_PROXY_AUTHENTICATION_REQUIRED)

		finally:
			if heartbeat is not None:
				heartbeat.cancel()
				await REDIS.expire(connection_id,CONFIG.chatbone_timeout.cache)



	@handle_http_exception(ServerError)
	async def create_chat_session(self, schema: ChatSVCBase) -> ChatSessionReturn:
		user_info_res = await DATASTORE.user.access.get(
			ClientRequestSchema[Token](body=Token(token_id=schema.token_id), timeout=CONFIG.datastore_request_timeout.default))

		if len(user_info_res.content.chat_ids >= CONFIG.max_sessions):
			raise TooManySessionsError(CONFIG.max_sessions)

		req = ClientRequestSchema[ChatSVCBase](body=schema, timeout=CONFIG.datastore_request_timeout.session_create)
		res = await DATASTORE.chat.session.create(req)
		return res.content

	@handle_http_exception(ServerError)
	async def delete_chat_session(self, schema: ChatSessionSVCDelete) -> dict | None:
		req = ClientRequestSchema[ChatSessionSVCDelete](body=schema,
		                                                timeout=CONFIG.datastore_request_timeout.session_delete)
		res = await DATASTORE.chat.session.delete(req)
		return res.content

	# Messages.
	@handle_http_exception(ServerError)
	async def _delete_old_messages(self,schema: ChatSVCDeleteOld)->dict|None:
		req = ClientRequestSchema[ChatSVCDeleteOld](body=schema,
		                                            timeout=CONFIG.datastore_request_timeout.message_delete_old)
		return (await DATASTORE.chat.message.delete_old(req)).content

	@handle_http_exception(ServerError)
	async def _get_messages(self, schema: ChatSVCGetLatest) -> MessagesReturn:
		"""
		Get messages and delete old messages. When received messages > maximum messages, the delete old will run.

		Note: Delete all apply only received messages, not for all messages in db.
		That means if a client gets messages < max messages. The delete old will NOT run despite num messages in db > maximum messages.
		This is intentional for overall performance. Because delete only also happens when create a new message.
		"""
		req = ClientRequestSchema[ChatSVCGetLatest](body=schema,
		                                            timeout=CONFIG.datastore_request_timeout.message_get_latest)
		res = await DATASTORE.chat.message.get_latest(req)

		# Delete old
		if len(res.content.messages)> CONFIG.max_messages:
			await self._delete_old_messages(ChatSVCDeleteOld(token_id=schema.token_id,
			                                                 chat_session_id=schema.chat_session_id,
			                                                 remain=CONFIG.max_messages))
			# request again to confirm.
			res = await DATASTORE.chat.message.get_latest(req)
			assert len(res.content.messages)<= CONFIG.max_messages
		return res.content


	@handle_http_exception(ServerError)
	async def _create_message(self, schema: ChatMessageSVCCreate)->MessagesReturn:
		"""
		Create new messages and check if messages <= max messages.
		"""
		c_req = ClientRequestSchema[ChatMessageSVCCreate](body=schema,
		                                                  timeout=CONFIG.datastore_request_timeout.message_create)
		_ = await DATASTORE.chat.message.create(c_req)

		messages = await self._get_messages(ChatSVCGetLatest(token_id=schema.token_id,
		                                                    chat_session_id=schema.chat_session_id,
		                                                    n=-1)) # This will activate delete old in get_massage.content
		# assert len(messages.messages)<= CONFIG.max_messages # already assert in get_messages.
		return messages

	# Chat summary
	@handle_http_exception(ServerError)
	async def _delete_old_chat_summaries(self, schema: ChatSVCDeleteOld)->dict|None:
		req = ClientRequestSchema[ChatSVCDeleteOld](body=schema,
		                                            timeout=CONFIG.datastore_request_timeout.summary_delete_old)
		return (await DATASTORE.chat.summary.delete_old(req)).content


	@handle_http_exception(ServerError)
	async def _get_chat_summaries(self, schema: ChatSVCGetLatest)->ChatSummariesReturn:
		req = ClientRequestSchema[ChatSVCGetLatest](body=schema,
		                                            timeout=CONFIG.datastore_request_timeout.summary_get_latest)
		res = await DATASTORE.chat.summary.get_latest(req)

		# Delete old
		if len(res.content.summaries) > CONFIG.max_chat_summaries:
			await self._delete_old_chat_summaries(
				ChatSVCDeleteOld(token_id=schema.token_id,
				                 chat_session_id=schema.chat_session_id,
				                 remain=CONFIG.max_chat_summaries))
			# request again to confirm.
			res = await DATASTORE.chat.summary.get_latest(req)
			assert len(res.content.summaries) <= CONFIG.max_chat_summaries
		return res.content

	@handle_http_exception(ServerError)
	async def _create_chat_summary(self, schema: ChatSummarySVCCreate)->ChatSummariesReturn:
		c_req = ClientRequestSchema[ChatSummarySVCCreate](body=schema,
		                                                  timeout=CONFIG.datastore_request_timeout.summary_create)
		_ = await DATASTORE.chat.summary.create(c_req)

		summaries = await self._get_chat_summaries(ChatSVCGetLatest(token_id=schema.token_id,
		                                                            chat_session_id=schema.chat_session_id,
		                                                            n=-1))
		# assert len(messages.messages)<= CONFIG.max_messages # already assert in get_messages.
		return summaries

	# User summary
	@handle_http_exception(ServerError)
	async def _delete_old_user_summaries(self, schema: UserSummarySVCDeleteOld)->dict|None:
		req =ClientRequestSchema[UserSummarySVCDeleteOld](body=schema,
		                                                  timeout=CONFIG.datastore_request_timeout.summary_delete_old)
		return (await DATASTORE.user.summary.delete_old(req)).content

	@handle_http_exception(ServerError)
	async def _get_user_summaries(self, schema:UserSummarySVCGetLatest)->UserSummariesReturn:
		"""Get and delete old summaries."""
		req = ClientRequestSchema[UserSummarySVCGetLatest](body=schema,
		                                                   timeout=CONFIG.datastore_request_timeout.summary_get_latest)
		res = await DATASTORE.user.summary.get_latest(req)

		if len(res.content.summaries)>CONFIG.max_user_summaries:
			_= await self._delete_old_user_summaries(UserSummarySVCDeleteOld(token_id=schema.token_id,
			                                                                 remain=CONFIG.max_user_summaries))
			res = await DATASTORE.user.summary.get_latest(req)
			assert len(res.content.summaries)<= CONFIG.max_user_summaries
		return res.content


	@handle_http_exception(ServerError)
	async def _create_user_summary(self,schema: UserSummarySVCCreate)->UserSummariesReturn:
		req = ClientRequestSchema[UserSummarySVCCreate](body=schema,
		                                                timeout=CONFIG.datastore_request_timeout.summary_create)
		_=await DATASTORE.user.summary.create(req)
		summaries = await self._get_user_summaries(UserSummarySVCGetLatest(token_id=schema.token_id,
		                                                                   n=-1))
		return summaries


data_svc = ChatBoneSVC()