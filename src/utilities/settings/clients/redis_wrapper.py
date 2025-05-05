__all__=["RedisWrapperConfig","RedisWrapperClient"]

from abc import abstractmethod, ABC
from copy import deepcopy
from functools import partial
from typing import Any, Literal, Coroutine, Callable, Set, TYPE_CHECKING, Awaitable

from pydantic import BaseModel, model_validator, ConfigDict, Field
from redis.asyncio import Redis, RedisCluster, Sentinel, ConnectionPool
from redis.asyncio.sentinel import SlaveNotFoundError
from utilities.logger import logger
from utilities.settings import Config

# --- Set of known Redis read-only commands ---
_READ_ONLY_COMMANDS: Set[str] = {
    "get", "mget", "strlen", "getrange", "getbit", "hget", "hmget", "hgetall", "hlen",
    "hkeys", "hvals", "hexists", "hstrlen", "hrandfield", "lindex", "llen", "lrange",
    "lpos", "scard", "sismember", "smembers", "srandmember", "sdiff", "sinter",
    "sunion", "sscan", "zcard", "zcount", "zscore", "zrank", "zrevrank", "zrange",
    "zrevrange", "zrangebyscore", "zrevrangebyscore", "zlexcount", "zrangebylex",
    "zrevrangebylex", "zscan", "geodist", "geohash", "geopos", "georadius",
    "georadiusbymember", "geosearch", "exists", "type", "keys", "scan", "ping",
    "echo", "time", "dbsize", "ttl", "pttl", "dump", "object", "memory", "bitcount",
    "bitpos", "cluster", "readonly", "json.get", "json.mget", "json.type", "json.strlen",
    "json.objlen", "json.objkeys", "json.arrlen", "json.arrindex",
}

if TYPE_CHECKING:
	_REDIS = Redis|RedisCluster
else:
	_REDIS = object

# TODO: deep test redis clients

class _RWrapper(BaseModel,ABC,_REDIS):
	mode:str =Field(description="For discriminator.")

	@abstractmethod
	def new(self)->Redis|RedisCluster:
		"""Create new client object."""

	def __getattr__(self, item)->Callable[...,Coroutine|Awaitable]| Awaitable |Any:
		"""If call be standard redis method directly, WITHOUT any reimplementation in subclass, create new one and call."""
		return getattr(self.new(), item)

class SentinelWrapper(_RWrapper):


	mode:Literal['sentinel']
	def __init__(self,**kwargs):
		self.redis_kwargs = kwargs['redis_kwargs']
		self.sentinel = Sentinel(*args,**kwargs)
		self._mf = partial(self.sentinel.master_for,**self.redis_kwargs)
		self._sf = partial(self.sentinel.slave_for,**self.redis_kwargs)
		super().__init__()

	class _NewRedis(_REDIS):
		def __init__(self,mf:Callable[...,Redis], sf:Callable[...,Redis]):
			super().__init__()
			self._mf = mf
			self._sf=sf
			self.master:Redis = self._mf() # must
			self.slave: Redis|None = None

		def _get_redis(self,item:str)-> Redis:
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
		return self._NewRedis(self._mf,self._sf)
class ClusterWrapper(_RWrapper):
	mode:Literal['cluster']
	async def new(self) -> Redis | RedisCluster:
		pass

class RedisWrapper(_RWrapper):
	mode:Literal['redis']
	def __init__(self,*args,**kwargs):
		super().__init__(*args,**kwargs)
		kwargs.pop('mode')
		self._pool = ConnectionPool(*args,**kwargs)
	def new(self) -> Redis | RedisCluster:
		return Redis(connection_pool=self._pool)

class RedisWrapperConfig(Config):
	"TODO complete this class."
	decode_responses:bool = True


# noinspection PyNestedDecorators
class RedisWrapperClient(_RWrapper):
	"""Input is 'mode' and all client arguments. Data and config will merge to each other.
	When call directly by Redis API, Create new real Redis instance and call.
	To create new Redis instance, call new()
	"""
	model_config = ConfigDict(arbitrary_types_allowed=True)

	rwrapper: RedisWrapper | SentinelWrapper | ClusterWrapper = Field(exclude=True, discriminator="mode")
	config:RedisWrapperConfig|None=None

	# env setting
	mode:Literal['redis','cluster','sentinel']
	url:str|None=None
	host:str|None=None
	port:int|None=None
	db:int|None=None
	password:str|None=None

	@model_validator(mode='before')
	@classmethod
	def create_wrapper(cls,data:dict)->dict:
		data = deepcopy(data) # for not change original data.

		if (config:=data.pop('config',None)) is not None:
			config = RedisWrapperConfig(file=config['file'])

		data['rwrapper'] = deepcopy(data) # for not recursively assignment
		data['rwrapper'].update(config.model_dump(exclude='config_file') if config is not None else {})

		data['config']=config
		data['password'] = '*'*len(data['password'])
		return data

	def new(self) -> Redis | RedisCluster:
		return self.rwrapper.new()

	def __getattr__(self, item:str) ->Callable[...,Coroutine]:
		return getattr(self.rwrapper,item)


if __name__=='__main__':
	r = RedisWrapperClient(mode='redis',host="localhost",port=3333,db=0,password="2352001",decode_responses=True)
	class Model(BaseModel):
		a:int
	async def main():
		s =await r.hset("s",mapping=Model(a=4).model_dump())
		print(s)
		b = await r.hget("s","a")
		print(b)
	import asyncio
	asyncio.run(main())