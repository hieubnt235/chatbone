alembic -n chat_db revision --autogenerate -m "First migration"
alembic -n chat_db upgrade head
#python ./scripts/load_chat.py