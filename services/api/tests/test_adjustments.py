from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.adjustments import AdjustmentUnavailable, adjust_series
from app.calendars import session_schedule
from app.catalog import ImportRejected
from app.corporate_actions import import_actions
from app.models import Asset, CorporateAction, MarketBar

UTC = timezone.utc
KNOWN = datetime(2026, 3, 1, tzinfo=UTC)
AS_OF = datetime(2026, 3, 2, tzinfo=UTC)


def raw_series(db, prices=("100", "50", "49"), days=("2026-01-30", "2026-02-02", "2026-02-03")):
    asset = Asset(id=str(uuid4()), symbol="T-" + uuid4().hex[:8], display_name="Test synthetic", asset_type="equity", venue="DEMO", currency="USD", timezone="America/New_York", calendar_id="XNYS", instrument_kind="spot")
    db.add(asset)
    db.flush()
    bars = []
    for day, price in zip(days, prices):
        day = date.fromisoformat(day)
        opens, closes = session_schedule(day, day, "XNYS")[day]
        value = Decimal(price)
        bar = MarketBar(asset_id=asset.id, source_id="demo_test", timeframe="1d", event_time=opens, close_time=closes, open=value, high=value * Decimal("1.01"), low=value * Decimal(".99"), close=value, volume=Decimal("1000"), currency="USD", adjustment="unadjusted", data_mode="DEMO", evidence_kind="SIMULATED", source_uri="fixture:test_bars", available_as_of=closes, ingested_at=KNOWN)
        db.add(bar)
        bars.append(bar)
    db.flush()
    return asset, bars


def split(native="split", day="2026-02-02", new="2", old="1", version=1, cancelled=False):
    return {"native_id": native, "version": version, "action_type": "split", "effective_date": day, "details": {"new_shares": new, "old_shares": old}, "cancelled": cancelled}


def dividend(native="dividend", day="2026-02-03", amount="1", currency="USD"):
    return {"native_id": native, "version": 1, "action_type": "cash_dividend", "effective_date": day, "details": {"amount": amount, "currency": currency}}


def action_document(asset, events, **extra):
    return {"asset_id": asset.id, "source_id": "demo_test", "source_uri": "fixture:test_actions", "data_mode": "DEMO", "dataset_id": "test", "version": 1, "available_as_of": "2026-02-04T00:00:00Z", "coverage": {"from": "2026-01-30", "to": "2026-02-03", "complete": True}, "events": events, **extra}


def apply(db, payload, ingested=KNOWN):
    return import_actions(db, payload, _demo_ingested_at=ingested)


def adjusted(db, asset, bars, kind="split_dividend_adjusted", as_of=AS_OF, source="demo_test"):
    return adjust_series(db, asset, bars, kind, source, as_of)


def test_forward_split_dividend_price_and_volume_without_mutating_raw(db):
    asset, bars = raw_series(db)
    original = [(b.open, b.high, b.low, b.close, b.volume, b.adjustment) for b in bars]
    payload = action_document(asset, [split(), dividend()])
    assert apply(db, payload)["inserted"] == 2
    assert apply(db, payload)["status"] == "UNCHANGED"
    result = adjusted(db, asset, bars)
    assert [b.close for b in result] == [Decimal(49)] * 3
    assert [b.volume for b in result] == [Decimal(2000), Decimal(1000), Decimal(1000)]
    assert result[0].open == 49 and result[0].high == Decimal("49.49") and result[0].low == Decimal("48.51")
    split_only = adjusted(db, asset, bars, "split_adjusted")
    assert [b.close for b in split_only] == [Decimal(50), Decimal(50), Decimal(49)]
    assert [(b.open, b.high, b.low, b.close, b.volume, b.adjustment) for b in bars] == original
    db.expire_all()
    assert [(db.get(MarketBar, b.id).close, db.get(MarketBar, b.id).adjustment) for b in bars] == [(100, "unadjusted"), (50, "unadjusted"), (49, "unadjusted")]


def test_reverse_split_adjusts_volume_inversely(db):
    asset, bars = raw_series(db, prices=("10", "50", "50"))
    apply(db, action_document(asset, [split(new="1", old="5")]))
    result = adjusted(db, asset, bars, "split_adjusted")
    assert result[0].close == 50 and result[0].volume == 200
    assert result[1].close == 50 and result[1].volume == 1000


def test_same_session_splits_normalize_dividend_reference_first(db):
    asset, bars = raw_series(db, prices=("100", "49", "49"))
    events = [dividend("cash-b", "2026-02-02", ".75"), split(), dividend("cash-a", "2026-02-02", ".25")]
    apply(db, action_document(asset, events))
    result = adjusted(db, asset, bars)
    assert result[0].close == 49 and result[0].volume == 2000
    assert result[1].close == 49


def test_same_session_multiple_splits_are_deterministic(db):
    asset, bars = raw_series(db, prices=("120", "20", "20"))
    apply(db, action_document(asset, [split("z", new="2"), split("a", new="3")]))
    result = adjusted(db, asset, bars)
    assert result[0].close == pytest.approx(Decimal(20))
    assert result[0].volume == pytest.approx(Decimal(6000))


def test_missing_or_incomplete_coverage_never_returns_raw_as_adjusted(db):
    asset, bars = raw_series(db)
    with pytest.raises(AdjustmentUnavailable, match="INCOMPLETE_ACTION_COVERAGE"):
        adjusted(db, asset, bars)
    apply(db, action_document(asset, [], coverage={"from": "2026-01-30", "to": "2026-02-03", "complete": False}))
    with pytest.raises(AdjustmentUnavailable, match="INCOMPLETE_ACTION_COVERAGE"):
        adjusted(db, asset, bars)
    payload = action_document(asset, [], version=2)
    apply(db, payload)
    assert adjusted(db, asset, bars)[0].close == 100  # Explicit complete, empty event ledger.


def test_coverage_gaps_and_revocation_are_visible(db):
    asset, bars = raw_series(db)
    apply(db, action_document(asset, [], dataset_id="first", coverage={"from": "2026-01-30", "to": "2026-01-30", "complete": True}))
    apply(db, action_document(asset, [], dataset_id="second", coverage={"from": "2026-02-02", "to": "2026-02-03", "complete": True}))
    with pytest.raises(AdjustmentUnavailable, match="INCOMPLETE_ACTION_COVERAGE"):
        adjusted(db, asset, bars)
    apply(db, action_document(asset, [], dataset_id="first", version=2))
    assert adjusted(db, asset, bars)[0].close == 100
    apply(db, action_document(asset, [], dataset_id="first", version=3, coverage={"from": "2026-01-30", "to": "2026-02-03", "complete": False}))
    with pytest.raises(AdjustmentUnavailable, match="INCOMPLETE_ACTION_COVERAGE"):
        adjusted(db, asset, bars)


def test_revision_publication_and_ingestion_both_gate_correction_and_tombstone(db):
    asset, bars = raw_series(db)
    apply(db, action_document(asset, [split()]))
    corrected = action_document(asset, [split(version=2, new="4")], version=2, available_as_of="2026-03-02T00:00:00Z")
    apply(db, corrected, datetime(2026, 3, 3, tzinfo=UTC))
    assert adjusted(db, asset, bars, as_of=datetime(2026, 3, 2, 12, tzinfo=UTC))[0].close == 50
    assert adjusted(db, asset, bars, as_of=datetime(2026, 3, 3, tzinfo=UTC))[0].close == 25
    cancelled = action_document(asset, [split(version=3, new="4", cancelled=True)], version=3, available_as_of="2026-03-04T00:00:00Z")
    apply(db, cancelled, datetime(2026, 3, 4, tzinfo=UTC))
    assert adjusted(db, asset, bars, as_of=datetime(2026, 3, 4, tzinfo=UTC))[0].close == 100
    assert len(db.scalars(select(CorporateAction).where(CorporateAction.asset_id == asset.id)).all()) == 3


def test_corrected_effective_date_does_not_leave_earlier_revision_applied(db):
    asset, bars = raw_series(db)
    apply(db, action_document(asset, [split()]))
    changed = action_document(asset, [split(day="2026-02-04", version=2)], version=2, coverage={"from": "2026-01-30", "to": "2026-02-04", "complete": True})
    apply(db, changed)
    assert adjusted(db, asset, bars)[0].close == 100


def test_complete_snapshot_cannot_silently_drop_reported_event(db):
    asset, _ = raw_series(db)
    apply(db, action_document(asset, [split()]))
    with pytest.raises(ImportRejected, match="omitted an existing event"):
        apply(db, action_document(asset, [], version=2))
    bad = action_document(asset, [split(new="3")])
    with pytest.raises(ImportRejected, match="Coverage revision is immutable"):
        apply(db, bad)


def test_dividend_requires_immediately_previous_session_close(db):
    asset, bars = raw_series(db, days=("2026-01-29", "2026-02-02", "2026-02-03"))
    payload = action_document(asset, [dividend(day="2026-02-02")], coverage={"from": "2026-01-29", "to": "2026-02-03", "complete": True})
    apply(db, payload)
    with pytest.raises(AdjustmentUnavailable, match="PREVIOUS_SESSION_CLOSE_MISSING"):
        adjusted(db, asset, bars)


@pytest.mark.parametrize("amount", ["50", "51"])
def test_nonpositive_dividend_factor_is_unavailable(db, amount):
    asset, bars = raw_series(db)
    apply(db, action_document(asset, [split(), dividend(amount=amount)]))
    with pytest.raises(AdjustmentUnavailable, match="NONPOSITIVE_DIVIDEND_FACTOR"):
        adjusted(db, asset, bars)


def test_no_implicit_currency_conversion(db):
    asset, bars = raw_series(db)
    with pytest.raises(ImportRejected, match="currency"):
        apply(db, action_document(asset, [dividend(currency="EUR")]))
    apply(db, action_document(asset, []))
    bars[0].currency = "EUR"
    with pytest.raises(AdjustmentUnavailable, match="BAR_CURRENCY"):
        adjusted(db, asset, bars)
    bars[0].currency = None
    with pytest.raises(AdjustmentUnavailable, match="BAR_CURRENCY"):
        adjusted(db, asset, bars)


def test_adjustment_rejects_unknown_calendar_mixed_modes_and_nonraw(db):
    asset, bars = raw_series(db)
    apply(db, action_document(asset, []))
    asset.calendar_id = None
    with pytest.raises(AdjustmentUnavailable, match="CALENDAR_UNAVAILABLE"):
        adjusted(db, asset, bars)
    asset.calendar_id = "XNYS"
    bars[0].data_mode = "END_OF_DAY"
    with pytest.raises(AdjustmentUnavailable, match="MIXED_DATA_MODES"):
        adjusted(db, asset, bars)
    bars[0].data_mode = "DEMO"
    bars[0].adjustment = "split_adjusted"
    with pytest.raises(AdjustmentUnavailable, match="RAW_DAILY_BARS_REQUIRED"):
        adjusted(db, asset, bars)


def test_future_unclosed_and_late_ingested_bars_are_excluded_by_api(db, client):
    asset, bars = raw_series(db)
    bars[1].ingested_at = datetime(2026, 3, 4, tzinfo=UTC)
    bars[2].available_as_of = datetime(2026, 3, 4, tzinfo=UTC)
    db.commit()
    response = client.get(f"/api/v1/assets/{asset.id}/bars", params={"source": "demo_test", "as_of": AS_OF.isoformat()})
    assert response.status_code == 200
    assert [b["id"] for b in response.json()["items"]] == [bars[0].id]
    response = client.get(f"/api/v1/assets/{asset.id}/bars", params={"source": "demo_test", "as_of": "2026-01-30T15:00:00Z"})
    assert response.json()["items"] == []
    assert client.get(f"/api/v1/assets/{asset.id}/bars", params={"as_of": "2099-01-01T00:00:00Z"}).status_code == 422


def test_actions_after_selected_last_bar_do_not_adjust_history(db):
    asset, bars = raw_series(db)
    payload = action_document(asset, [split(day="2026-02-04")], coverage={"from": "2026-01-30", "to": "2026-02-04", "complete": True})
    apply(db, payload)
    assert adjusted(db, asset, bars)[0].close == 100


def test_overflowing_combinations_fail_explicitly(db):
    asset, bars = raw_series(db)
    events = [split(str(i), new="0.000000000001", old="1000000000000") for i in range(5)]
    apply(db, action_document(asset, events))
    with pytest.raises(AdjustmentUnavailable, match="NUMERIC_RANGE_UNSUPPORTED"):
        adjusted(db, asset, bars)


def test_demo_api_returns_metrics_and_prices_share_exact_provenance(client):
    asset_id = client.get("/api/v1/assets", params={"q": "SPLIT-DEMO"}).json()["items"][0]["id"]
    query = {"adjustment": "split_dividend_adjusted", "as_of": "2026-10-08T00:00:00Z", "corporate_action_source": "demo"}
    responses = [client.get(f"/api/v1/assets/{asset_id}/{path}", params=query) for path in ("bars", "returns", "metrics")]
    assert [r.status_code for r in responses] == [200, 200, 200]
    prices, returns, metrics = [r.json() for r in responses]
    for key in ("source_id", "data_mode", "as_of", "last_observation_at", "currency", "calendar_id", "adjustment", "action_source_id", "adjustment_status", "adjustment_methodology"):
        assert prices[key] == returns[key] == metrics[key]
    assert prices["as_of"] != prices["last_observation_at"]
    assert prices["items"][0]["close"] == 49 and prices["items"][0]["volume"] == 2000
    assert returns["items"][-1]["return_pct"] == 0
    assert metrics["max_drawdown_pct"] == 0 and metrics["sma_20"] == 49
    raw = client.get(f"/api/v1/assets/{asset_id}/bars").json()
    assert raw["items"][0]["close"] == 100 and raw["items"][0]["volume"] == 1000
    assert client.get(f"/api/v1/assets/{asset_id}/bars", params={**query, "as_of": "2026-10-07T00:00:00Z"}).status_code == 409
    unknown = client.get(f"/api/v1/assets/{asset_id}/bars", params={**query, "corporate_action_source": "unconfigured"})
    assert unknown.status_code == 409 and unknown.json()["detail"]["code"] == "ADJUSTMENT_UNAVAILABLE"
