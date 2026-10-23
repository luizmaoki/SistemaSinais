from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from app.catalog import ImportRejected, import_catalog
from app.models import Asset, CatalogImport, MarketBar

UTC = timezone.utc
KNOWN = datetime(2026, 10, 9, tzinfo=UTC)


def option_document(db):
    underlying = db.scalar(select(Asset).where(Asset.symbol == "NVDA"))
    return {
        "source_id": "demo_option_test", "source_uri": "fixture:option_contract", "metadata_status": "DEMO",
        "available_as_of": "2026-10-08T00:00:00Z",
        "assets": [{
            "id": str(uuid4()), "symbol": "NVDA-DEC26-C100", "display_name": "Synthetic call",
            "asset_type": "option", "venue": "DEMO", "currency": "USD", "timezone": "America/New_York",
            "calendar_id": None, "instrument_kind": "contract", "underlying_asset_id": underlying.id,
            "contract_multiplier": "100", "option_type": "call", "strike": "100", "expiration": "2026-12-18",
        }],
    }


@pytest.mark.parametrize("field,value", [("option_type", "put"), ("strike", "200")])
@pytest.mark.parametrize("with_bar", [True, False])
def test_option_identity_cannot_be_reassigned_and_import_is_atomic(db, field, value, with_bar):
    payload = option_document(db)
    import_catalog(db, payload, _demo_ingested_at=KNOWN)
    asset_id = payload["assets"][0]["id"]
    if with_bar:
        db.add(MarketBar(asset_id=asset_id, source_id="demo", timeframe="1d", event_time=datetime(2026, 10, 8, 13, 30, tzinfo=UTC), close_time=datetime(2026, 10, 8, 20, tzinfo=UTC), open=100, high=101, low=99, close=100, volume=10, currency="USD", adjustment="unadjusted", data_mode="DEMO", evidence_kind="SIMULATED", available_as_of=KNOWN, ingested_at=KNOWN))
        db.flush()
    before = db.scalar(select(func.count()).select_from(CatalogImport))
    changed = deepcopy(payload)
    changed["assets"][0][field] = value
    changed["assets"][0]["display_name"] = "Must not replace the original"
    other = deepcopy(payload["assets"][0])
    other.update(id=str(uuid4()), symbol="SHOULD-NOT-BE-IMPORTED")
    changed["assets"].insert(0, other)
    with pytest.raises(ImportRejected, match="immutable|cannot be reassigned"):
        import_catalog(db, changed, _demo_ingested_at=KNOWN)
    assert db.get(Asset, other["id"]) is None
    original = db.get(Asset, asset_id)
    assert original.option_type == "call" and original.strike == Decimal("100")
    assert original.display_name == "Synthetic call"
    assert db.scalar(select(func.count()).select_from(CatalogImport)) == before
    if with_bar:
        assert db.scalar(select(MarketBar.close).where(MarketBar.asset_id == asset_id)) == Decimal("100")


def test_unchanged_option_strike_precision_allows_metadata_update(db):
    payload = option_document(db)
    import_catalog(db, payload, _demo_ingested_at=KNOWN)
    db.flush()
    db.expire_all()
    payload["assets"][0]["display_name"] = "Updated label"
    payload["assets"][0]["strike"] = "100.00000000"
    import_catalog(db, payload, _demo_ingested_at=KNOWN)
    assert db.get(Asset, payload["assets"][0]["id"]).display_name == "Updated label"


@pytest.mark.parametrize("currency", [None, "EUR", "mixed"])
def test_catalog_scanner_and_metrics_consistently_hide_invalid_denomination(db, client, currency):
    asset = db.scalar(select(Asset).where(Asset.symbol == "SPLIT-DEMO"))
    condition = MarketBar.asset_id == asset.id
    if currency == "mixed":
        first_id = db.scalar(select(MarketBar.id).where(condition).order_by(MarketBar.event_time).limit(1))
        db.execute(update(MarketBar).where(MarketBar.id == first_id).values(currency="EUR"))
    else:
        db.execute(update(MarketBar).where(condition).values(currency=currency))
    db.commit()
    expected_reason = "CURRENCY_UNAVAILABLE" if currency is None else "SERIES_CURRENCY_MISMATCH"
    detailed = client.get(f"/api/v1/assets/{asset.id}").json()
    listed = client.get("/api/v1/assets?q=SPLIT-DEMO").json()["items"][0]
    scanned = client.get("/api/v1/scanner?q=SPLIT-DEMO").json()["items"][0]
    watchlist = client.get("/api/v1/watchlists").json()["items"][0]
    assert client.post(f"/api/v1/watchlists/{watchlist['id']}/assets", json={"asset_id": asset.id}).status_code == 200
    watched = client.get("/api/v1/watchlists").json()["items"][0]["assets"][0]
    for projection in (detailed, listed, scanned, watched):
        assert projection["currency"] == "USD"  # Instrument metadata, not an invented denomination for a quote.
        assert projection["latest_price"] is None and projection["change_pct"] is None
        assert projection["quote_currency"] is None and projection["quote_status"] == "UNAVAILABLE"
        assert projection["quote_reason"] == expected_reason and projection["data_mode"] == "UNAVAILABLE"
    assert scanned["metrics"]["calculation_status"] == "UNAVAILABLE"
    assert scanned["metrics"]["frequency_quality"] == expected_reason
    assert scanned["metrics"].get("max_drawdown_pct") is None
    bars = client.get(f"/api/v1/assets/{asset.id}/bars")
    metrics = client.get(f"/api/v1/assets/{asset.id}/metrics")
    if currency is None:
        assert bars.status_code == metrics.status_code == 200
        assert bars.json()["currency"] is None
        assert metrics.json()["frequency_quality"] == scanned["metrics"]["frequency_quality"]
        assert metrics.json().get("max_drawdown_pct") is None
    else:
        assert bars.status_code == metrics.status_code == 409
        assert bars.json()["detail"]["code"] == expected_reason


def test_consistent_non_usd_series_keeps_original_prices_and_currency(db, client):
    asset = db.scalar(select(Asset).where(Asset.symbol == "SPLIT-DEMO"))
    asset.currency = "EUR"
    db.execute(update(MarketBar).where(MarketBar.asset_id == asset.id).values(currency="EUR"))
    db.commit()
    row = client.get("/api/v1/scanner?q=SPLIT-DEMO").json()["items"][0]
    assert row["currency"] == row["quote_currency"] == "EUR"
    assert row["latest_price"] == 49 and row["quote_status"] == "AVAILABLE"
    assert row["metrics"]["calculation_status"] == "AVAILABLE"
    assert client.get(f"/api/v1/assets/{asset.id}/bars").json()["currency"] == "EUR"
