from fastapi import FastAPI
from ray import serve
from ray.serve import ingress

from datastore.api.user_access import router as user_access_router
from datastore.api.user_summary import router as user_summary_router
from datastore.api.chat_session import router as chat_session_router
from datastore.api.chat_message import router as chat_message_router
from datastore.api.chat_summary import router as chat_summary_router
app = FastAPI()

app.include_router(user_access_router, prefix='/user/access', tags=['User'])
app.include_router(user_summary_router, prefix='/user/summary',tags=['User'])

app.include_router(chat_session_router,prefix='/chat/session',tags=['Chat'])
app.include_router(chat_message_router,prefix='/chat/message',tags=['Chat'])
app.include_router(chat_summary_router,prefix='/chat/summary',tags=['Chat'])

@serve.deployment(name='datastore_app')
@ingress(app)
class DatastoreApp:
    pass

datastore_app = DatastoreApp.bind()
serve.run(datastore_app,blocking=True)