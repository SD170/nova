"""All JSON shapes the news tools return (the brain's contract)."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

DataSource = Literal["live", "demo"]


class Topic(BaseModel):
    id: str            # what you pass to fetch_news, e.g. "world"
    label: str
    kind: Literal["section", "custom"]
    outlets: list[str] = Field(default_factory=list)


class TopicsOut(BaseModel):
    sections: list[Topic]
    custom_topics: str  # how free-text topics work
    examples: list[str]


class NewsItem(BaseModel):
    id: str                       # stable: sha1(url)[:12]
    title: str
    url: str                      # link to the original article (source_url rule)
    source: str                   # outlet, e.g. "NPR"
    published_at: Optional[str]   # UTC ISO-8601
    topic: str                    # which requested topic it belongs to
    outlets: int = 1              # independent newsrooms reporting this story
    confirmed: bool = False       # outlets >= 2
    also_reported_by: list[dict] = Field(default_factory=list)  # [{source, url}]
    summary: str = ""
    trusted: bool = True
    data_source: DataSource = "live"


class TopicStatus(BaseModel):
    topic: str
    kind: str
    ok: bool
    count: int
    providers: list[str] = Field(default_factory=list)


class NewsOut(BaseModel):
    generated_at: str
    topics: list[str]
    since_hours: int
    trusted_only: bool
    data_source: DataSource = "live"
    count: int
    links: list[str]              # every article link, in order — the quick answer
    items: list[NewsItem]
    by_topic: list[TopicStatus]
    speak: str                    # short spoken summary for voice


class ItemDetail(NewsItem):
    text: str = ""
    text_available: bool = False
    text_note: str = ""


class DedupeIn(BaseModel):
    id: str
    title: str
    source: str = ""
    url: str = ""
    published_at: Optional[str] = None


class Cluster(BaseModel):
    lead_id: str
    ids: list[str]
    sources: list[str]
    outlets: int
    confirmed: bool


class DedupeOut(BaseModel):
    clusters: list[Cluster]


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] | str = Field(default_factory=dict)


class Health(BaseModel):
    ok: bool
    data_source: DataSource
    tools: list[str]
    keyed_sources: dict[str, bool]
    cached_stories: int
    push_subscribers: int
    auth_required: bool
