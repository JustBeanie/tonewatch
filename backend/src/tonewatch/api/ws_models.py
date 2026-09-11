"""Pydantic models defining the non-OpenAPI WebSocket wire protocol."""

from pydantic import BaseModel, Field


class SubscribeMessage(BaseModel):
    type: str = "subscribe"
    topics: list[str] = Field(default_factory=list)


class SubscriptionAck(BaseModel):
    type: str = "subscribed"
    topics: list[str] = Field(default_factory=list)
