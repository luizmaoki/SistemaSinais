"""Validated operator-only catalog imports and point-in-time alias resolution.

Imports identify instruments only by an explicit UUID. CIK identifies a filer,
not a listing. Identifier revisions and import receipts are append-only.
"""
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from app.calendars import SUPPORTED_CALENDARS, catalog_calendar
from app.database import utcnow
from app.models import Asset, AssetIdentifier, CatalogImport, MarketBar


class ImportRejected(ValueError):
    pass


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def check_uri(value, demo):
    parsed = urlparse(value)
    if demo and parsed.scheme == "fixture" and parsed.path and not (parsed.query or parsed.fragment or parsed.username or parsed.password):
        return value
    if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("source_uri must be an HTTP(S) reference; fixture: is allowed only for DEMO")
    return value


def normalized_identifier(kind, value):
    value = value.strip()
    if kind == "cik":
        if not value.isascii() or not value.isdigit() or len(value) > 10:
            raise ValueError("CIK must contain 1-10 ASCII digits")
        return value.zfill(10)
    return value.upper() if kind in {"ticker", "isin", "figi", "cusip"} else value


class IdentifierInput(StrictInput):
    native_id: str = Field(min_length=1, max_length=100)
    version: int = Field(default=1, ge=1, le=1000000)
    identifier_type: Literal["ticker", "cik", "isin", "figi", "cusip", "vendor", "contract_address"]
    value: str = Field(min_length=1, max_length=100)
    venue: str | None = Field(default=None, max_length=100)
    chain_id: str | None = Field(default=None, max_length=30)
    effective_from: date | None = None
    effective_to: date | None = None
    cancelled: bool = False

    @model_validator(mode="after")
    def validate_identity(self):
        self.value = normalized_identifier(self.identifier_type, self.value)
        if self.effective_from and self.effective_to and self.effective_from >= self.effective_to:
            raise ValueError("Identifier validity is [effective_from, effective_to), with from < to")
        if self.identifier_type == "contract_address" and not self.chain_id:
            raise ValueError("Contract addresses require chain_id scope")
        if self.identifier_type != "contract_address" and self.chain_id:
            raise ValueError("chain_id is only valid for a contract_address identifier")
        if self.identifier_type == "ticker" and not self.venue:
            raise ValueError("Ticker identifiers require venue scope")
        return self


class AssetInput(StrictInput):
    id: UUID
    symbol: str = Field(min_length=1, max_length=30)
    display_name: str = Field(min_length=1, max_length=200)
    asset_type: Literal["equity", "adr", "etf", "etn", "etp", "reit", "option", "future", "perpetual", "bond", "index", "forex", "commodity", "crypto"]
    currency: str = Field(pattern=r"^[A-Z][A-Z0-9]{2,7}$")
    venue: str = Field(min_length=1, max_length=100)
    timezone: str = Field(min_length=1, max_length=50)
    calendar_id: Literal["XNYS", "24/7"] | None = None
    primary_exchange: str | None = Field(default=None, max_length=100)
    mic: str | None = Field(default=None, pattern=r"^[A-Z0-9]{4}$")
    instrument_identifier: str | None = Field(default=None, max_length=50)
    instrument_kind: Literal["spot", "root", "contract", "perpetual"] = "spot"
    underlying_asset_id: UUID | None = None
    contract_multiplier: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=8)
    option_type: Literal["call", "put"] | None = None
    strike: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=8)
    expiration: date | None = None
    chain_id: str | None = Field(default=None, max_length=30)
    contract_address: str | None = Field(default=None, max_length=100)
    status: Literal["active", "inactive", "delisted"] = "active"
    listed_at: date | None = None
    delisted_at: date | None = None
    sector: str | None = Field(default=None, max_length=100)
    cik: str | None = None
    identifiers: list[IdentifierInput] = Field(default_factory=list, max_length=100)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown IANA timezone") from None
        return value

    @model_validator(mode="after")
    def validate_instrument(self):
        if self.cik:
            self.cik = normalized_identifier("cik", self.cik)
        if self.listed_at and self.delisted_at and self.listed_at >= self.delisted_at:
            raise ValueError("Listing date must precede delisting date")
        if self.calendar_id:
            if self.calendar_id != catalog_calendar(self.asset_type, self.venue, self.instrument_kind):
                raise ValueError("Calendar is not supported for this class and venue")
            if self.timezone != SUPPORTED_CALENDARS[self.calendar_id]:
                raise ValueError("Timezone does not match the assigned calendar")
        if self.asset_type == "option":
            if self.instrument_kind != "contract" or not all((self.underlying_asset_id, self.contract_multiplier, self.option_type, self.strike, self.expiration)):
                raise ValueError("Options require underlying, multiplier, type, strike, expiration and contract kind")
        elif any(v is not None for v in (self.option_type, self.strike)):
            raise ValueError("Option fields are only valid for options")
        if self.asset_type == "future":
            if self.instrument_kind not in {"root", "contract"}:
                raise ValueError("Futures require explicit root or contract kind")
            if self.instrument_kind == "contract" and not all((self.expiration, self.underlying_asset_id, self.contract_multiplier)):
                raise ValueError("Dated futures require expiration, underlying and multiplier")
            if self.instrument_kind == "root" and self.expiration:
                raise ValueError("A futures root must not pretend to have a contract expiration")
        if self.asset_type == "perpetual":
            if self.instrument_kind != "perpetual" or self.expiration or not all((self.underlying_asset_id, self.contract_multiplier)):
                raise ValueError("Perpetuals require underlying and multiplier, and have no expiration")
        if self.asset_type not in {"option", "future", "perpetual"}:
            if self.instrument_kind != "spot" or any(v is not None for v in (self.expiration, self.contract_multiplier, self.underlying_asset_id)):
                raise ValueError("Derivative fields require an explicit derivative class")
        if self.contract_address and (self.asset_type != "crypto" or not self.chain_id):
            raise ValueError("Crypto contract_address requires chain_id")
        if self.chain_id and self.asset_type != "crypto":
            raise ValueError("chain_id requires the crypto class")
        if len({i.native_id for i in self.identifiers}) != len(self.identifiers):
            raise ValueError("Duplicate identifier native_id in one instrument")
        for identifier in self.identifiers:
            if identifier.identifier_type == "contract_address" and identifier.chain_id != self.chain_id:
                raise ValueError("Identifier chain scope differs from instrument chain")
        return self


class CatalogDocument(StrictInput):
    schema_version: Literal[1] = 1
    source_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,49}$")
    source_uri: str = Field(min_length=1, max_length=2000)
    available_as_of: AwareDatetime
    metadata_status: Literal["VERIFIED", "UNVERIFIED", "DEMO"]
    assets: list[AssetInput] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_document(self):
        demo = self.metadata_status == "DEMO"
        check_uri(self.source_uri, demo)
        if self.source_id.startswith("demo") != demo:
            raise ValueError("DEMO and real metadata require distinct source identities")
        if len({item.id for item in self.assets}) != len(self.assets):
            raise ValueError("Duplicate asset UUID in document")
        if len({(a.symbol, a.venue, a.asset_type) for a in self.assets}) != len(self.assets):
            raise ValueError("Duplicate current symbol/venue/class in document")
        return self


def import_catalog(session, payload, *, _demo_ingested_at=None):
    document = CatalogDocument.model_validate(payload)
    ingested_at = utcnow()
    if _demo_ingested_at is not None:
        if document.metadata_status != "DEMO":
            raise ImportRejected("Only built-in DEMO fixtures may set ingestion time")
        ingested_at = _demo_ingested_at
    if document.available_as_of > ingested_at:
        raise ImportRejected("Metadata is not yet available at ingestion time")
    canonical = document.model_dump(mode="json")
    digest = checksum(canonical)
    if session.scalar(select(CatalogImport.id).where(CatalogImport.checksum == digest)):
        return {"inserted": 0, "updated": 0, "identifiers_inserted": 0, "status": "UNCHANGED", "checksum": digest}
    incoming_ids = {str(a.id) for a in document.assets}
    # Validate references and current-key collisions before any mutation. The
    # legacy uniqueness constraint remains deliberately more restrictive than UUID identity.
    for item in document.assets:
        collision = session.scalar(select(Asset).where(Asset.symbol == item.symbol, Asset.venue == item.venue, Asset.asset_type == item.asset_type, Asset.id != str(item.id)))
        if collision:
            raise ImportRejected("CATALOG_KEY_COLLISION: symbol/venue/class already belongs to another UUID")
        existing = session.get(Asset, str(item.id))
        if existing:
            if (existing.asset_type, existing.venue, existing.currency) != (item.asset_type, item.venue, item.currency):
                raise ImportRejected("Changing an instrument class, venue or currency requires a distinct UUID")
            if session.scalar(select(MarketBar.id).where(MarketBar.asset_id == existing.id).limit(1)):
                for field in ("timezone", "calendar_id", "contract_multiplier", "instrument_kind", "option_type", "strike"):
                    if getattr(existing, field) != getattr(item, field):
                        raise ImportRejected("Metadata interpreting existing bars is immutable: " + field)
            for field in ("underlying_asset_id", "chain_id", "contract_address", "expiration", "option_type", "strike"):
                old, new = getattr(existing, field), getattr(item, field)
                if isinstance(new, UUID):
                    new = str(new)
                if old is not None and old != new:
                    raise ImportRejected("Instrument contract identity cannot be reassigned: " + field)
            if existing.metadata_available_as_of and document.available_as_of < existing.metadata_available_as_of:
                raise ImportRejected("Stale metadata cannot replace a newer catalog record")
        if item.underlying_asset_id:
            ref = str(item.underlying_asset_id)
            if ref == str(item.id) or (ref not in incoming_ids and not session.get(Asset, ref)):
                raise ImportRejected("Underlying UUID is missing or self-referential")
    # Cycles among derivative references are never valid instrument identities.
    links = {str(a.id): str(a.underlying_asset_id) for a in document.assets if a.underlying_asset_id}
    for first in links:
        seen, cursor = set(), first
        while cursor:
            if cursor in seen:
                raise ImportRejected("Cyclic underlying references")
            seen.add(cursor)
            if cursor in links:
                cursor = links[cursor]
            else:
                row = session.get(Asset, cursor)
                cursor = row.underlying_asset_id if row else None
    inserted = updated = aliases = 0
    with session.begin_nested():
        # First insert all UUIDs without dependency links, then assign underlyings.
        for item in document.assets:
            if not session.get(Asset, str(item.id)):
                values = item.model_dump(exclude={"identifiers", "underlying_asset_id"})
                values["id"] = str(item.id)
                session.add(Asset(**values))
                inserted += 1
        session.flush()
        for item in document.assets:
            row = session.get(Asset, str(item.id))
            if row.metadata_source_id is not None:
                updated += 1
            for name, value in item.model_dump(exclude={"id", "identifiers"}).items():
                setattr(row, name, str(value) if name == "underlying_asset_id" and value else value)
            row.metadata_status = document.metadata_status
            row.metadata_source_id = document.source_id
            row.metadata_source_uri = document.source_uri
            row.metadata_available_as_of = document.available_as_of
            row.metadata_ingested_at = ingested_at
            for alias in item.identifiers:
                values = alias.model_dump(mode="json")
                alias_digest = checksum(values)
                revisions = list(session.scalars(select(AssetIdentifier).where(AssetIdentifier.asset_id == row.id, AssetIdentifier.source_id == document.source_id, AssetIdentifier.native_id == alias.native_id).order_by(AssetIdentifier.version.desc())))
                matching = next((r for r in revisions if r.version == alias.version), None)
                if matching:
                    if matching.checksum != alias_digest:
                        raise ImportRejected("Identifier revision is immutable; increment version for a correction")
                    continue
                if revisions and alias.version <= revisions[0].version:
                    raise ImportRejected("Identifier revision must increase monotonically")
                if revisions and document.available_as_of < revisions[0].available_as_of:
                    raise ImportRejected("Identifier correction cannot predate the preceding revision")
                session.add(AssetIdentifier(asset_id=row.id, **alias.model_dump(), source_id=document.source_id, source_uri=document.source_uri, available_as_of=document.available_as_of, ingested_at=ingested_at, checksum=alias_digest))
                aliases += 1
        session.add(CatalogImport(checksum=digest, source_id=document.source_id, source_uri=document.source_uri, available_as_of=document.available_as_of, ingested_at=ingested_at, asset_count=len(document.assets), payload=canonical))
        session.flush()
    return {"inserted": inserted, "updated": updated, "identifiers_inserted": aliases, "status": "IMPORTED", "checksum": digest}


def visible_identifiers(session, known_at: datetime, asset_id=None):
    query = select(AssetIdentifier).where(AssetIdentifier.available_as_of <= known_at, AssetIdentifier.ingested_at <= known_at)
    if asset_id:
        query = query.where(AssetIdentifier.asset_id == str(asset_id))
    latest = {}
    for row in session.scalars(query.order_by(AssetIdentifier.version.desc(), AssetIdentifier.id)):
        key = (row.asset_id, row.source_id, row.native_id or row.id)
        latest.setdefault(key, row)
    return sorted((r for r in latest.values() if not r.cancelled), key=lambda r: (r.identifier_type, r.value, r.venue or "", r.id))


def resolve_identifiers(session, identifier_type, value, effective_on: date, known_at: datetime, venue=None, chain_id=None):
    value = normalized_identifier(identifier_type, value)
    return sorted({row.asset_id for row in visible_identifiers(session, known_at) if row.identifier_type == identifier_type and row.value == value and (venue is None or row.venue == venue) and (chain_id is None or row.chain_id == chain_id) and (row.effective_from is None or row.effective_from <= effective_on) and (row.effective_to is None or effective_on < row.effective_to)})
