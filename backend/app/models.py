from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=2, max_length=1000)
    mode: Literal["lexical", "vector", "hybrid"] = "hybrid"
    document_ids: list[str] | None = Field(default=None, max_length=100)
    limit: int = Field(default=5, ge=1, le=20)


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=2, max_length=1000)
    mode: Literal["lexical", "vector", "hybrid"] = "hybrid"
    document_ids: list[str] | None = Field(default=None, max_length=100)


class DemoSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identity: Literal["viewer", "reviewer"]
