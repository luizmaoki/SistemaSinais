import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4
from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict, Field
from redis import Redis
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from app.auth import Principal, get_principal
from app.calculations import monthly_returns, technical_metrics
from app.config import get_settings
from app.database import get_db, utcnow
from app.errors import api_error
from app.ingestion import evaluate_alerts
from app.models import Alert, AlertRule, Asset, AuditLog, Filing, MacroEvent, MarketBar, Watchlist, WatchlistAsset
from app.providers import provider_rows
from app.logging_config import application_logger

settings = get_settings()
logger = application_logger("capital.api")


@asynccontextmanager
async def lifespan(app):
    settings.assert_auth_ready()
    yield


app = FastAPI(title="Capital Intelligence", version="0.1.0", lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts.split(","))
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
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
        if origin and origin not in settings.cors_origins.split(","):
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
    return {
        column.name: float(value) if isinstance(value := getattr(obj, column.name), Decimal) else value
        for column in obj.__table__.columns
    }


def get_asset(session, asset_id):
    asset = session.get(Asset, str(asset_id))
    if not asset:
        raise api_error(404, "ASSET_NOT_FOUND", "Ativo não encontrado.")
    return asset


def series(session, asset_id, source_id="demo", start=None, end=None):
    asset = get_asset(session, asset_id)
    if source_id == "coinbase" and not settings.coinbase_personal_use_accepted:
        raise api_error(503, "PROVIDER_NOT_CONFIGURED", "Coinbase não configurada; aceite pessoal necessário.")
    query = select(MarketBar).where(
        MarketBar.asset_id == asset.id,
        MarketBar.source_id == source_id,
        MarketBar.close_time <= utcnow(),
        MarketBar.available_as_of <= utcnow(),
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
    if bars[-1].source_id == "demo":
        return "DEMO"
    return "STALE" if bars[-1].close_time < utcnow() - timedelta(days=2) else "END_OF_DAY"


def asset_row(asset, session):
    result = record(asset)
    _, bars = series(session, asset.id)
    result.update(
        latest_price=float(bars[-1].close) if bars else None,
        change_pct=(float(bars[-1].close / bars[-2].close - 1) * 100) if len(bars) >= 2 else None,
        data_mode=mode_for(bars),
        source_id="demo" if bars else None,
        updated_at=bars[-1].close_time if bars else None,
    )
    return result


@app.get(PREFIX + "/health")
def health():
    return {"status": "ok", "service": "capital_intelligence", "mode": "DEMO"}


@app.get(PREFIX + "/ready")
def ready(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2).ping()
    except Exception:
        raise api_error(503, "DEPENDENCY_UNAVAILABLE", "Banco ou fila indisponível.") from None
    return {"status": "ready", "database": "ok", "redis": "ok"}


@app.get(PREFIX + "/auth/session", dependencies=authenticated)
def auth_session(principal: Principal = Depends(get_principal)):
    return {
        "mode": "DEMO",
        "user": {"id": principal.user_id, "name": "Usuário demo"},
        "tenant_id": principal.tenant_id,
        "role": principal.role,
    }


@app.get(PREFIX + "/assets", dependencies=authenticated)
def assets(
    q: str = Query("", max_length=100),
    asset_class: str | None = Query(None, alias="class", max_length=40),
    venue: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = select(Asset)
    if q:
        # LIKE metacharacters escaped; query stays parametrized.
        needle = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(
            Asset.symbol.ilike(f"%{needle}%", escape="\\") | Asset.display_name.ilike(f"%{needle}%", escape="\\")
        )
    if asset_class:
        query = query.where(Asset.asset_type == asset_class)
    if venue:
        query = query.where(Asset.venue == venue)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(Asset.symbol).offset((page - 1) * page_size).limit(page_size))
    return {"items": [asset_row(asset, db) for asset in rows], "total": total, "page": page, "page_size": page_size}


@app.get(PREFIX + "/assets/{asset_id}", dependencies=authenticated)
def asset_detail(asset_id: UUID, db: Session = Depends(get_db)):
    return asset_row(get_asset(db, asset_id), db)


@app.get(PREFIX + "/assets/{asset_id}/bars", dependencies=authenticated)
def bars_endpoint(
    asset_id: UUID,
    source: Literal["demo", "coinbase"] = "demo",
    timeframe: Literal["1d"] = "1d",
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    db: Session = Depends(get_db),
):
    for stamp in [start, end]:
        if stamp and stamp.tzinfo is None:
            raise api_error(422, "TIMEZONE_REQUIRED", "Inclua timezone nos filtros de data.")
    if start and end and start > end:
        raise api_error(422, "INVALID_RANGE", "Data inicial posterior à final.")
    asset, bars = series(db, asset_id, source, start, end)
    mode = mode_for(bars)
    return {
        "items": [{**record(bar), "time": bar.event_time, "data_mode": mode} for bar in bars],
        "data_mode": mode,
        "source_id": source,
        "as_of": utcnow(),
        "currency": asset.currency,
        "adjustment": "unadjusted",
        "timeframe": timeframe,
    }


@app.get(PREFIX + "/assets/{asset_id}/returns", dependencies=authenticated)
def returns_endpoint(
    asset_id: UUID,
    source: Literal["demo", "coinbase"] = "demo",
    granularity: Literal["month"] = "month",
    db: Session = Depends(get_db),
):
    asset, bars = series(db, asset_id, source)
    return {
        "items": monthly_returns(bars, asset.asset_type, asset.timezone, utcnow()),
        "data_mode": mode_for(bars),
        "source_id": source,
        "as_of": utcnow(),
        "methodology": "Último fechamento do mês / fechamento do mês anterior - 1; lacunas e meses parciais explícitos.",
    }


@app.get(PREFIX + "/assets/{asset_id}/metrics", dependencies=authenticated)
def metrics(asset_id: UUID, source: Literal["demo", "coinbase"] = "demo", db: Session = Depends(get_db)):
    asset, bars = series(db, asset_id, source)
    return {
        **technical_metrics(bars, asset.asset_type),
        "data_mode": mode_for(bars),
        "source_id": source,
        "as_of": bars[-1].close_time if bars else None,
    }


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
                "demo_bars": asset.asset_type in {"equity", "etf", "crypto"},
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
    result = assets(q, asset_class, None, page, page_size, db)
    for row in result["items"]:
        asset, bars = series(db, row["id"])
        row["metrics"] = technical_metrics(bars, asset.asset_type)
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
    body: WatchlistInput, db: Session = Depends(get_db), principal: Principal = Depends(get_principal)
):
    row = Watchlist(tenant_id=principal.tenant_id, user_id=principal.user_id, name=body.name.strip())
    db.add(row)
    db.flush()
    audit(db, principal, "watchlist_created", row.id)
    db.commit()
    return {**record(row), "asset_ids": [], "assets": []}


@app.post(PREFIX + "/watchlists/{watchlist_id}/assets")
def add_asset(
    watchlist_id: UUID, body: AddAsset, db: Session = Depends(get_db), principal: Principal = Depends(get_principal)
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
    watchlist_id: UUID, asset_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_principal)
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
def create_rule(body: RuleInput, db: Session = Depends(get_db), principal: Principal = Depends(get_principal)):
    asset, bars = series(db, body.asset_id, body.source_id)
    if not bars:
        raise api_error(503, "DATASET_UNAVAILABLE", "Série indisponível para esta regra.")
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
    rule_id: UUID, body: RulePatch, db: Session = Depends(get_db), principal: Principal = Depends(get_principal)
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
            record(row)
            for row in db.scalars(
                select(Alert)
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

