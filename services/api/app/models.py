from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, UTCDateTime, utcnow


def new_id() -> str:
    return str(uuid4())


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(30), default="owner")


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("symbol", "venue", "asset_type"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    asset_type: Mapped[str] = mapped_column(String(40), index=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    venue: Mapped[str] = mapped_column(String(100))
    primary_exchange: Mapped[str | None] = mapped_column(String(100))
    mic: Mapped[str | None] = mapped_column(String(10))
    instrument_identifier: Mapped[str | None] = mapped_column(String(50))
    underlying_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))
    contract_multiplier: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    option_type: Mapped[str | None] = mapped_column(String(8))
    strike: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    expiration: Mapped[date | None] = mapped_column(Date)
    chain_id: Mapped[str | None] = mapped_column(String(30))
    contract_address: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="active")
    timezone: Mapped[str] = mapped_column(String(50), default="America/New_York")
    listed_at: Mapped[date | None] = mapped_column(Date)
    delisted_at: Mapped[date | None] = mapped_column(Date)
    sector: Mapped[str | None] = mapped_column(String(100))
    cik: Mapped[str | None] = mapped_column(String(10), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class AssetIdentifier(Base):
    __tablename__ = "asset_identifiers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), index=True)
    identifier_type: Mapped[str] = mapped_column(String(30))
    value: Mapped[str] = mapped_column(String(100))
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    source_id: Mapped[str] = mapped_column(String(50))


class CorporateAction(Base):
    __tablename__ = "asset_corporate_actions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), index=True)
    action_type: Mapped[str] = mapped_column(String(40))
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime)
    details: Mapped[dict] = mapped_column(JSON)
    source_id: Mapped[str] = mapped_column(String(50))
    data_mode: Mapped[str] = mapped_column(String(30))


class MarketBar(Base):
    __tablename__ = "market_bars"
    __table_args__ = (
        UniqueConstraint("asset_id", "source_id", "timeframe", "event_time"),
        Index("ix_bars_asset_source_time", "asset_id", "source_id", "event_time"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    source_id: Mapped[str] = mapped_column(String(50))
    timeframe: Mapped[str] = mapped_column(String(10), default="1d")
    event_time: Mapped[datetime] = mapped_column(UTCDateTime)
    close_time: Mapped[datetime] = mapped_column(UTCDateTime)
    open: Mapped[Decimal] = mapped_column(Numeric(26, 8))
    high: Mapped[Decimal] = mapped_column(Numeric(26, 8))
    low: Mapped[Decimal] = mapped_column(Numeric(26, 8))
    close: Mapped[Decimal] = mapped_column(Numeric(26, 8))
    volume: Mapped[Decimal] = mapped_column(Numeric(30, 8))
    data_mode: Mapped[str] = mapped_column(String(30))
    evidence_kind: Mapped[str] = mapped_column(String(20), default="OBSERVED")
    adjustment: Mapped[str] = mapped_column(String(30), default="unadjusted")
    source_uri: Mapped[str | None] = mapped_column(Text)
    available_as_of: Mapped[datetime] = mapped_column(UTCDateTime)
    ingested_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ProviderState(Base):
    __tablename__ = "data_providers"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="NOT_CONFIGURED")
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    records_ingested: Mapped[int] = mapped_column(Integer, default=0)


class Filing(Base):
    __tablename__ = "filings"
    __table_args__ = (
        UniqueConstraint("source_id", "accession_number", "version"),
        UniqueConstraint("source_id", "accession_number", "raw_payload_checksum"),
        Index("ix_filings_asset_published", "asset_id", "published_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    cik: Mapped[str] = mapped_column(String(10), index=True)
    accession_number: Mapped[str] = mapped_column(String(40))
    form: Mapped[str] = mapped_column(String(30), index=True)
    title: Mapped[str] = mapped_column(String(300))
    filing_date: Mapped[date] = mapped_column(Date)
    filing_period_end: Mapped[date | None] = mapped_column(Date)
    published_at: Mapped[datetime] = mapped_column(UTCDateTime)
    publication_precision: Mapped[str] = mapped_column(String(20), default="timestamp")
    event_time: Mapped[datetime] = mapped_column(UTCDateTime)
    available_as_of: Mapped[datetime] = mapped_column(UTCDateTime)
    ingested_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    source_id: Mapped[str] = mapped_column(String(50), default="sec_edgar")
    source_uri: Mapped[str] = mapped_column(Text)
    data_mode: Mapped[str] = mapped_column(String(30), default="END_OF_DAY")
    evidence_kind: Mapped[str] = mapped_column(String(30), default="REPORTED")
    version: Mapped[int] = mapped_column(Integer, default=1)
    raw_payload_checksum: Mapped[str] = mapped_column(String(71))
    metadata_json: Mapped[dict] = mapped_column(JSON)


class MacroEvent(Base):
    __tablename__ = "macro_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    country: Mapped[str] = mapped_column(String(5))
    importance: Mapped[str] = mapped_column(String(20))
    scheduled_at: Mapped[datetime] = mapped_column(UTCDateTime)
    released_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    actual: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    consensus: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    previous: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    revised_previous: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    unit: Mapped[str] = mapped_column(String(30))
    source_id: Mapped[str] = mapped_column(String(50), default="demo")
    source_uri: Mapped[str | None] = mapped_column(Text)
    data_mode: Mapped[str] = mapped_column(String(30), default="DEMO")
    evidence_kind: Mapped[str] = mapped_column(String(30), default="SIMULATED")
    ingested_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Watchlist(Base):
    __tablename__ = "watchlists"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class WatchlistAsset(Base):
    __tablename__ = "watchlist_assets"
    watchlist_id: Mapped[str] = mapped_column(ForeignKey("watchlists.id", ondelete="CASCADE"), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AlertRule(Base):
    __tablename__ = "alert_rules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), index=True)
    threshold: Mapped[Decimal] = mapped_column(Numeric(26, 8))
    direction: Mapped[str] = mapped_column(String(10))
    source_id: Mapped[str] = mapped_column(String(50), default="demo")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (UniqueConstraint("rule_id", "bar_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    rule_id: Mapped[str] = mapped_column(ForeignKey("alert_rules.id"))
    bar_id: Mapped[str] = mapped_column(ForeignKey("market_bars.id"))
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    message: Mapped[str] = mapped_column(String(400))
    observed_price: Mapped[Decimal] = mapped_column(Numeric(26, 8))
    threshold: Mapped[Decimal] = mapped_column(Numeric(26, 8))
    source_id: Mapped[str] = mapped_column(String(50))
    data_mode: Mapped[str] = mapped_column(String(30))
    evidence_kind: Mapped[str] = mapped_column(String(30))
    event_time: Mapped[datetime] = mapped_column(UTCDateTime)
    available_as_of: Mapped[datetime] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider_id: Mapped[str] = mapped_column(String(50), index=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(30))
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(100))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
