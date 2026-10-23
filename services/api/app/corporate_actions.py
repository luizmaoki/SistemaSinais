"""Immutable corporate-action revisions and explicitly declared source coverage."""
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import select

from app.calendars import CalendarUnavailable, session_schedule
from app.catalog import ImportRejected, StrictInput, check_uri, checksum
from app.database import utcnow
from app.models import Asset, CorporateAction, CorporateActionCoverage


class SplitDetails(StrictInput):
    new_shares: Decimal = Field(gt=0, le=Decimal("1e12"), max_digits=25, decimal_places=12)
    old_shares: Decimal = Field(gt=0, le=Decimal("1e12"), max_digits=25, decimal_places=12)


class DividendDetails(StrictInput):
    amount: Decimal = Field(gt=0, le=Decimal("1e12"), max_digits=25, decimal_places=12)
    currency: str = Field(pattern=r"^[A-Z][A-Z0-9]{2,7}$")


class ActionInput(StrictInput):
    native_id: str = Field(min_length=1, max_length=100)
    version: int = Field(ge=1, le=1000000)
    action_type: Literal["split", "cash_dividend"]
    effective_date: date
    details: dict
    cancelled: bool = False
    available_as_of: AwareDatetime | None = None
    source_uri: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_details(self):
        model = SplitDetails if self.action_type == "split" else DividendDetails
        self.details = model.model_validate(self.details).model_dump(mode="json")
        return self


class CoverageInput(StrictInput):
    model_config = {**StrictInput.model_config, "populate_by_name": True}
    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")
    complete: bool

    @model_validator(mode="after")
    def validate_range(self):
        if not 0 <= (self.to_date - self.from_date).days <= 3660:
            raise ValueError("Coverage must span 0-3660 days")
        return self


class ActionsDocument(StrictInput):
    schema_version: Literal[1] = 1
    asset_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    source_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,49}$")
    source_uri: str = Field(min_length=1, max_length=2000)
    data_mode: Literal["DEMO", "END_OF_DAY"]
    dataset_id: str = Field(min_length=1, max_length=100)
    version: int = Field(ge=1, le=1000000)
    available_as_of: AwareDatetime
    coverage: CoverageInput
    events: list[ActionInput] = Field(max_length=5000)

    @model_validator(mode="after")
    def validate_document(self):
        demo = self.data_mode == "DEMO"
        check_uri(self.source_uri, demo)
        if self.source_id.startswith("demo") != demo:
            raise ValueError("DEMO and real actions require distinct source identities")
        if len({e.native_id for e in self.events}) != len(self.events):
            raise ValueError("A snapshot must contain at most one revision per event")
        for event in self.events:
            if not self.coverage.from_date <= event.effective_date <= self.coverage.to_date:
                raise ValueError("Event lies outside declared coverage")
            if event.available_as_of and event.available_as_of > self.available_as_of:
                raise ValueError("Coverage cannot be known before an included event")
            if event.source_uri:
                check_uri(event.source_uri, demo)
        return self


def latest_actions(session, asset_id, source_id, data_mode, as_of, *, include_cancelled=False):
    query = select(CorporateAction).where(
        CorporateAction.asset_id == str(asset_id), CorporateAction.source_id == source_id,
        CorporateAction.data_mode == data_mode, CorporateAction.available_as_of <= as_of,
        CorporateAction.ingested_at <= as_of, CorporateAction.native_id.is_not(None),
    ).order_by(CorporateAction.version.desc(), CorporateAction.id)
    latest = {}
    for event in session.scalars(query):
        latest.setdefault(event.native_id, event)
    return sorted((e for e in latest.values() if include_cancelled or not e.cancelled), key=lambda e: (e.effective_at, e.native_id))


def latest_coverage(session, asset_id, source_id, data_mode, as_of):
    query = select(CorporateActionCoverage).where(
        CorporateActionCoverage.asset_id == str(asset_id), CorporateActionCoverage.source_id == source_id,
        CorporateActionCoverage.data_mode == data_mode, CorporateActionCoverage.available_as_of <= as_of,
        CorporateActionCoverage.ingested_at <= as_of,
    ).order_by(CorporateActionCoverage.version.desc(), CorporateActionCoverage.id)
    latest = {}
    for row in session.scalars(query):
        latest.setdefault(row.dataset_id, row)
    return sorted(latest.values(), key=lambda r: (r.coverage_from, r.coverage_to, r.dataset_id))


def import_actions(session, payload, *, _demo_ingested_at=None):
    document = ActionsDocument.model_validate(payload)
    ingested_at = utcnow()
    if _demo_ingested_at is not None:
        if document.data_mode != "DEMO":
            raise ImportRejected("Only built-in DEMO fixtures may set ingestion time")
        ingested_at = _demo_ingested_at
    if document.available_as_of > ingested_at:
        raise ImportRejected("Actions are not yet available at ingestion time")
    asset = session.get(Asset, document.asset_id)
    if not asset:
        raise ImportRejected("Unknown asset UUID")
    digest = checksum(document.model_dump(mode="json", by_alias=True))
    coverages = list(session.scalars(select(CorporateActionCoverage).where(
        CorporateActionCoverage.asset_id == asset.id, CorporateActionCoverage.source_id == document.source_id,
        CorporateActionCoverage.data_mode == document.data_mode, CorporateActionCoverage.dataset_id == document.dataset_id,
    ).order_by(CorporateActionCoverage.version.desc())))
    same = next((r for r in coverages if r.version == document.version), None)
    if same:
        if same.checksum != digest:
            raise ImportRejected("Coverage revision is immutable; increment version for a correction")
        return {"inserted": 0, "status": "UNCHANGED", "checksum": digest}
    if coverages and (document.version <= coverages[0].version or document.available_as_of < coverages[0].available_as_of):
        raise ImportRejected("Coverage revisions and availability must increase monotonically")
    current = latest_actions(session, asset.id, document.source_id, document.data_mode, ingested_at)
    if document.coverage.complete:
        included = {e.native_id for e in document.events}
        # Removing an earlier reported event requires an explicit cancelled revision.
        for old in current:
            if document.coverage.from_date <= old.effective_at.date() <= document.coverage.to_date and old.native_id not in included:
                raise ImportRejected("Complete snapshot omitted an existing event; include a cancellation revision")
    prepared = []
    for event in document.events:
        try:
            schedule = session_schedule(event.effective_date, event.effective_date, asset.calendar_id)
        except CalendarUnavailable as error:
            raise ImportRejected(str(error)) from None
        if event.effective_date not in schedule:
            raise ImportRejected("Corporate action effective_date must be a trading session")
        effective_at = schedule[event.effective_date][0]
        if event.action_type == "cash_dividend" and event.details["currency"] != asset.currency:
            raise ImportRejected("Dividend currency differs from instrument currency; no implicit FX")
        content = event.model_dump(mode="json", exclude={"available_as_of", "source_uri"})
        event_digest = checksum(content)
        revisions = list(session.scalars(select(CorporateAction).where(
            CorporateAction.asset_id == asset.id, CorporateAction.source_id == document.source_id,
            CorporateAction.data_mode == document.data_mode, CorporateAction.native_id == event.native_id,
        ).order_by(CorporateAction.version.desc())))
        matching = next((r for r in revisions if r.version == event.version), None)
        if matching:
            if matching.checksum != event_digest:
                raise ImportRejected("Event revision is immutable; increment version for a correction")
            continue
        available = event.available_as_of or document.available_as_of
        if revisions and (event.version <= revisions[0].version or available < revisions[0].available_as_of):
            raise ImportRejected("Event revisions and availability must increase monotonically")
        prepared.append(CorporateAction(asset_id=asset.id, action_type=event.action_type, effective_at=effective_at, details=event.details, source_id=document.source_id, data_mode=document.data_mode, native_id=event.native_id, version=event.version, checksum=event_digest, source_uri=event.source_uri or document.source_uri, available_as_of=available, ingested_at=ingested_at, cancelled=event.cancelled))
    with session.begin_nested():
        session.add_all(prepared)
        session.add(CorporateActionCoverage(asset_id=asset.id, source_id=document.source_id, data_mode=document.data_mode, dataset_id=document.dataset_id, version=document.version, coverage_from=document.coverage.from_date, coverage_to=document.coverage.to_date, complete=document.coverage.complete, checksum=digest, source_uri=document.source_uri, available_as_of=document.available_as_of, ingested_at=ingested_at))
        session.flush()
    return {"inserted": len(prepared), "status": "IMPORTED", "checksum": digest}
