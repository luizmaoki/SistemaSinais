import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from dataclasses import asdict, is_dataclass
from zoneinfo import ZoneInfo
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict, Field
from redis import Redis
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from app.auth import Principal, get_principal, require_writer
from app.auth_routes import router as auth_router
from app.calculations import monthly_returns, technical_metrics
from app.calendars import CalendarUnavailable, SUPPORTED_CALENDARS, session_schedule
from app.catalog import normalized_identifier, resolve_identifiers, visible_identifiers
from app.corporate_actions import latest_actions, latest_coverage
from app.adjustments import AdjustmentUnavailable, METHODOLOGY, adjust_series, has_coverage
from app.config import get_settings
from app.database import get_db, utcnow
from app.errors import api_error
from app.ingestion import evaluate_alerts
from app.models import Alert, AlertRule, Asset, AssetIdentifier, AuditLog, Filing, MacroEvent, MarketBar, Watchlist, WatchlistAsset
from app.providers import provider_rows
from app.logging_config import application_logger

settings = get_settings()
logger = application_logger("capital.api")


@asynccontextmanager
async def lifespan(app):
    settings.assert_auth_ready()
    yield


app = FastAPI(title="Capital Intelligence", version="0.1.0", lifespan=lifespan)
app.include_router(auth_router)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.host_allowlist)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)
_request_counts = {}


@app.middleware("http")
async def guards(request: Request, call_next):
    start = time.monotonic()
    correlation = str(uuid4())
    client = request.client.host if request.client else "unknown"
    minute = int(time.time() // 60)
    if len(_request_counts) > 1000:
        _request_counts.clear()
    bucket = _request_counts.get(client, (minute, 0))
    count = bucket[1] + 1 if bucket[0] == minute else 1
    _request_counts[client] = (minute, count)
    if count > settings.request_limit_per_minute:
        return JSONResponse(
            {"detail": {"code": "RATE_LIMITED", "message": "Limite local de requisições atingido."}},
            status_code=429,
            headers={"Retry-After": "60"},
        )
    if request.method in {"POST", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin is not None and origin not in settings.allowed_origins:
            return JSONResponse(
                {"detail": {"code": "INVALID_ORIGIN", "message": "Origem não autorizada."}}, status_code=403
            )
        body = await request.body()
        if len(body) > settings.max_request_bytes:
            return JSONResponse(
                {"detail": {"code": "PAYLOAD_TOO_LARGE", "message": "Payload excedeu o limite."}}, status_code=413
            )
    try:
        response = await call_next(request)
    except Exception:
        logger.error({"event": "request_failed", "correlation_id": correlation})
        return JSONResponse(
            {"detail": {"code": "INTERNAL_ERROR", "message": "Falha interna; consulte o identificador da requisição."}},
            status_code=500,
            headers={"X-Correlation-ID": correlation},
        )
    response.headers.update(
        {
            "X-Correlation-ID": correlation,
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
        }
    )
    logger.info({
        "event": "request", "correlation_id": correlation, "method": request.method,
        "status": response.status_code, "latency_ms": int((time.monotonic() - start) * 1000),
    })
    return response


PREFIX = "/api/v1"
authenticated = [Depends(get_principal)]


def record(obj):
    values = asdict(obj) if is_dataclass(obj) else {column.name: getattr(obj, column.name) for column in obj.__table__.columns}
    return {key: float(value) if isinstance(value, Decimal) else value for key, value in values.items()}


def knowledge_time(value=None):
    now = utcnow()
    if value is not None and value.tzinfo is None:
        raise api_error(422, "TIMEZONE_REQUIRED", "Inclua timezone no instante de conhecimento.")
    if value is not None and value > now:
        raise api_error(422, "FUTURE_AS_OF", "O instante de conhecimento não pode estar no futuro.")
    return value or now


def get_asset(session, asset_id):
    asset = session.get(Asset, str(asset_id))
    if not asset:
        raise api_error(404, "ASSET_NOT_FOUND", "Ativo não encontrado.")
    return asset


def series(session, asset_id, source_id="demo", start=None, end=None, as_of=None):
    asset = get_asset(session, asset_id)
    if source_id == "coinbase" and not settings.coinbase_personal_use_accepted:
        raise api_error(503, "PROVIDER_NOT_CONFIGURED", "Coinbase não configurada; aceite pessoal necessário.")
    cutoff = as_of or utcnow()
    query = select(MarketBar).where(
        MarketBar.asset_id == asset.id,
        MarketBar.source_id == source_id,
        MarketBar.close_time <= cutoff,
        MarketBar.available_as_of <= cutoff,
        MarketBar.ingested_at <= cutoff,
        MarketBar.adjustment == "unadjusted",
        MarketBar.timeframe == "1d",
    )
    if start:
        query = query.where(MarketBar.close_time >= start)
    if end:
        query = query.where(MarketBar.close_time <= end)
    bars = list(session.scalars(query.order_by(MarketBar.event_time).limit(2000)))
    return asset, bars


def mode_for(bars):
    if not bars:
        return "UNAVAILABLE"
    if bars[-1].data_mode == "DEMO":
        return "DEMO"
    return "STALE" if bars[-1].close_time < utcnow() - timedelta(days=2) else "END_OF_DAY"


def series_currency(asset, bars):
    """Use observed denominations; catalog metadata cannot fill an unknown bar currency."""
    currencies = {bar.currency for bar in bars}
    if not currencies:
        return asset.currency, None
    if len(currencies) > 1:
        return None, "SERIES_CURRENCY_MISMATCH"
    currency = next(iter(currencies))
    if not currency:
        return None, "CURRENCY_UNAVAILABLE"
    if currency != asset.currency:
        return None, "SERIES_CURRENCY_MISMATCH"
    return currency, None


def asset_row(asset, session):
    result = record(asset)
    _, bars = series(session, asset.id)
    quote_currency, reason = series_currency(asset, bars)
    reason = reason or ("NO_CLOSED_RAW_BARS" if not bars else None)
    if bars and bars[-1].close <= 0:
        reason = reason or "INVALID_PRICE"
    available = reason is None
    result.update(
        latest_price=float(bars[-1].close) if available else None,
        change_pct=(float((bars[-1].close / bars[-2].close - 1) * 100)) if available and len(bars) >= 2 and bars[-2].close > 0 else None,
        data_mode=mode_for(bars) if available else "UNAVAILABLE",
        source_id="demo" if bars else None,
        updated_at=bars[-1].close_time if bars else None,
        quote_currency=quote_currency if available else None,
        quote_status="AVAILABLE" if available else "UNAVAILABLE",
        quote_reason=reason,
    )
    return result


@app.get(PREFIX + "/health")
def health():
    return {
        "status": "ok", "service": "capital_intelligence",
        "mode": "DEMO" if settings.demo_available else "OIDC",
    }


@app.get(PREFIX + "/ready")
def ready(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2).ping()
    except Exception:
        raise api_error(503, "DEPENDENCY_UNAVAILABLE", "Banco ou fila indisponível.") from None
    return {"status": "ready", "database": "ok", "redis": "ok"}


@app.get(PREFIX + "/assets", dependencies=authenticated)
def assets(
    q: str = Query("", max_length=100),
    asset_class: str | None = Query(None, alias="class", max_length=40),
    venue: str | None = Query(None, max_length=100),
    currency: str | None = Query(None, max_length=8),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = select(Asset)
    if q:
        # LIKE metacharacters escaped; query stays parametrized.
        needle = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(
            Asset.symbol.ilike(f"%{needle}%", escape="\\") | Asset.display_name.ilike(f"%{needle}%", escape="\\") | Asset.id.in_(select(AssetIdentifier.asset_id).where(AssetIdentifier.value.ilike(f"%{needle}%", escape="\\")))
        )
    if asset_class:
        query = query.where(Asset.asset_type == asset_class)
    if venue:
        query = query.where(Asset.venue == venue)
    if currency:
        query = query.where(Asset.currency == currency)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(Asset.symbol, Asset.venue, Asset.id).offset((page - 1) * page_size).limit(page_size))
    return {"items": [asset_row(asset, db) for asset in rows], "total": total, "page": page, "page_size": page_size}


@app.get(PREFIX + "/assets/resolve", dependencies=authenticated)
def resolve_asset(
    identifier_type: Literal["ticker", "cik", "isin", "figi", "cusip", "vendor", "contract_address"],
    value: str = Query(min_length=1, max_length=100),
    venue: str | None = Query(None, max_length=100),
    chain_id: str | None = Query(None, max_length=30),
    as_of: date | None = None,
    known_at: datetime | None = None,
    db: Session = Depends(get_db),
):
    known = knowledge_time(known_at)
    effective = as_of or known.date()
    try:
        normalized = normalized_identifier(identifier_type, value)
    except ValueError as error:
        raise api_error(422, "INVALID_IDENTIFIER", str(error)) from None
    candidates = resolve_identifiers(db, identifier_type, normalized, effective, known, venue, chain_id)
    if len(candidates) > 1:
        raise HTTPException(409, detail={"code": "AMBIGUOUS_IDENTIFIER", "message": "Identificador corresponde a mais de um instrumento; informe escopo e vigência.", "candidate_ids": candidates})
    if not candidates:
        raise api_error(404, "IDENTIFIER_NOT_FOUND", "Nenhum identificador conhecido e vigente corresponde à consulta.")
    return {"asset_id": candidates[0], "asset": asset_row(get_asset(db, candidates[0]), db), "identifier_type": identifier_type, "value": normalized, "as_of": effective, "known_at": known}


@app.get(PREFIX + "/assets/{asset_id}", dependencies=authenticated)
def asset_detail(asset_id: UUID, db: Session = Depends(get_db)):
    return asset_row(get_asset(db, asset_id), db)


@app.get(PREFIX + "/assets/{asset_id}/identifiers", dependencies=authenticated)
def identifiers(asset_id: UUID, known_at: datetime | None = None, db: Session = Depends(get_db)):
    get_asset(db, asset_id)
    known = knowledge_time(known_at)
    return {"items": [record(row) for row in visible_identifiers(db, known, asset_id)], "known_at": known}


@app.get(PREFIX + "/assets/{asset_id}/calendar", dependencies=authenticated)
def asset_calendar(
    asset_id: UUID, start: date = Query(alias="from"), end: date = Query(alias="to"),
    db: Session = Depends(get_db),
):
    asset = get_asset(db, asset_id)
    if not 0 <= (end - start).days <= 365:
        raise api_error(422, "INVALID_RANGE", "O intervalo deve conter de 1 a 366 dias, incluindo os limites.")
    response = {"calendar_id": asset.calendar_id, "timezone": asset.timezone, "currency": asset.currency, "as_of": utcnow()}
    try:
        if asset.calendar_id and SUPPORTED_CALENDARS.get(asset.calendar_id) != asset.timezone:
            raise CalendarUnavailable("CALENDAR_TIMEZONE_MISMATCH")
        schedule = session_schedule(start, end, asset.calendar_id)
    except CalendarUnavailable as error:
        return {**response, "status": "UNAVAILABLE", "reason": str(error), "items": []}
    return {**response, "status": "AVAILABLE", "reason": None, "items": [{"session_date": day, "open_at": times[0], "close_at": times[1]} for day, times in schedule.items()]}


@app.get(PREFIX + "/assets/{asset_id}/corporate-actions", dependencies=authenticated)
def corporate_actions(
    asset_id: UUID, source: str = Query("demo", pattern=r"^[a-z][a-z0-9_-]{0,49}$"),
    as_of: datetime | None = None, db: Session = Depends(get_db),
):
    asset = get_asset(db, asset_id)
    cutoff = knowledge_time(as_of)
    mode = "DEMO" if source.startswith("demo") else "END_OF_DAY"
    actions = latest_actions(db, asset.id, source, mode, cutoff, include_cancelled=True)
    intervals = latest_coverage(db, asset.id, source, mode, cutoff)
    complete = [r for r in intervals if r.complete]
    coverage = None
    if complete and has_coverage(complete, min(r.coverage_from for r in complete), max(r.coverage_to for r in complete)):
        coverage = {"from": min(r.coverage_from for r in complete), "to": max(r.coverage_to for r in complete), "source_id": source, "data_mode": mode, "complete": True}
    return {"items": [{**record(row), "effective_date": row.effective_at.astimezone(ZoneInfo(asset.timezone)).date(), "evidence_kind": "SIMULATED" if mode == "DEMO" else "REPORTED"} for row in actions], "coverage": coverage, "coverage_intervals": [record(row) for row in intervals], "source_id": source, "data_mode": mode, "as_of": cutoff}


Adjustment = Literal["unadjusted", "split_adjusted", "split_dividend_adjusted"]


def requested_series(db, asset_id, source, adjustment, as_of, action_source, start=None, end=None):
    cutoff = knowledge_time(as_of)
    for stamp in (start, end):
        if stamp and stamp.tzinfo is None:
            raise api_error(422, "TIMEZONE_REQUIRED", "Inclua timezone nos filtros de data.")
    if start and end and start > end:
        raise api_error(422, "INVALID_RANGE", "Data inicial posterior à final.")
    asset, raw = series(db, asset_id, source, start, end, cutoff)
    currency, currency_reason = series_currency(asset, raw)
    if currency_reason == "SERIES_CURRENCY_MISMATCH":
        raise api_error(409, "SERIES_CURRENCY_MISMATCH", "Série contém moedas inconsistentes; conversão cambial indisponível.")
    try:
        bars = adjust_series(db, asset, raw, adjustment, action_source or source, cutoff)
    except AdjustmentUnavailable as error:
        raise HTTPException(409, detail={"code": "ADJUSTMENT_UNAVAILABLE", "message": "Ajuste indisponível para esta série e instante de conhecimento.", "reason": str(error)}) from None
    return asset, bars, {
        "data_mode": mode_for(bars), "source_id": source, "as_of": cutoff,
        "last_observation_at": bars[-1].close_time if bars else None,
        "currency": currency,
        "calendar_id": asset.calendar_id, "adjustment": adjustment,
        "adjustment_status": "AVAILABLE", "adjustment_methodology": METHODOLOGY[adjustment],
        "action_source_id": (action_source or source) if adjustment != "unadjusted" else None,
    }


@app.get(PREFIX + "/assets/{asset_id}/bars", dependencies=authenticated)
def bars_endpoint(
    asset_id: UUID,
    source: str = Query("demo", pattern=r"^[a-z][a-z0-9_-]{0,49}$"),
    timeframe: Literal["1d"] = "1d", adjustment: Adjustment = "unadjusted",
    as_of: datetime | None = None,
    corporate_action_source: str | None = Query(None, pattern=r"^[a-z][a-z0-9_-]{0,49}$"),
    start: datetime | None = Query(None, alias="from"), end: datetime | None = Query(None, alias="to"),
    db: Session = Depends(get_db),
):
    _, bars, metadata = requested_series(db, asset_id, source, adjustment, as_of, corporate_action_source, start, end)
    return {"items": [{**record(bar), "time": bar.event_time, "data_mode": metadata["data_mode"]} for bar in bars], **metadata, "timeframe": timeframe}


def calculation_availability(asset, bars, currency):
    _, currency_reason = series_currency(asset, bars)
    if currency_reason:
        return currency_reason
    if asset.calendar_id not in SUPPORTED_CALENDARS or asset.timezone != SUPPORTED_CALENDARS.get(asset.calendar_id):
        return "CALENDAR_UNAVAILABLE"
    if not bars:
        return "NO_CLOSED_RAW_BARS"
    if currency is None:
        return "CURRENCY_UNAVAILABLE"
    tz = ZoneInfo(asset.timezone)
    days = [bar.event_time.astimezone(tz).date() for bar in bars]
    try:
        # Monthly calculations need the preceding month as a return base too.
        first = (min(days).replace(day=1) - timedelta(days=1)).replace(day=1)
        last = (max(days).replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        schedule = session_schedule(first, last, asset.calendar_id)
    except CalendarUnavailable as error:
        return str(error)
    if len(days) != len(set(days)):
        return "DUPLICATE_SESSIONS"
    if any(day not in schedule or bar.close_time != schedule[day][1] or not schedule[day][0] <= bar.event_time < bar.close_time for day, bar in zip(days, bars)):
        return "BAR_SESSION_MISMATCH"
    if any(bar.close <= 0 or bar.volume < 0 for bar in bars):
        return "INVALID_PRICE"
    return None


@app.get(PREFIX + "/assets/{asset_id}/returns", dependencies=authenticated)
def returns_endpoint(
    asset_id: UUID, source: str = Query("demo", pattern=r"^[a-z][a-z0-9_-]{0,49}$"),
    granularity: Literal["month"] = "month", adjustment: Adjustment = "unadjusted",
    as_of: datetime | None = None,
    corporate_action_source: str | None = Query(None, pattern=r"^[a-z][a-z0-9_-]{0,49}$"),
    db: Session = Depends(get_db),
):
    asset, bars, metadata = requested_series(db, asset_id, source, adjustment, as_of, corporate_action_source)
    unavailable_reason = calculation_availability(asset, bars, metadata["currency"])
    available = unavailable_reason is None
    return {
        "items": monthly_returns(bars, asset.asset_type, asset.timezone, metadata["as_of"], asset.calendar_id) if available else [],
        **metadata, "calculation_status": "AVAILABLE" if available else "UNAVAILABLE",
        "reason": unavailable_reason,
        "methodology": "Último fechamento do mês / fechamento do mês anterior - 1; lacunas e meses parciais explícitos. Variação de preço na modalidade selecionada, sem retorno total/reinvestimento.",
    }


def metrics_projection(asset, bars):
    currency, _ = series_currency(asset, bars)
    unavailable_reason = calculation_availability(asset, bars, currency)
    if unavailable_reason is not None:
        return {"calculation_status": "UNAVAILABLE", "frequency_quality": unavailable_reason, "volatility_reason": unavailable_reason}
    return technical_metrics(bars, asset.asset_type, asset.calendar_id, asset.timezone)


@app.get(PREFIX + "/assets/{asset_id}/metrics", dependencies=authenticated)
def metrics(
    asset_id: UUID, source: str = Query("demo", pattern=r"^[a-z][a-z0-9_-]{0,49}$"),
    adjustment: Adjustment = "unadjusted", as_of: datetime | None = None,
    corporate_action_source: str | None = Query(None, pattern=r"^[a-z][a-z0-9_-]{0,49}$"),
    db: Session = Depends(get_db),
):
    asset, bars, metadata = requested_series(db, asset_id, source, adjustment, as_of, corporate_action_source)
    return {**metrics_projection(asset, bars), **metadata}


@app.get(PREFIX + "/providers", dependencies=authenticated)
def providers(db: Session = Depends(get_db)):
    return {"items": provider_rows(db, settings)}


@app.get(PREFIX + "/coverage", dependencies=authenticated)
def coverage(db: Session = Depends(get_db)):
    return {
        "items": [
            {
                "asset_id": asset.id,
                "symbol": asset.symbol,
                "catalog": True,
                "real_quote": False,
                "demo_bars": bool(db.scalar(select(MarketBar.id).where(MarketBar.asset_id == asset.id, MarketBar.source_id == "demo").limit(1))),
                "sec_filings": bool(asset.cik),
            }
            for asset in db.scalars(select(Asset))
        ]
    }


@app.get(PREFIX + "/scanner", dependencies=authenticated)
def scanner(
    q: str = Query("", max_length=100),
    asset_class: str | None = Query(None, alias="class", max_length=40),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    result = assets(q=q, asset_class=asset_class, venue=None, currency=None, page=page, page_size=page_size, db=db)
    for row in result["items"]:
        asset, bars = series(db, row["id"])
        row["metrics"] = metrics_projection(asset, bars)
    return result


@app.get(PREFIX + "/macro/calendar", dependencies=authenticated)
def calendar(country: str | None = Query(None, max_length=5), db: Session = Depends(get_db)):
    query = select(MacroEvent)
    if country:
        query = query.where(MacroEvent.country == country)
    return {
        "items": [record(row) for row in db.scalars(query.order_by(MacroEvent.scheduled_at).limit(200))],
        "data_mode": "DEMO",
    }


def filings_query(db, asset_id=None, cik=None, form=None):
    query = select(Filing)
    if asset_id:
        query = query.where(Filing.asset_id == str(asset_id))
    if cik:
        query = query.where(Filing.cik == cik.zfill(10))
    if form:
        query = query.where(Filing.form == form)
    result = []
    for filing in db.scalars(query.order_by(Filing.published_at.desc(), Filing.version.desc()).limit(200)):
        row = record(filing)
        row.pop("metadata_json")
        row["symbol"] = db.get(Asset, filing.asset_id).symbol
        row["data_mode"] = "END_OF_DAY"  # Historical reported event, not a live quote.
        result.append(row)
    return result


@app.get(PREFIX + "/institutional/filings", dependencies=authenticated)
def filings(
    asset_id: UUID | None = None,
    cik: str | None = Query(None, pattern=r"^\d{1,10}$"),
    form: str | None = Query(None, max_length=30),
    db: Session = Depends(get_db),
):
    return {
        "items": filings_query(db, asset_id, cik, form),
        "source_id": "sec_edgar",
        "coverage": "Metadados reportados, sem posições ou causalidade",
        "ai_status": "NOT_CONFIGURED",
    }


@app.get(PREFIX + "/news", dependencies=authenticated)
def news(asset_id: UUID | None = None, db: Session = Depends(get_db)):
    return {
        "items": filings_query(db, asset_id),
        "coverage": "Comunicados/filings públicos SEC; feed de notícias premium não configurado",
        "ai_status": "NOT_CONFIGURED",
    }


@app.get(PREFIX + "/assets/{asset_id}/events", dependencies=authenticated)
def events(asset_id: UUID, db: Session = Depends(get_db)):
    get_asset(db, asset_id)
    return {"items": filings_query(db, asset_id)}


class WatchlistInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80, pattern=r".*\S.*")


class AddAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: UUID


class RuleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: UUID
    threshold: Decimal = Field(gt=0, le=Decimal("1000000000000"), max_digits=20, decimal_places=8)
    direction: Literal["above", "below"]
    source_id: Literal["demo", "coinbase"] = "demo"


class RulePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


def owned_watchlist(db, watchlist_id, principal):
    row = db.scalar(
        select(Watchlist).where(
            Watchlist.id == str(watchlist_id),
            Watchlist.tenant_id == principal.tenant_id,
            Watchlist.user_id == principal.user_id,
        )
    )
    if not row:
        raise api_error(404, "WATCHLIST_NOT_FOUND", "Watchlist não encontrada neste workspace.")
    return row


def audit(db, principal, action, resource_id):
    db.add(
        AuditLog(tenant_id=principal.tenant_id, user_id=principal.user_id, action=action, resource_id=str(resource_id))
    )


@app.get(PREFIX + "/watchlists")
def watchlists(db: Session = Depends(get_db), principal: Principal = Depends(get_principal)):
    result = []
    for row in db.scalars(
        select(Watchlist)
        .where(Watchlist.tenant_id == principal.tenant_id, Watchlist.user_id == principal.user_id)
        .order_by(Watchlist.created_at)
    ):
        ids = list(db.scalars(select(WatchlistAsset.asset_id).where(WatchlistAsset.watchlist_id == row.id)))
        result.append(
            {**record(row), "asset_ids": ids, "assets": [asset_row(db.get(Asset, value), db) for value in ids]}
        )
    return {"items": result}


@app.post(PREFIX + "/watchlists", status_code=201)
def create_watchlist(
    body: WatchlistInput, db: Session = Depends(get_db), principal: Principal = Depends(require_writer)
):
    row = Watchlist(tenant_id=principal.tenant_id, user_id=principal.user_id, name=body.name.strip())
    db.add(row)
    db.flush()
    audit(db, principal, "watchlist_created", row.id)
    db.commit()
    return {**record(row), "asset_ids": [], "assets": []}


@app.post(PREFIX + "/watchlists/{watchlist_id}/assets")
def add_asset(
    watchlist_id: UUID, body: AddAsset, db: Session = Depends(get_db), principal: Principal = Depends(require_writer)
):
    owned_watchlist(db, watchlist_id, principal)
    get_asset(db, body.asset_id)
    key = {"watchlist_id": str(watchlist_id), "asset_id": str(body.asset_id)}
    if not db.get(WatchlistAsset, key):
        db.add(WatchlistAsset(**key))
        audit(db, principal, "watchlist_asset_added", watchlist_id)
        db.commit()
    return {"status": "ok", **key}


@app.delete(PREFIX + "/watchlists/{watchlist_id}/assets/{asset_id}")
def remove_asset(
    watchlist_id: UUID, asset_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(require_writer)
):
    owned_watchlist(db, watchlist_id, principal)
    row = db.get(WatchlistAsset, {"watchlist_id": str(watchlist_id), "asset_id": str(asset_id)})
    if row:
        db.delete(row)
        audit(db, principal, "watchlist_asset_removed", watchlist_id)
        db.commit()
    return {"status": "ok"}


@app.get(PREFIX + "/alert-rules")
def rules(db: Session = Depends(get_db), principal: Principal = Depends(get_principal)):
    return {
        "items": [
            record(row)
            for row in db.scalars(
                select(AlertRule).where(
                    AlertRule.tenant_id == principal.tenant_id, AlertRule.user_id == principal.user_id
                )
            )
        ]
    }


@app.post(PREFIX + "/alert-rules", status_code=201)
def create_rule(body: RuleInput, db: Session = Depends(get_db), principal: Principal = Depends(require_writer)):
    asset, bars = series(db, body.asset_id, body.source_id)
    if not bars:
        raise api_error(503, "DATASET_UNAVAILABLE", "Série indisponível para esta regra.")
    _, currency_reason = series_currency(asset, bars)
    if currency_reason:
        raise api_error(409, currency_reason, "Moeda da série ausente ou incompatível; regra não criada.")
    row = AlertRule(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        asset_id=asset.id,
        threshold=body.threshold,
        direction=body.direction,
        source_id=body.source_id,
    )
    db.add(row)
    db.flush()
    audit(db, principal, "alert_rule_created", row.id)
    db.commit()
    evaluate_alerts(db)
    return {**record(row), "data_mode": mode_for(bars)}


@app.patch(PREFIX + "/alert-rules/{rule_id}")
def patch_rule(
    rule_id: UUID, body: RulePatch, db: Session = Depends(get_db), principal: Principal = Depends(require_writer)
):
    row = db.scalar(
        select(AlertRule).where(
            AlertRule.id == str(rule_id),
            AlertRule.tenant_id == principal.tenant_id,
            AlertRule.user_id == principal.user_id,
        )
    )
    if not row:
        raise api_error(404, "RULE_NOT_FOUND", "Regra não encontrada.")
    row.enabled = body.enabled
    audit(db, principal, "alert_rule_updated", row.id)
    db.commit()
    return record(row)


@app.get(PREFIX + "/alerts")
def alerts(db: Session = Depends(get_db), principal: Principal = Depends(get_principal)):
    return {
        "items": [
            {**record(row), "observed_currency": observed_currency}
            for row, observed_currency in db.execute(
                select(Alert, MarketBar.currency)
                .outerjoin(MarketBar, (MarketBar.id == Alert.bar_id) & (MarketBar.asset_id == Alert.asset_id) & (MarketBar.source_id == Alert.source_id))
                .where(Alert.source_id != "coinbase" if not settings.coinbase_personal_use_accepted else True)
                .where(Alert.tenant_id == principal.tenant_id, Alert.user_id == principal.user_id)
                .order_by(Alert.created_at.desc())
                .limit(200)
            )
        ]
    }


@app.get(PREFIX + "/derivatives/{asset_id}/metrics", dependencies=authenticated)
@app.get(PREFIX + "/liquidity/{asset_id}/zones", dependencies=authenticated)
def unavailable(asset_id: UUID):
    raise api_error(503, "DATASET_UNAVAILABLE", "Dataset não contratado ou não implementado.")


@app.get(PREFIX + "/crypto/wallets", dependencies=authenticated)
@app.get(PREFIX + "/signals", dependencies=authenticated)
def unavailable_list():
    raise api_error(503, "DATASET_UNAVAILABLE", "Módulo não implementado nesta fase.")

