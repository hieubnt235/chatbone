from typing import Any, Sequence

from sqlalchemy import select, and_, exists

from utilities.exception import handle_exception, BaseMethodException
from utilities.mixin import RepoMixin

from datastore.entities import User, UserSummary


class UserRepoException(BaseMethodException):
	pass


class UserRepo(RepoMixin):
	@handle_exception(UserRepoException)
	async def create(self,  username: str, hashed_password: str) -> User:
		"""
		For sign up
		Create a new user with hashed password.
		Args:
			username (str): The username of the new user.
			hashed_password (str): The hashed password of the new user.
		"""
		user = User(username=username, hashed_password=hashed_password)
		self._session.add(user)
		await self.flush()
		await self.refresh(user)
		return user

	@handle_exception(UserRepoException)
	async def get_verify(self, username: str, hashed_password: str) -> User | None:
		"""
		For login
		Check if a user already exists by username. Should be called before creating a new user.
		Args:
		 hashed_password:
			username (str): The username to check for existence.
		Returns:
			bool: True if the user exists, False otherwise.
		"""
		q = select(User).where(and_(User.username == username, User.hashed_password == hashed_password))
		return await self._session.scalar(q)

	@handle_exception(UserRepoException)
	async def is_existing(self,username:str)->bool:
		q= select(exists().where(User.username==username))
		return await self._session.scalar(q)

	@handle_exception(UserRepoException)
	async def delete(self, user:User):
		await self._session.delete(user)

	@handle_exception(UserRepoException)
	async def create_summary(self, user: User,summary:str):
		await self.refresh(user)
		self._session.add(user)
		s = UserSummary(summary=summary)
		user.summaries.add(s)
		await self.flush()

	@handle_exception(UserRepoException)
	async def get_summaries(self,user:User, n:int=-1)->Sequence[UserSummary]:
		"""
		Get n latest summaries.
		Args:
			user:
			n: n<0 to get all summaries

		Returns:
		"""
		q = user.summaries.select().order_by(UserSummary.created_at.desc())
		if n>=0:
			q=q.limit(n)
		r = await self._session.scalars(q)
		return r.all()

	@handle_exception(UserRepoException)
	async def delete_old_summaries(self,user:User, max_summaries:int):
		"""
		Delete old summaries while keeping the length of remaining summaries <= max_summaries.
		If max_summaries==0 delete all user's summaries.
		Args:
			user:
			max_summaries:
		"""
		assert max_summaries>=0
		sq = (select(UserSummary.id)
		     .where(UserSummary.user_id==user.id)
		     .order_by(UserSummary.created_at.desc())
		     .offset(max_summaries)
		     .subquery())
		await self._session.execute(user.summaries.delete()
		                            .where(and_(UserSummary.id.in_(sq),UserSummary.user_id==user.id) ))
		await self.flush()


	@handle_exception(UserRepoException)
	async def flush(self):
		await self._session.flush()

	@handle_exception(UserRepoException)
	async def refresh(self, obj: Any):
		await self._session.flush()


class UserRepoAdmin(UserRepo):
	"""
	//TODO
	"""
	pass


__all__ = ["UserRepo", "UserRepoException"]
