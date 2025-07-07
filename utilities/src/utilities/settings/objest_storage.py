import io
from copy import deepcopy
from datetime import timedelta
from typing import BinaryIO, Union, Dict, List, Tuple

from miniopy_async import Minio
from miniopy_async.helpers import ObjectWriteResult
from pydantic import BaseModel, model_validator, Field, ConfigDict

from utilities import logger


class ObjectStorageSettings(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")
    endpoint: str
    access_key: str
    secret_key: str
    secure: bool = True

    bucket: str

    optional_kwargs: dict = dict()

    client: Minio = Field(exclude=True)

    @model_validator(mode="before")
    @classmethod
    def init_storage(cls, env_vars: dict):
        if (s := env_vars.get("secure")) is not None:
            env_vars["secure"] = False if int(s) == 0 else True
        else:
            env_vars["secure"] = True
        ev = deepcopy(env_vars)
        bucket = ev.pop("bucket")
        optional_kwargs = ev.pop("optional_kwargs", {})
        client = Minio(**ev, **optional_kwargs)

        env_vars["secret_key"] = "*" * len(ev["secret_key"])
        env_vars["client"] = client

        return env_vars

    async def verify_bucket(self):
        if not (await self.client.bucket_exists(self.bucket)):
            logger.info(f"New bucket '{self.bucket}' created.")
            await self.client.make_bucket(self.bucket)

    async def get_upload_url(
        self,
        object_name: str,
        expires: timedelta = timedelta(days=7),
        *,
        response_headers: Dict[str, Union[str, List[str], Tuple[str]]] | None = None,
        content_type: str | None = None,
        tagging: dict[str, str] = None,
    ):
        await self.verify_bucket()
        extra_query_params = {}
        if content_type:
            extra_query_params.update({"content-type": content_type})
        if tagging:
            tags = ""
            for k, v in tagging.items():
                if tags != "":
                    tags += "&"
                tags += f"{k}={v}"
            extra_query_params.update({"x-amz-tagging": tags})

        return await self.client.get_presigned_url(
            "PUT",
            self.bucket,
            object_name,
            expires,
            response_headers,
            extra_query_params=extra_query_params,
        )

    async def get_download_url(
        self,
        object_name: str,
        expires: timedelta = timedelta(days=7),
        *,
        response_headers: Dict[str, Union[str, List[str], Tuple[str]]] | None = None,
    ):
        await self.verify_bucket()
        return await self.client.presigned_get_object(
            self.bucket, object_name, expires, response_headers=response_headers
        )

    async def get_object(
        self,
        object_name: str,
        offset: int = 0,
        length: int = 0,
    ) -> bytes:
        await self.verify_bucket()
        res = await self.client.get_object(self.bucket, object_name)
        return await res.read()

    async def put_object(
        self,
        object_name: str,
        data: BinaryIO | io.BytesIO,
        content_type: str = "application/octet-stream",
        metadata: dict | None = None,
    ) -> ObjectWriteResult:
        await self.verify_bucket()
        return await self.client.put_object(
            self.bucket, object_name, data, -1, content_type, metadata
        )

    async def remove_object(self, object_name: str) -> None:
        await self.client.remove_object(self.bucket, object_name)
