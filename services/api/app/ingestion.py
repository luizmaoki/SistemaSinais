import asyncio
from datetime import timedelta
from time import monotonic
from sqlalchemy import func, select
from app.adapters.base import NormalizedQuery
from app.adapters.coinbase import CoinbaseAdapter
from app.adapters.sec import SECAdapter
from app.config import get_settings
from app.database import SessionLocal, utcnow
from app.errors import ProviderError
from app.models import Alert, AlertRule, Asset, Filing, IngestionRun, MarketBar, ProviderState, User


def evaluate_alerts(session):
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    insert = pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    created = 0
    cutoff = utcnow()
    for rule in session.scalars(
        select(AlertRule).join(User, User.id == AlertRule.user_id).where(
            AlertRule.enabled.is_(True), User.active.is_(True), User.tenant_id == AlertRule.tenant_id,
        )
    ):
        if rule.source_id == "coinbase" and not get_settings().coinbase_personal_use_accepted:
            continue
        bar = session.scalar(
            select(MarketBar)
            .where(
                MarketBar.asset_id == rule.asset_id,
                MarketBar.source_id == rule.source_id,
                MarketBar.available_as_of <= cutoff,
                MarketBar.close_time <= cutoff,
                MarketBar.ingested_at <= cutoff,
                MarketBar.adjustment == "unadjusted",
                MarketBar.timeframe == "1d",
            )
            .order_by(MarketBar.event_time.desc())
            .limit(1)
        )
        if not bar or (bar.source_id != "demo" and bar.close_time < utcnow() - timedelta(days=2)):
            continue
        asset = session.get(Asset, rule.asset_id)
        if asset is None or not bar.currency or bar.currency != asset.currency or bar.close <= 0:
            continue
        matches = bar.close > rule.threshold if rule.direction == "above" else bar.close < rule.threshold
        if matches:
            statement = insert(Alert).values(
                tenant_id=rule.tenant_id,
                user_id=rule.user_id,
                rule_id=rule.id,
                bar_id=bar.id,
                asset_id=rule.asset_id,
                message="Preço observado atende ao limiar da regra; não é recomendação.",
                observed_price=bar.close,
                threshold=rule.threshold,
                source_id=bar.source_id,
                data_mode=bar.data_mode,
                evidence_kind=bar.evidence_kind,
                event_time=bar.close_time,
                available_as_of=bar.available_as_of,
            )
            statement = statement.on_conflict_do_nothing(index_elements=["rule_id", "bar_id"])
            created += session.execute(statement).rowcount
    session.commit()
    return created


def persist_events(session, asset, events):
    count = 0
    for event in events:
        if event.event_type == "filing_published":
            p = event.payload
            existing = session.scalar(
                select(Filing.id).where(
                    Filing.source_id == event.source_id,
                    Filing.accession_number == event.native_id,
                    Filing.raw_payload_checksum == p["raw_payload_checksum"],
                )
            )
            if existing:
                continue
            version = (
                session.scalar(
                    select(func.max(Filing.version)).where(
                        Filing.source_id == event.source_id, Filing.accession_number == event.native_id
                    )
                )
                or 0
            ) + 1
            session.add(
                Filing(
                    asset_id=asset.id,
                    cik=p["cik"],
                    accession_number=event.native_id,
                    form=p["form"],
                    title=f"{asset.display_name} — {p['form']}",
                    filing_date=p["filing_date"],
                    filing_period_end=p["filing_period_end"],
                    published_at=event.published_at,
                    publication_precision=p["publication_precision"],
                    event_time=event.published_at,
                    available_as_of=event.available_as_of,
                    ingested_at=event.ingested_at,
                    source_id=event.source_id,
                    source_uri=event.source_uri,
                    evidence_kind=event.evidence_kind,
                    data_mode=event.data_mode,
                    version=version,
                    raw_payload_checksum=p["raw_payload_checksum"],
                    metadata_json=p["metadata"],
                )
            )
        elif event.event_type == "daily_bar":
            p = event.payload
            # Provider evidence declares the denomination; metadata only validates it.
            if not p.get("currency") or p["currency"] != asset.currency:
                raise ProviderError("PROVIDER_CURRENCY_MISMATCH", event.source_id, "Moeda do candle ausente ou incompatível com o instrumento; lote não persistido.")
            if event.source_id == "coinbase":
                product = CoinbaseAdapter.product_for_asset(asset)
                if product is None or p.get("provider_product") != product or p.get("provider_asset_id") != asset.id:
                    raise ProviderError("PROVIDER_IDENTITY_MISMATCH", event.source_id, "Produto sem vínculo explícito com este instrumento; lote não persistido.")
            bar_values = {key: value for key, value in p.items() if key not in {"provider_product", "provider_asset_id"}}
            existing = session.scalar(
                select(MarketBar.id).where(
                    MarketBar.asset_id == asset.id,
                    MarketBar.source_id == event.source_id,
                    MarketBar.event_time == p["event_time"],
                )
            )
            if existing:
                continue
            session.add(
                MarketBar(
                    asset_id=asset.id,
                    source_id=event.source_id,
                    **bar_values,
                    data_mode=event.data_mode,
                    evidence_kind=event.evidence_kind,
                    source_uri=event.source_uri,
                    available_as_of=event.available_as_of,
                    ingested_at=event.ingested_at,
                )
            )
        else:
            continue
        session.flush()
        count += 1
    return count


async def sync_provider(provider_id):
    settings = get_settings()
    settings.assert_auth_ready()
    adapter = (
        SECAdapter(settings.sec_user_agent, settings.provider_timeout_seconds)
        if provider_id == "sec_edgar"
        else CoinbaseAdapter(settings.coinbase_personal_use_accepted, settings.provider_timeout_seconds)
    )
    with SessionLocal() as session:
        state = session.get(ProviderState, provider_id)
        if not state:
            state = ProviderState(id=provider_id)
            session.add(state)
        run = IngestionRun(provider_id=provider_id, status="RUNNING")
        session.add(run)
        state.last_attempt_at = utcnow()
        session.commit()
        started = monotonic()
        count = 0
        try:
            assets = list(
                session.scalars(
                    select(Asset).where(Asset.cik.is_not(None))
                    if provider_id == "sec_edgar"
                    else select(Asset).where(Asset.asset_type == "crypto")
                )
            )
            if provider_id == "coinbase":
                assets = [asset for asset in assets if CoinbaseAdapter.product_for_asset(asset) is not None]
                if not assets:
                    raise ProviderError("ASSET_MAPPING_UNAVAILABLE", provider_id, "Nenhum instrumento possui vínculo válido com o piloto Coinbase.")
            for asset in assets:
                query = NormalizedQuery(asset_id=asset.id, symbol=asset.symbol, cik=asset.cik)
                events = await adapter.normalize(await adapter.fetch(query))
                count += persist_events(session, asset, events)
            # Commit only after the full batch succeeds; no partial healthy state.
            state.status = "HEALTHY"
            state.last_success_at = utcnow()
            state.last_error = None
            state.records_ingested += count
            state.latency_ms = int((monotonic() - started) * 1000)
            run.status = "SUCCEEDED"
            run.record_count = count
            run.completed_at = utcnow()
            session.commit()
            return {"provider_id": provider_id, "status": "HEALTHY", "inserted": count}
        except ProviderError as error:
            session.rollback()
            state = session.get(ProviderState, provider_id)
            run = session.get(IngestionRun, run.id)
            state.status = (
                "NOT_CONFIGURED"
                if error.code in {"PROVIDER_NOT_CONFIGURED", "LICENSE_ACCEPTANCE_REQUIRED"}
                else "UNAVAILABLE"
            )
            state.last_error = error.code + ": " + error.safe_message
            run.status = "FAILED"
            run.error_code = error.code
            run.completed_at = utcnow()
            session.commit()
            return {"provider_id": provider_id, "status": state.status, "error_code": error.code}


def sync(provider, use_lock=True):
    from redis import Redis
    from redis.exceptions import RedisError

    if provider not in {"sec_edgar", "coinbase", "all"}:
        raise ValueError("Unknown provider")
    providers = ["sec_edgar", "coinbase"] if provider == "all" else [provider]
    results = []
    for item in providers:
        if not use_lock:
            results.append(asyncio.run(sync_provider(item)))
            continue
        lock = Redis.from_url(get_settings().redis_url, socket_connect_timeout=2, socket_timeout=2).lock(
            "capital:ingestion:" + item, timeout=600, blocking_timeout=0
        )
        try:
            if not lock.acquire(blocking=False):
                results.append({"provider_id": item, "status": "ALREADY_RUNNING"})
                continue
            try:
                results.append(asyncio.run(sync_provider(item)))
            finally:
                if lock.owned():
                    lock.release()
        except RedisError:
            results.append({"provider_id": item, "status": "UNAVAILABLE", "error_code": "QUEUE_UNAVAILABLE"})
    return results
