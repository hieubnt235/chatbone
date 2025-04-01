from pwdlib import PasswordHash


# Password utils
password_hash = PasswordHash.recommended()

def hash_password(password:str):
    return password_hash.hash(password)

def verify_password(password:str, hashed_password):
    return password_hash.verify(password,hashed_password)

