__all__=["RedisWrapperConfig","RedisWrapperClient"]

from functools import partial
from typing import Any, Literal, Coroutine, Callable, Set, TYPE_CHECKING

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
	_REDIS = Redis
else:
	_REDIS = object

# TODO: deep test redis clients

class SentinelWrapper(Sentinel,_REDIS):
	def __init__(self,*args, redis_kwargs:dict,**kwargs):
		super(Sentinel).__init__(*args,**kwargs)

		self.redis_kwargs = redis_kwargs
		self.master:Redis = self.master_for(**self.redis_kwargs)
		self.slave: Redis|None = None

	def _get_redis(self,item:str)->Redis:
		if item not in _READ_ONLY_COMMANDS:
			return self.master
		else:
			if self.slave is not None:
				return self.slave
			# slave is None
			try:
				self.slave = self.slave_for(**self.redis_kwargs)
				return self.slave
			except SlaveNotFoundError:
				return self.master

	async def _wrapper_method(self,item:str,*args,**kwargs)->Any:
		r = self._get_redis(item)
		if r==self.master:
			return await getattr(r,item)(*args,**kwargs)
		else:
			try:
				return await getattr(r,item)(*args,**kwargs)
			except Exception as e:
				logger.debug(e)
				return await getattr(self.master,item)(*args,**kwargs)

	def __getattr__(self, item:str)->Callable[...,Coroutine]|Any:
		return partial(self._wrapper_method,item=item)

class RedisWrapper:
	def __init__(self,*args,**kwargs):
		self._pool = ConnectionPool(*args,**kwargs)

	def __getattr__(self, item:str)->Callable[...,Coroutine]|Any:
		return getattr(Redis(connection_pool=self._pool),item)

REDIS_MODES = dict(redis= RedisWrapper,
                   sentinel=SentinelWrapper,
                   cluster=RedisCluster
                   )

class RedisWrapperConfig(Config):
	decode_responses:bool = True


# noinspection PyNestedDecorators
class RedisWrapperClient(BaseModel,_REDIS):
	"""Input is 'mode' and all client arguments."""
	model_config = ConfigDict(arbitrary_types_allowed=True)

	# env setting
	mode:Literal['redis','cluster','sentinel']
	url:str|None=None
	host:str|None=None
	port:int|None=None
	db:int|None=None
	password:str|None=None

	# config (env__file)
	config:RedisWrapperConfig|None=None

	client: RedisWrapper | SentinelWrapper | RedisCluster = Field(exclude=True)

	@model_validator(mode='before')
	@classmethod
	def create_client(cls,data:dict)->dict:
		if data.get('client') is None:
			mode = data.pop('mode')
			if data.get('config') is not None:
				data['config'] = RedisWrapperConfig(file=data['config']['file'])

			data['client'] = REDIS_MODES[mode](**data)
			data['mode'] = mode
			data['password'] = '*'*len(data['password'])

		return data

	def __getattr__(self, item:str) ->Callable[...,Coroutine]:
		return getattr(self.client,item)


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