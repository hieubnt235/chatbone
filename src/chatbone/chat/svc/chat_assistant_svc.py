from fastapi import WebSocket
from purse import RedisHash

from chatbone.settings import REDIS
from utilities.exception import handle_http_exception
from utilities.settings.clients.datastore import *

"""
1. User do auth in frontend, frontend init ticket in redis:
	ticket = dict(
		active_token: UUID # must)
	then return the browser app to user, with that ticket to access to chatserver.

2. User access to chatserver, chatserver first check the ticket, if not have data, chatserver will init the data using active token.
Then ticket hashkey become like this:
	ticket = dict(
		data: UserData 
		active_token: UUID # must

3. If the active token is expired (cannot call datastore) or None, delete active token and send jsonrpc to user, 
wait until timeout for the active token not None.
The browser app must somehow re validate, and update active token.

4. Pass query to assistant apps, assistant only aware about the ticket and data key. 
Does not need to know it success or not, if data is None, it mean not any information.
"""


class ChatAssistantSVC:
	"""
	- Load User history, info, summary to object storage and distribute it.
	"""

	@handle_http_exception(ServerError)
	async def connect_chat_session(self, ws: WebSocket, user_ticket: str, chat_session_id: UUID):
		r = REDIS.new()
		rh = RedisHash(r, user_ticket, UserData)
		if not await rh.contains(user_ticket):
			raise AuthenticationError
		user_data = await rh.get(user_ticket)
		assert isinstance(user_data, UserData)


chat_assistant_svc = ChatAssistantSVC()
