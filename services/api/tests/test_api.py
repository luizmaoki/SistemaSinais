from uuid import uuid4
import pytest
from sqlalchemy import func, select
from app.config import Settings
from app.ingestion import evaluate_alerts
from app.models import Alert, Tenant, User, Watchlist
from app.seed import seed


def nvda(client):
    response = client.get("/api/v1/assets?q=NVDA")
    assert response.status_code == 200
    return response.json()["items"][0]["id"]


def test_catalog_filters_and_demo_series(client):
    asset_id = nvda(client)
    assert client.get("/api/v1/assets?q=BTC").json()["items"][0]["symbol"] == "BTC-USD"
    bars = client.get(f"/api/v1/assets/{asset_id}/bars").json()
    assert bars["data_mode"] == "DEMO"
    assert bars["items"][0]["evidence_kind"] == "SIMULATED"
    assert bars["items"][0]["source_uri"].startswith("fixture:")
    assert client.get(f"/api/v1/assets/{asset_id}/returns").json()["items"][0]["return_pct"] is None
    assert client.get("/api/v1/assets?class=crypto").json()["total"] == 3


@pytest.mark.parametrize("path", ["/api/v1/assets?page=0", "/api/v1/assets?page_size=101", "/api/v1/assets/not-a-uuid"])
def test_validation(client, path):
    assert client.get(path).status_code == 422


def test_no_dataset_numbers_when_not_configured(client):
    asset_id = nvda(client)
    assert client.get(f"/api/v1/assets/{asset_id}/bars?source=coinbase").status_code == 503
    response = client.get(f"/api/v1/derivatives/{asset_id}/metrics")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "DATASET_UNAVAILABLE"
    providers = client.get("/api/v1/providers").json()["items"]
    assert next(p for p in providers if p["id"] == "coinbase")["ai_processing_allowed"] is False


def test_watchlist_persist_add_idempotent(client):
    asset_id = nvda(client)
    created = client.post("/api/v1/watchlists", json={"name": "Test persisted"})
    assert created.status_code == 201
    watchlist_id = created.json()["id"]
    for _ in range(2):
        assert client.post(f"/api/v1/watchlists/{watchlist_id}/assets", json={"asset_id": asset_id}).status_code == 200
    lists = client.get("/api/v1/watchlists").json()["items"]
    assert next(w for w in lists if w["id"] == watchlist_id)["asset_ids"] == [asset_id]


def test_cross_tenant_and_header_spoofing_blocked(client, db):
    tenant_id, user_id, watchlist_id = map(str, [uuid4(), uuid4(), uuid4()])
    db.add(Tenant(id=tenant_id, name="other"))
    db.flush()
    db.add(User(id=user_id, tenant_id=tenant_id, name="other", role="owner"))
    db.flush()
    db.add(Watchlist(id=watchlist_id, tenant_id=tenant_id, user_id=user_id, name="private"))
    db.commit()
    rows = client.get("/api/v1/watchlists", headers={"X-Tenant-ID": tenant_id, "X-User-ID": user_id}).json()["items"]
    assert not any(row["id"] == watchlist_id for row in rows)
    assert client.post(f"/api/v1/watchlists/{watchlist_id}/assets", json={"asset_id": nvda(client)}).status_code == 404
    assert client.post("/api/v1/watchlists", json={"name": "bad", "tenant_id": tenant_id}).status_code == 422


def test_alert_evidence_and_deduplication(client, db):
    response = client.post("/api/v1/alert-rules", json={"asset_id": nvda(client), "threshold": 1, "direction": "above"})
    assert response.status_code == 201
    assert db.scalar(select(func.count()).select_from(Alert)) == 1
    assert evaluate_alerts(db) == 0
    item = client.get("/api/v1/alerts").json()["items"][0]
    assert item["data_mode"] == "DEMO"
    assert item["available_as_of"] and item["event_time"]
    assert client.patch("/api/v1/alert-rules/" + response.json()["id"], json={"enabled": False}).status_code == 200


def test_production_startup_fails_closed():
    with pytest.raises(RuntimeError, match="production requires AUTH_MODE=oidc"):
        Settings(APP_ENV="production").assert_auth_ready()
    with pytest.raises(RuntimeError, match="DEMO_MODE"):
        Settings(APP_ENV="development", demo_mode=False).assert_auth_ready()


def test_calendar_unknown_consensus_and_no_llm_failure(client):
    events = client.get("/api/v1/macro/calendar").json()["items"]
    assert all(e["data_mode"] == "DEMO" and e["consensus"] is None for e in events)
    assert client.get("/api/v1/news").json()["ai_status"] == "NOT_CONFIGURED"


def test_origin_and_payload_protection(client):
    assert (
        client.post("/api/v1/watchlists", json={"name": "x"}, headers={"Origin": "https://foreign.example"}).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/watchlists", content=b"x" * 70000, headers={"Content-Type": "application/json"}
        ).status_code
        == 413
    )


def test_seed_idempotent(db):
    before = db.scalar(select(func.count()).select_from(Watchlist))
    seed(db)
    assert db.scalar(select(func.count()).select_from(Watchlist)) == before


def test_withdrawn_coinbase_opt_in_blocks_alert_processing(client, db):
    from app.main import settings
    from app.models import Asset, MarketBar, AlertRule
    from app.auth import DEMO_TENANT_ID, DEMO_USER_ID
    from app.database import utcnow
    from datetime import timedelta
    from decimal import Decimal

    asset = db.scalar(select(Asset).where(Asset.symbol == "BTC-USD"))
    now = utcnow()
    db.add(
        MarketBar(
            asset_id=asset.id,
            source_id="coinbase",
            event_time=now - timedelta(days=1),
            close_time=now,
            available_as_of=now,
            open=Decimal("10"),
            high=Decimal("12"),
            low=Decimal("9"),
            close=Decimal("11"),
            volume=Decimal("100"),
            data_mode="END_OF_DAY",
            evidence_kind="OBSERVED",
        )
    )
    db.add(
        AlertRule(
            asset_id=asset.id,
            tenant_id=DEMO_TENANT_ID,
            user_id=DEMO_USER_ID,
            threshold=Decimal("1"),
            direction="above",
            source_id="coinbase",
        )
    )
    db.commit()
    assert settings.coinbase_personal_use_accepted is False
    assert evaluate_alerts(db) == 0
    assert db.scalar(select(func.count()).select_from(Alert)) == 0
