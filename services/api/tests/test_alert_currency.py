from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.auth import DEMO_TENANT_ID, DEMO_USER_ID
from app.ingestion import evaluate_alerts
from app.models import Alert, AlertRule, Asset, MarketBar, Tenant, User

UTC = timezone.utc
STAMP = datetime(2026, 10, 8, 20, tzinfo=UTC)


def observation(db, currency, *, rule=True):
    asset = Asset(id=str(uuid4()), symbol="ALERT-" + uuid4().hex[:8], display_name="Synthetic alert", asset_type="equity", venue="DEMO", currency="USD", timezone="America/New_York", calendar_id="XNYS", instrument_kind="spot")
    db.add(asset)
    db.flush()
    bar = MarketBar(asset_id=asset.id, source_id="demo", timeframe="1d", event_time=STAMP.replace(hour=13, minute=30), close_time=STAMP, open=100, high=101, low=99, close=100, volume=100, currency=currency, adjustment="unadjusted", data_mode="DEMO", evidence_kind="SIMULATED", available_as_of=STAMP, ingested_at=STAMP)
    db.add(bar)
    created_rule = None
    if rule:
        created_rule = AlertRule(tenant_id=DEMO_TENANT_ID, user_id=DEMO_USER_ID, asset_id=asset.id, threshold=50, direction="above", source_id="demo")
        db.add(created_rule)
    db.flush()
    return asset, bar, created_rule


def historical_alert(db, asset, bar, rule, tenant_id=DEMO_TENANT_ID, user_id=DEMO_USER_ID):
    alert = Alert(tenant_id=tenant_id, user_id=user_id, rule_id=rule.id, bar_id=bar.id, asset_id=asset.id, message="Historic synthetic evidence", observed_price=100, threshold=50, source_id="demo", data_mode="DEMO", evidence_kind="SIMULATED", event_time=STAMP, available_as_of=STAMP)
    db.add(alert)
    db.flush()
    return alert


def test_worker_skips_unknown_or_mismatched_currency_and_preserves_valid_alert(db):
    invalid_unknown = observation(db, None)
    invalid_eur = observation(db, "EUR")
    valid = observation(db, "USD")
    assert evaluate_alerts(db) == 1
    rows = list(db.scalars(select(Alert)))
    assert [row.bar_id for row in rows] == [valid[1].id]
    assert all(row.bar_id not in {invalid_unknown[1].id, invalid_eur[1].id} for row in rows)
    assert evaluate_alerts(db) == 0


@pytest.mark.parametrize("currency,code", [(None, "CURRENCY_UNAVAILABLE"), ("EUR", "SERIES_CURRENCY_MISMATCH")])
def test_creation_refuses_rule_on_inconsistent_denomination(db, client, currency, code):
    asset, _, _ = observation(db, currency, rule=False)
    db.commit()
    response = client.post("/api/v1/alert-rules", json={"asset_id": asset.id, "threshold": 50, "direction": "above"})
    assert response.status_code == 409 and response.json()["detail"]["code"] == code
    assert db.scalar(select(func.count()).select_from(AlertRule)) == 0
    assert db.scalar(select(func.count()).select_from(Alert)) == 0


def test_historic_alert_currency_comes_from_original_bar_with_owner_scope(db, client):
    expected = {}
    for currency in (None, "EUR", "USD"):
        asset, bar, rule = observation(db, currency)
        alert = historical_alert(db, asset, bar, rule)
        expected[alert.id] = currency
    # Another owner's alert references the same public market observation, but
    # must remain private even after the API joins the market-bar currency.
    tenant_id, user_id = str(uuid4()), str(uuid4())
    db.add(Tenant(id=tenant_id, name="Other"))
    db.flush()
    db.add(User(id=user_id, tenant_id=tenant_id, name="Other", role="owner"))
    db.flush()
    other_rule = AlertRule(tenant_id=tenant_id, user_id=user_id, asset_id=asset.id, threshold=50, direction="above", source_id="demo")
    db.add(other_rule)
    db.flush()
    foreign = historical_alert(db, asset, bar, other_rule, tenant_id, user_id)
    db.commit()
    rows = client.get("/api/v1/alerts").json()["items"]
    assert {row["id"]: row["observed_currency"] for row in rows} == expected
    assert foreign.id not in {row["id"] for row in rows}
    assert all(row["observed_price"] == 100 for row in rows)


def test_valid_rule_exposes_observation_currency(db, client):
    asset, _, _ = observation(db, "USD", rule=False)
    db.commit()
    assert client.post("/api/v1/alert-rules", json={"asset_id": asset.id, "threshold": 50, "direction": "above"}).status_code == 201
    assert client.get("/api/v1/alerts").json()["items"][0]["observed_currency"] == "USD"
