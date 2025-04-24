import asyncio
import json
from pathlib import Path
from chatbone_utils.settings import chatbone_settings
async def load_chat():
    users: list[User] = []
    with open(Path('./chat.json').resolve()) as f:
        chats = json.load(f)
        for u in chats:
            user = User(username=u['username'],
                        hashed_password=u['hashed_password'])
            for c in u['chat_sessions']:
                chat_sessions = ChatSession()
                chat_sessions.messages.add_all([Message(**m) for m in c['messages']])
                user.chat_sessions.append(chat_sessions)
            users.append(user)


    async with chatbone_settings.chat_db.session() as session:
        for user in users:
            session.add(user)

asyncio.run(load_chat())
