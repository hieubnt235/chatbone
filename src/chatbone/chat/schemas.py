from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ReturnMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: str
    content: str
    created_at: datetime