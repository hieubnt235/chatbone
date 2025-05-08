import asyncio
from uuid import UUID

from sqlalchemy import select, delete

from chatbone import AccessToken, User
from utilities.settings import chatbone_settings

chat_db = chatbone_settings.chat_db

from datastore.repo import UserRepo
from chatbone import ChatRepo
from utilities.utils import get_expire_date
from uuid_extensions import uuid7


async def main():
	username = str(uuid7())[:30]
	password = 'efaesfsefesfse'

	# Register
	async with chat_db.session() as session:
		repo = UserRepo(session)
		await repo.create(username=username, hashed_password=password)
	logger.info(f"Created {username}")

	# Login
	async with chat_db.session() as session:
		repo = UserRepo(session)
		token = await repo.authenticate(username=username, hashed_password=password, expires_date=get_expire_date())

		logger.info(f"token_id: {token}")

	# Create session
	async with chat_db.session() as session:
		repo = ChatRepo(session)

		logger.info(await repo.list_chat_sessions(token))
		token = await repo.create_chat_session(token)
		logger.info(await repo.list_chat_sessions(token))


async def main2():
	"""
	test with chat
	Returns:

	"""
	u = "A"
	p = "efaesfsefesfse"

	async with chat_db.session() as session:
		repo = UserRepo(session)
		token_id = await repo.authenticate(username=u, hashed_password=p, expires_date=get_expire_date())

		logger.info(f"token_id: {token_id}")


# async def test():
#     u = "A"
#     p = "efaesfsefesfse"
#     try:
#         async with chat.session() as session:
#             repo = UserRepo(session)
#             await repo.create(username=u,hashed_password=p)
#     except Exception as e:
#         logger.info(f"Exception type: {e.__class__.__name__}.")
#         logger.info(f"Exception message: {e}")

async def test_delete():
	async with chat_db.session() as session:

		try:
			q = select(AccessToken).where(AccessToken.id == UUID('067dc0f0-0de8-75bd-8000-299da71cc276'))
			token = await session.scalar(q)

			q = select(User).where(User.id == AccessToken.user_id)
			user = await session.scalar(q)

			logger.info("START")
			logger.info(token)
			logger.info(len(user.tokens))

			# await session.delete(token)
			dq = delete(AccessToken).where(AccessToken.id == UUID('067dc0f0-0de8-75bd-8000-299da71cc276'))
			await session.execute(dq)
			await session.flush()
			logger.info(f"token after delete {token}")

			logger.info(len(user.tokens))
			await session.refresh(user)
			logger.info("After refresh")
			logger.info(len(user.tokens))
			await session.rollback()



		except Exception as e:
			logger.exception(e)  # logger.info(user)  # logger.info(token.user)


async def delete_user():
	user_id = '067dbdc9-8126-7e56-8000-a14eef761e8a'
	async with chat_db.session() as session:
		user = await session.scalar(select(User).where(User.id == user_id))
		logger.info(user.tokens)
		logger.info(user.id)
		logger.info(user.username)

		await session.execute(delete(User).where(User.id == user_id))
		# await session.delete(user)
		await session.flush()

		# await session.refresh(user)
		user = await session.scalar(select(User).where(User.id == user_id))
		logger.info("after delete")
		logger.info(user)  # logger.info(user)

		# await session.rollback()


async def serialization():
	token_id = '067dc3b0-ed31-79f7-8000-a58adce55655'
	try:
		async with chat_db.session() as session:
			token = await session.scalar(select(AccessToken).where(AccessToken.id == token_id))
			logger.info(token.as_dict().pop('user_id'))
	except Exception as e:
		logger.exception(e)


async def chat_repo():
	"""
	test
	Returns:

	"""
	pass


if __name__ == "__main__":
	# asyncio.run(main())
	# asyncio.run(main2())
	# asyncio.run(test())
	# asyncio.run(test_delete())
	# asyncio.run(delete_user())
	asyncio.run(serialization())
