from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class Capability:
    dataset: str
    asset_classes: tuple[str, ...]
    latency_class: str


@dataclass(frozen=True)
class ProviderHealth:
    provider_id: str
    status: str
    message: str | None = None


@dataclass(frozen=True)
class NormalizedQuery:
    asset_id: str
    symbol: str
    cik: str | None = None
    start: datetime | None = None
    end: datetime | None = None


@dataclass(frozen=True)
class RawProviderEvent:
    native_id: str
    payload: dict[str, Any]
    fetched_at: datetime


@dataclass(frozen=True)
class NormalizedEvent:
    native_id: str
    source_id: str
    event_type: str
    published_at: datetime
    available_as_of: datetime
    ingested_at: datetime
    source_uri: str
    evidence_kind: str
    data_mode: str
    payload: dict[str, Any] = field(default_factory=dict)


class ProviderAdapter(Protocol):
    provider_id: str

    async def health(self) -> ProviderHealth: ...
    async def capabilities(self) -> list[Capability]: ...
    async def fetch(self, query: NormalizedQuery) -> list[RawProviderEvent]: ...
    async def normalize(self, events: list[RawProviderEvent]) -> list[NormalizedEvent]: ...
