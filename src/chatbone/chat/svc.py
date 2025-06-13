from contextlib import asynccontextmanager, AsyncExitStack, AbstractAsyncContextManager
from typing import Callable, Coroutine, Self
from uuid import UUID

import redis
from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict
from redis.exceptions import LockError

from chatbone.assistant_interface import AssistantInterface, AssistantData
from chatbone.broker import (UserData as UserDataCache, UserToken, ChatSessionData, Message, WriteStream, ReadStream, )
from chatbone.chat.settings import DATASTORE, CONFIG, AUTH
from utilities.exception import handle_http_exception
from utilities.func import utc_now
from utilities.logger import logger
from utilities.schemas.auth import TokenJWT, UserAuthenticate
from utilities.settings.datastore import *

ServerError = HTTPException(
    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    detail="Something went wrong with server.",
)


def TooManySessionsError(max_sessions: int):
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Too many sessions exist. You have to delete"
        f"some to create new one. Max sessions allowed: {max_sessions}",
    )


AuthenticationError = HTTPException(
    status_code=status.HTTP_407_PROXY_AUTHENTICATION_REQUIRED,
    detail="Chat session authentication fail because of expiring or no authentication.",
)


class _DataSVC(BaseModel):
    """For interacting with data store service.
    TODO: all deletion operations should be become "mark delete" not actual delete.
     The checking for deleting if reach maximum should be delete in cache, instead of direct database.
    """

    __PRIVATE__ = "__PRIVATE__"

    @handle_http_exception(ServerError)
    async def _create_chat_session(self, schema: ChatSVCBase) -> ChatSessionReturn:
        user_info_res = await DATASTORE.user.access.get(
            ClientRequestSchema[Token](
                body=Token(token_id=schema.token_id),
                timeout=CONFIG.datastore_request_timeout.default,
            )
        )

        if len(user_info_res.content.chat_ids >= CONFIG.max_sessions):
            raise TooManySessionsError(CONFIG.max_sessions)

        req = ClientRequestSchema[ChatSVCBase](
            body=schema, timeout=CONFIG.datastore_request_timeout.session_create
        )
        res = await DATASTORE.chat.session.create(req)
        return res.content

    @handle_http_exception(ServerError)
    async def _delete_chat_session(self, schema: ChatSessionSVCDelete) -> dict | None:
        req = ClientRequestSchema[ChatSessionSVCDelete](
            body=schema, timeout=CONFIG.datastore_request_timeout.session_delete
        )
        res = await DATASTORE.chat.session.delete(req)
        return res.content

    # Messages.
    @handle_http_exception(ServerError)
    async def _delete_old_messages(self, schema: ChatSVCDeleteOld) -> dict | None:
        req = ClientRequestSchema[ChatSVCDeleteOld](
            body=schema, timeout=CONFIG.datastore_request_timeout.message_delete_old
        )
        return (await DATASTORE.chat.message.delete_old(req)).content

    @handle_http_exception(ServerError)
    async def _get_messages(self, schema: ChatSVCGetLatest) -> MessagesReturn:
        """
        Get messages and delete old messages. When received messages > maximum messages, the delete old will run.

        Note: Delete all apply only received messages, not for all messages in db.
        That means if a client gets messages < max messages. The delete old will NOT run despite num messages in db > maximum messages.
        This is intentional for overall performance. Because delete only also happens when create a new message.
        """
        req = ClientRequestSchema[ChatSVCGetLatest](
            body=schema, timeout=CONFIG.datastore_request_timeout.message_get_latest
        )
        res = await DATASTORE.chat.message.get_latest(req)

        # Delete old
        if len(res.content.messages) > CONFIG.max_messages:
            await self._delete_old_messages(
                ChatSVCDeleteOld(
                    token_id=schema.token_id,
                    chat_session_id=schema.chat_session_id,
                    remain=CONFIG.max_messages,
                )
            )
            # request again to confirm.
            res = await DATASTORE.chat.message.get_latest(req)
            assert len(res.content.messages) <= CONFIG.max_messages
        return res.content

    @handle_http_exception(ServerError)
    async def _create_message(self, schema: ChatMessageSVCCreate) -> MessagesReturn:
        """
        Create new messages and check if messages <= max messages.
        """
        c_req = ClientRequestSchema[ChatMessageSVCCreate](
            body=schema, timeout=CONFIG.datastore_request_timeout.message_create
        )
        _ = await DATASTORE.chat.message.create(c_req)

        messages = await self._get_messages(
            ChatSVCGetLatest(
                token_id=schema.token_id, chat_session_id=schema.chat_session_id, n=-1
            )
        )  # This will activate delete old in get_massage.content
        # assert len(messages.messages)<= CONFIG.max_messages # already assert in get_messages.
        return messages

    # Chat summary
    @handle_http_exception(ServerError)
    async def _delete_old_chat_summaries(self, schema: ChatSVCDeleteOld) -> dict | None:
        req = ClientRequestSchema[ChatSVCDeleteOld](
            body=schema, timeout=CONFIG.datastore_request_timeout.summary_delete_old
        )
        return (await DATASTORE.chat.summary.delete_old(req)).content

    @handle_http_exception(ServerError)
    async def _get_chat_summaries(
        self, schema: ChatSVCGetLatest
    ) -> ChatSummariesReturn:
        req = ClientRequestSchema[ChatSVCGetLatest](
            body=schema, timeout=CONFIG.datastore_request_timeout.summary_get_latest
        )
        res = await DATASTORE.chat.summary.get_latest(req)

        # Delete old
        if len(res.content.summaries) > CONFIG.max_chat_summaries:
            await self._delete_old_chat_summaries(
                ChatSVCDeleteOld(
                    token_id=schema.token_id,
                    chat_session_id=schema.chat_session_id,
                    remain=CONFIG.max_chat_summaries,
                )
            )
            # request again to confirm.
            res = await DATASTORE.chat.summary.get_latest(req)
            assert len(res.content.summaries) <= CONFIG.max_chat_summaries
        return res.content

    @handle_http_exception(ServerError)
    async def _create_chat_summary(
        self, schema: ChatSummarySVCCreate
    ) -> ChatSummariesReturn:
        c_req = ClientRequestSchema[ChatSummarySVCCreate](
            body=schema, timeout=CONFIG.datastore_request_timeout.summary_create
        )
        _ = await DATASTORE.chat.summary.create(c_req)

        summaries = await self._get_chat_summaries(
            ChatSVCGetLatest(
                token_id=schema.token_id, chat_session_id=schema.chat_session_id, n=-1
            )
        )
        # assert len(messages.messages)<= CONFIG.max_messages # already assert in get_messages.
        return summaries

    # User summary
    @handle_http_exception(ServerError)
    async def _delete_old_user_summaries(
        self, schema: UserSummarySVCDeleteOld
    ) -> dict | None:
        req = ClientRequestSchema[UserSummarySVCDeleteOld](
            body=schema, timeout=CONFIG.datastore_request_timeout.summary_delete_old
        )
        return (await DATASTORE.user.summary.delete_old(req)).content

    @handle_http_exception(ServerError)
    async def _get_user_summaries(
        self, schema: UserSummarySVCGetLatest
    ) -> UserSummariesReturn:
        """Get and delete old summaries."""
        req = ClientRequestSchema[UserSummarySVCGetLatest](
            body=schema, timeout=CONFIG.datastore_request_timeout.summary_get_latest
        )
        res = await DATASTORE.user.summary.get_latest(req)

        if len(res.content.summaries) > CONFIG.max_user_summaries:
            _ = await self._delete_old_user_summaries(
                UserSummarySVCDeleteOld(
                    token_id=schema.token_id, remain=CONFIG.max_user_summaries
                )
            )
            res = await DATASTORE.user.summary.get_latest(req)
            assert len(res.content.summaries) <= CONFIG.max_user_summaries
        return res.content

    @handle_http_exception(ServerError)
    async def _create_user_summary(
        self, schema: UserSummarySVCCreate
    ) -> UserSummariesReturn:
        req = ClientRequestSchema[UserSummarySVCCreate](
            body=schema, timeout=CONFIG.datastore_request_timeout.summary_create
        )
        _ = await DATASTORE.user.summary.create(req)
        summaries = await self._get_user_summaries(
            UserSummarySVCGetLatest(token_id=schema.token_id, n=-1)
        )
        return summaries


class AssistantApp(BaseModel):
    """Store captured of assistant apps at the creation time. This will be used for validating data.
    Notes:
            This class does not check the change of assistant app dynamically, should be refreshed and recreate if something wrong.

    """

    model_config = ConfigDict(arbitrary_types_allowed=True)
    app_name: str
    schema: type[AssistantData]

    @classmethod
    async def create(cls, assistant_app_name) -> Self:
        schema = await AssistantInterface.get_assistant_schema(assistant_app_name)
        return cls(app_name=assistant_app_name, schema=schema)


class ChatHandle(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    write_stream: WriteStream
    read_stream: ReadStream
    task: asyncio.Task


# noinspection PyMethodMayBeStatic
class ChatAssistantSVC(_DataSVC):
    """
    This class support static check for validating captured assistant apps., If something wrong, need to recreate to reinit (user refresh page)
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)
    userdata: UserDataCache
    assistant_apps: dict[str, AssistantApp]
    """keys are assistant name, value contain app_name"""

    @property
    def assistant_names(self) -> list[str]:
        return list(self.assistant_apps.keys())

    def __init__(self, _ud, _as, *__PRIVATE__):
        if not __PRIVATE__ == self.__PRIVATE__:
            raise ValueError(
                "Does not support create this class through constructor, use 'create' method instead."
            )
        super().__init__(userdata=_ud, assistant_app=_as)

    @classmethod
    async def create(cls, userdata: UserDataCache):
        obj = cls(_ud=userdata, _as={}, __PRIVATE__=cls.__PRIVATE__)
        await obj.refresh()

    async def refresh(self):
        """Recapture all assistant apps and reload userdata."""
        await self._init_all_assistant_app()
        await self._init_user_data()

    async def create_chat_session(self) -> UUID:
        return (
            await self._call_data_svc_method(
                self._create_chat_session, ChatSVCBase(token_id=self.token_id)
            )
        ).id

    # Support delete later, for now just close chat session instead. Deletion should be handle outside the app.
    async def delete_chat_session(self, chat_session_id: UUID):
        return await self._call_data_svc_method(
            self._delete_chat_session,
            ChatSessionSVCDelete(
                token_id=self.token_id, chat_session_ids=chat_session_id
            ),
        )

    async def get_chat_session(self, chat_session_id: UUID) -> ChatSessionData:
        """
        Get chat session data, such as messages or summary.If userdata does not have a chat session, call database for it.
        Returns:
        """
        try:
            return (await self.userdata.get_chat_sessions([chat_session_id]))[
                chat_session_id
            ]
        except redis.ResponseError:
            logger.info(
                f"No chat session with id '{chat_session_id}' found in cache. Try to load from datastore."
            )
            messages = await self._call_data_svc_method(
                self._get_messages,
                ChatSVCGetLatest(
                    token_id=self.token_id, chat_session_id=chat_session_id
                ),
            )
            chat_summaries = await self._call_data_svc_method(
                self._get_chat_summaries,
                ChatSVCGetLatest(
                    token_id=self.token_id,
                    chat_session_id=chat_session_id,
                ),
            )

            def _extract():
                s = [s.summary for s in chat_summaries.summaries]
                m = [Message(role=m.role, content=m.content) for m in messages.messages]
                return {
                    chat_session_id: ChatSessionData(
                        id=chat_session_id, messages=m, summaries=s
                    )
                }

            await self.userdata.update(
                "chat_sessions", await asyncio.to_thread(_extract)
            )
            return (await self.userdata.get_chat_sessions([chat_session_id]))[
                chat_session_id
            ]

    @asynccontextmanager
    async def chat(
        self, assistant_name: str, data: AssistantData, chat_session_id: UUID
    ) -> AbstractAsyncContextManager[ChatHandle]:
        """
        Args:
                assistant_name:
                data:
                chat_session_id:
        Raises:
                ValueError: assistant name or data are not correct.
        Notes:
                Both errors may be solved by recreating this object (user refresh page). Or maybe internal server error.

        Yields:
                Tuple (WriteStream, ReadStream)
        """
        try:
            assistant_app = self.assistant_apps[assistant_name]
            assert isinstance(data, assistant_app.schema)
        except (KeyError, AssertionError) as e:
            raise ValueError(f"Static check fail for assistant. {e}")

        cs = await self.get_chat_session(chat_session_id)
        async with AsyncExitStack() as stack:
            try:
                streams = await stack.enter_async_context(
                    cs.get_streams(
                        write_streams_acquire_timeout=CONFIG.write_stream_accquire_timeout
                    )
                )
            except LockError:
                streams = await stack.enter_async_context(
                    cs.get_streams(read_only=True)
                )

            # todo: prepare context.
            #

            task = await stack.enter_async_context(
                AssistantInterface.call(assistant_name, data, *streams["as2cs"])
            )
            chat_handle = ChatHandle(
                write_stream=streams["cs2as"][0],
                read_stream=streams["cs2as"][1],
                task=task,
            )
            yield chat_handle  # chat app uses these streams.

            # TODO: persist data.
        # // HACK

    @property
    def token_id(self) -> UUID:
        return self.userdata.user_token.id

    async def _init_all_assistant_app(self):
        names = await AssistantInterface.get_assistant_names()
        for n in names:
            self.assistant_apps[n[1]] = await AssistantApp.create(n[0])

    async def _init_user_data(self):
        await self.userdata.refresh(exclude={})
        if not self.userdata.summaries:
            user_summaries = await self._call_data_svc_method(
                self._get_user_summaries,
                UserSummarySVCGetLatest(token_id=self.token_id),
            )

            def _extract():
                return [s.summary for s in user_summaries.summaries]

            await self.userdata.append("summaries", await asyncio.to_thread(_extract))
            await self.userdata.refresh(exclude={})

    async def _call_data_svc_method[
        S, T
    ](self, func: Callable[[S], Coroutine[..., ..., T]], schema: S) -> T:
        assert hasattr(schema, "token_id")
        try:
            return await func(schema)
        except HTTPException as he:
            if (
                he.detail == "__TOKEN_ERROR__"
            ):  # __TOKEN_ERROR__ is the special HTTP exception from datastore service
                logger.info(f"Access token was expired, reauthenticate.")
                await self._re_authenticate()
                schema.token_id = self.token_id
                try:
                    return await func(schema)
                except:
                    raise RuntimeError("Token still not valid after re authenticate.")
            raise

    async def _re_authenticate(self):
        """This method must only be called when token is expired."""
        username = self.userdata.username
        password = self.userdata.password
        req = ClientRequestSchema[UserAuthenticate](
            data=UserAuthenticate(username=username, password=password)
        )
        token_jwt: TokenJWT = (await AUTH.authenticate(req)).content
        token: TokenInfoReturn = (
            await AUTH.get_user(
                ClientRequestSchema(
                    headers={"Authorization": f"Bearer {token_jwt.access_token}"}
                )
            )
        ).content.tokens[-1]
        user_token = UserToken.model_validate(
            token, from_attributes=True
        )  # It's maybe redundant
        assert (
            user_token.expires_at > utc_now()
        )  # Must, or reimplement auth/datastore service.
        await self.userdata.set("user_token", user_token)
        self.userdata = await self.userdata.refresh(include={"user_token"})
