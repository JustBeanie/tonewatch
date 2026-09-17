"""Pydantic models defining the non-OpenAPI WebSocket wire protocol."""

from typing import Literal

from pydantic import BaseModel, Field


class SubscribeMessage(BaseModel):
    type: str = "subscribe"
    topics: list[str] = Field(default_factory=list)


class SubscriptionAck(BaseModel):
    type: str = "subscribed"
    topics: list[str] = Field(default_factory=list)


class ToneDiscoveredMessage(BaseModel):
    """Wire shape for the one-shot discovery notification."""

    type: Literal["tone_discovered"] = "tone_discovered"
    data: dict[str, object] = Field(default_factory=dict)


class CallEnrichedMessage(BaseModel):
    """Wire shape for a CAD-enriched call event."""

    type: Literal["call_enriched"] = "call_enriched"
    data: dict[str, object] = Field(default_factory=dict)
