from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import pytest
from app.calculations import monthly_returns, technical_metrics, session_closes

UTC = timezone.utc


def bar(day, price):
    stamp = datetime.fromisoformat(day + "T00:00:00+00:00")
    return SimpleNamespace(
        event_time=stamp,
        close_time=stamp.replace(hour=23),
        available_as_of=stamp.replace(hour=23),
        close=Decimal(str(price)),
        volume=Decimal("100"),
    )


def test_monthly_return_previous_month_not_first_current():
    rows = monthly_returns(
        [bar("2026-01-31", 100), bar("2026-02-01", 120), bar("2026-02-28", 110)],
        "crypto",
        "UTC",
        datetime(2026, 3, 1, tzinfo=UTC),
    )
    assert rows[0]["return_pct"] is None
    assert rows[1]["return_pct"] == pytest.approx(10)
    assert rows[1]["partial"]  # Missing interior sessions are explicit.
    assert "MISSING_SESSIONS" in rows[1]["reason"]


def test_missing_month_is_not_bridged():
    rows = monthly_returns(
        [bar("2026-01-31", 100), bar("2026-03-31", 130)], "crypto", "UTC", datetime(2026, 4, 1, tzinfo=UTC)
    )
    assert rows[1]["month"] == "2026-02"
    assert rows[1]["return_pct"] is None
    assert rows[2]["return_pct"] is None


def test_current_month_partial_and_future_not_visible():
    asof = datetime(2026, 2, 3, tzinfo=UTC)
    rows = monthly_returns(
        [bar("2026-01-31", 100), bar("2026-02-01", 105), bar("2026-02-15", 999)], "crypto", "UTC", asof
    )
    assert rows[-1]["last_close"] == 105
    assert rows[-1]["partial"]
    assert "CURRENT_MONTH" in rows[-1]["reason"]


def test_late_ingestion_cannot_be_used_point_in_time():
    row = bar("2026-01-31", 100)
    row.available_as_of = datetime(2026, 3, 1, tzinfo=UTC)
    assert monthly_returns([row], "crypto", "UTC", datetime(2026, 2, 1, tzinfo=UTC)) == []


def test_nyse_holidays_and_dst():
    sessions = session_closes(datetime(2026, 7, 3).date(), datetime(2026, 7, 6).date(), "equity")
    assert len(sessions) == 1
    assert list(sessions.values())[0].hour == 20
    winter = session_closes(datetime(2026, 1, 5).date(), datetime(2026, 1, 5).date(), "equity")
    assert list(winter.values())[0].hour == 21


def test_metrics_drawdown_and_insufficient_history():
    result = technical_metrics([bar("2026-01-01", 100), bar("2026-01-02", 80), bar("2026-01-03", 90)], "crypto")
    assert result["max_drawdown_pct"] == pytest.approx(-20)
    assert result["sma_20"] is None
    assert result["rsi_14"] is None


def test_volatility_requires_consecutive_daily_sessions():
    from datetime import timedelta

    start = datetime(2026, 1, 1, tzinfo=UTC)
    prices = [100 + (i % 4) * 3 for i in range(21)]
    complete = [bar((start + timedelta(days=i)).date().isoformat(), price) for i, price in enumerate(prices)]
    gapped = [bar((start + timedelta(days=i * 2)).date().isoformat(), price) for i, price in enumerate(prices)]
    assert technical_metrics(complete, "crypto")["volatility_20_annualized_pct"] is not None
    invalid = technical_metrics(gapped, "crypto")
    assert invalid["volatility_20_annualized_pct"] is None
    assert invalid["frequency_quality"] == "MISSING_SESSIONS"
