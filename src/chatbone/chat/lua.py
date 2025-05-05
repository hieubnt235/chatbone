from chatbone.chat.settings import REDIS


# language=lua
CREATE_CONNECTION = """
local username = KEYS[1]
local tokens_list_key = KEYS[2]
local new_token_json = ARGV[1]
local initial_info_json = ARGV[2]
local initial_data_json = ARGV[3]
local created = 0

if redis.call('EXISTS', user_hash_key) == 0 then
  -- Use HSET with multiple field/value pairs for initial hash setup
  redis.call('HSET', user_hash_key, 'info', initial_info_json, 'data', initial_data_json)
  -- Can add other initial fields like 'created_at' here too
  redis.call('HSET', user_hash_key, 'created_at', redis.call('TIME')[1])
  created = 1
end
-- Always add the new token to the list
redis.call('LPUSH', tokens_list_key, new_token_json)
return created
"""
LUA=dict(
  create_connection = REDIS.register_script(CREATE_CONNECTION)

)
__all__ = ["lua"]