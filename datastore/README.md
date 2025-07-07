Data store Service
SHOULD NOT VERIFY any thing

REPO:

/token:
create_token(User,max_tokens) ->Token
get_token(token_id) ->Token

# for admin
get_all_tokens()
delete_expired_tokens()
delete_all_tokens()
delete_user_tokens(User,username) # user must currently have access (has vaid token) to delete all tokens.

User:
create_user(username,hashed_password)->User
verify_user(username,hashed_password)-> User
upgrade_password(User,hashed_password)

get_user_summaries(User)


delete_user(user_id,username)


/user_summary
get_summary_ids(user_id)->list
create_user_summary(user_id)

get_user_summaries(user_id)->list[user_summary]

get_user_summary(summary_id)

delete_user_summary(summary_id)


/chat:

SHOULD HAVE ONLY ONE TOKEN ACTIVE. NOT ALLOW 1 session access by two machine at sametime.
cache the user in used in chat. And each user has only one token.

AUTH SERVICE:
register: create_user-> verify_user ->create_token(User,max_tokens) -> encode_jwt 
login: verify_user->create_token(User,max_tokens)-> encoder_jwt
logout: decode_jwt -> delete_token(token_id)

#user by chat repo
auth: decode_jwt-> get_token(token_id) -> User= Token.user -> User
delete_expires...

Auth also in datastore

Function first, finegrant later
Beside CRUD, provide easy access, high level task but still use simple db operation.