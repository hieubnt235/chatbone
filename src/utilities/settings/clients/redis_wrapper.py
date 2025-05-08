__all__ = ["RedisWrapperConfig", "RedisWrapperClient"]

from abc import abstractmethod, ABC
from contextlib import asynccontextmanager, AbstractAsyncContextManager
from copy import deepcopy
from functools import partial
from typing import Any, Literal, Coroutine, Callable, Set, TYPE_CHECKING, Awaitable
from purse import Redlock
from pydantic import BaseModel, model_validator, ConfigDict, Field
from redis.asyncio import Redis, RedisCluster, Sentinel, ConnectionPool
from redis.asyncio.sentinel import SlaveNotFoundError
from utilities.logger import logger
from utilities.settings import Config

# --- Set of known Redis read-only commands ---
_READ_ONLY_COMMANDS: Set[str] = {"get", "mget", "strlen", "getrange", "getbit", "hget", "hmget", "hgetall", "hlen",
	"hkeys", "hvals", "hexists", "hstrlen", "hrandfield", "lindex", "llen", "lrange", "lpos", "scard", "sismember",
	"smembers", "srandmember", "sdiff", "sinter", "sunion", "sscan", "zcard", "zcount", "zscore", "zrank", "zrevrank",
	"zrange", "zrevrange", "zrangebyscore", "zrevrangebyscore", "zlexcount", "zrangebylex", "zrevrangebylex", "zscan",
	"geodist", "geohash", "geopos", "georadius", "georadiusbymember", "geosearch", "exists", "type", "keys", "scan",
	"ping", "echo", "time", "dbsize", "ttl", "pttl", "dump", "object", "memory", "bitcount", "bitpos", "cluster",
	"readonly", "json.get", "json.mget", "json.type", "json.strlen", "json.objlen", "json.objkeys", "json.arrlen",
	"json.arrindex", }

if TYPE_CHECKING:
	_REDIS = Redis | RedisCluster
else:
	_REDIS = object


class RedisWrapperConfig(Config):
	decode_responses: bool = True


class RedisWrapperParams(BaseModel):
	host: str
	port: int
	db: int
	password: str
	config: RedisWrapperConfig | None = None

	def _make_params(self) -> dict:
		params = self.model_dump()
		if (config := params.pop('config', None)) is not None:
			config.pop('config_file')
			params.update(config)
		return params


class _RedisWrapperAbstract(BaseModel, ABC, _REDIS):
	@abstractmethod
	def new(self) -> Redis | RedisCluster:
		"""Create new client object."""

	def __getattr__(self, item) -> Callable[..., Coroutine | Awaitable] | Awaitable | Any:
		"""If call be standard redis method directly, WITHOUT any reimplementation in subclass, create new one and call."""
		return getattr(self.new(), item)


class _RWrapper(_RedisWrapperAbstract, ABC):
	mode: str = Field(description="For discriminator.")
	params: RedisWrapperParams
	redlock_params: list[RedisWrapperParams] | None = None

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

		self._params: dict = self.params._make_params()
		if self.redlock_params is not None:
			self._redlock_params = [rp._make_params() for rp in self.redlock_params]
		else:
			self.redlock_params = [self.params]
			self._redlock_params = [self._params]

		self._redlock_masters = [Redis(**rlp) for rlp in self._redlock_params]


class SentinelWrapper(_RWrapper):
	mode: Literal['sentinel']

	def __init__(self, **kwargs):
		self.redis_kwargs = kwargs['redis_kwargs']
		self.sentinel = Sentinel(**kwargs)
		self._mf = partial(self.sentinel.master_for, **self.redis_kwargs)
		self._sf = partial(self.sentinel.slave_for, **self.redis_kwargs)
		super().__init__()

	class _NewRedis(_REDIS):
		def __init__(self, mf: Callable[..., Redis], sf: Callable[..., Redis]):
			super().__init__()
			self._mf = mf
			self._sf = sf
			self.master: Redis = self._mf()  # must
			self.slave: Redis | None = None

		def _get_redis(self, item: str) -> Redis:
			if item not in _READ_ONLY_COMMANDS:
				return self.master
			else:
				if self.slave is not None:
					return self.slave
				# slave is None
				try:
					self.slave = self._sf()
					return self.slave
				except SlaveNotFoundError:
					return self.master

		async def _wrapper_method(self, item: str, *args, **kwargs) -> Any:
			r = self._get_redis(item)
			if r == self.master:
				return await getattr(r, item)(*args, **kwargs)
			else:
				try:
					return await getattr(r, item)(*args, **kwargs)
				except Exception as e:
					logger.debug(e)
					return await getattr(self.master, item)(*args, **kwargs)

		def __getattr__(self, item):
			return partial(self._wrapper_method, item=item)

	def new(self) -> Redis | RedisCluster:
		return self._NewRedis(self._mf, self._sf)


class ClusterWrapper(_RWrapper):
	mode: Literal['cluster']

	async def new(self) -> Redis | RedisCluster:
		pass


class RedisWrapper(_RWrapper):
	mode: Literal['redis']

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self._pool = ConnectionPool(**self._params)
		self._redlock = [Redis(**p) for p in self._redlock_params]

	def new(self) -> Redis | RedisCluster:
		return Redis(connection_pool=self._pool)

class RedisWrapperClient(_RedisWrapperAbstract,_REDIS):
	# noinspection PyUnresolvedReferences
	"""Input is 'mode' and all client arguments. Data and config will merge to each other.
		When called directly by Redis API, Create a new real Redis instance and call.
		To create a new Redis instance, call new()

		Attributes:
			mode: "redis" or "sentinel" or "cluster"
			params: parameters of class RedisWrapperParams
			redlock_params: list of parameters of RedisWrapperParams, default is the redis-server with params.

		Examples:
			r = RedisWrapperClient(mode='redis', params=dict(host="localhost", port=3333, db=0, password="2352001",
														 config=dict(decode_responses=True)))
			redis = r.new()
			async def task1():
				class Token(BaseModel):
					id: int
					expired_at: datetime

				class User(BaseModel):
					tokens: list[Token]
					username: str
					password: str

				user_dict = {"tokens": [{"id": 1, "expired_at": get_expire_date(100000)},
										{"id": 1, "expired_at": get_expire_date(100000)}], "username": "hieu",
							 "password": "2352001"}
				user = User(**user_dict)
				rh = RedisHash(redis, user.username, User)
				await rh.clear()
				await rh.update({user.username: user})
				a = await rh.get(user.username)
				print(a)
				print (type(a))

		"""
	model_config = ConfigDict(arbitrary_types_allowed=True)
	rwrapper: RedisWrapper | SentinelWrapper | ClusterWrapper = Field(discriminator="mode")

	# noinspection PyNestedDecorators
	@model_validator(mode='before')
	@classmethod
	def create_wrapper(cls, data: dict) -> dict:
		return {'rwrapper': deepcopy(data)}

	def new(self) -> Redis | RedisCluster:
		return self.rwrapper.new()

	@property
	def redlock_masters(self) -> list[Redis]:
		return self.rwrapper._redlock_masters

	@asynccontextmanager
	async def redlock(self, key: str, raise_on_redis_errors=False, auto_release_time: int = 10_000,
	                  num_extensions: int = 3, context_manager_blocking: bool = True,
	                  context_manager_timeout: float = -1) -> AbstractAsyncContextManager[Redlock]:
		"""Lock the key.
		Args:
			key:
            masters: a list of redis connection objects
			raise_on_redis_errors:
			auto_release_time: milliseconds to auto-release the lock if not extended
			num_extensions: -1 for infinite extensions
			context_manager_blocking: block if locked
			context_manager_timeout: optional timeout, or -1 for infinite

		Examples:
			async with r.redlock("redlock:list_lock") as redlock:
				assert isinstance(redlock, Redlock)
		"""
		async with Redlock(key, self.redlock_masters, raise_on_redis_errors, auto_release_time, num_extensions,
		                   context_manager_blocking, context_manager_timeout) as redlock:
			yield redlock

	def __getattr__(self, item: str) -> Callable[..., Coroutine]:
		return getattr(self.rwrapper, item)


if __name__ == '__main__':
	import asyncio
	from purse import RedisHash, Redlock, RedisList
	from datetime import datetime
	from utilities.func import get_expire_date
	from random import random

	r = RedisWrapperClient(mode='redis', params=dict(host="localhost", port=3333, db=0, password="2352001",
	                                                 config=dict(decode_responses=True)))
	redis = r.new()

	async def task1():
		class Token(BaseModel):
			id: int
			expired_at: datetime

		class User(BaseModel):
			tokens: list[Token]
			username: str
			password: str

		user_dict = {"tokens": [{"id": 1, "expired_at": get_expire_date(100000)},
		                        {"id": 1, "expired_at": get_expire_date(100000)}], "username": "hieu",
		             "password": "2352001"}

		user = User(**user_dict)
		rh = RedisHash(redis, user.username, User)
		await rh.clear()
		await rh.update({user.username: user})
		a = await rh.get(user.username)
		print(a)
		print(type(a))


	async def task2(n):
		rlist = RedisList(redis, "redis_list", str)
		for x in range(n):
			async with r.redlock("redlock:list_lock") as redlock:
				assert isinstance(redlock, Redlock)
				cl = await rlist.len()
				if cl == 0:
					await rlist.append("0")
					current_num = 0
				else:
					current_num = int(await rlist.getitem(-1))

				# This sleep simulates the processing time of the job - up to 100ms here
				await asyncio.sleep(0.1 * random())

				# Get the job done, which is add 1 to the last number
				current_num += 1

				print(f"the task {asyncio.current_task().get_name()} working on item #: {current_num}")

				await rlist.append(str(current_num))


	async def main():
		logger.info("Task 1.")
		await task1()

		logger.info("Task 2.")
		rlist = RedisList(redis, "redis_list", str)
		await rlist.clear()

		# run 10 async threads (or tasks) in parallel, each one to perform 10 increments
		await asyncio.gather(*[asyncio.create_task(task2(10)) for _ in range(3)])

		pre = int(await rlist.getitem(0))
		for i in (await rlist.slice(1, -1)):
			i = int(i)
			print(pre, i)
			assert i > pre
			pre = i
		return "success"

	asyncio.run(main())
