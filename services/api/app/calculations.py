import calendar
import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from statistics import pstdev
from zoneinfo import ZoneInfo

import exchange_calendars as xcals


@lru_cache(maxsize=1)
def nyse_calendar():
    # Explicit bounds keep reproducible historical/demo dates and include the MVP horizon.
    return xcals.get_calendar("XNYS", start="2000-01-01", end="2035-12-31")


def session_closes(start: date, end: date, asset_type: str) -> dict[date, datetime]:
    if end < start:
        return {}
    if asset_type == "crypto":
        return {
            start + timedelta(days=i): datetime.combine(
                start + timedelta(days=i + 1), datetime.min.time(), timezone.utc
            )
            for i in range((end - start).days + 1)
        }
    cal = nyse_calendar()
    sessions = cal.sessions_in_range(start.isoformat(), end.isoformat())
    return {stamp.date(): cal.session_close(stamp).to_pydatetime() for stamp in sessions}


def month_before(value: date) -> date:
    return (value.replace(day=1) - timedelta(days=1)).replace(day=1)


def next_month(value: date) -> date:
    return (value.replace(day=28) + timedelta(days=4)).replace(day=1)


def monthly_returns(bars, asset_type: str, timezone_name: str, as_of: datetime) -> list[dict]:
    """Last close / immediately previous calendar-month last close - 1; no gap bridging."""
    tz = ZoneInfo(timezone_name)
    grouped = defaultdict(list)
    for bar in bars:
        if bar.close_time <= as_of and bar.available_as_of <= as_of:
            local_date = bar.event_time.astimezone(tz).date()
            grouped[local_date.replace(day=1)].append((local_date, bar))
    if not grouped:
        return []
    cursor, final = min(grouped), max(grouped)
    result = []
    while cursor <= final:
        month_end = date(cursor.year, cursor.month, calendar.monthrange(cursor.year, cursor.month)[1])
        expected = session_closes(cursor, month_end, asset_type)
        closed_expected = {day: close for day, close in expected.items() if close <= as_of}
        records = sorted(grouped.get(cursor, []), key=lambda pair: pair[1].event_time)
        valid = [(day, bar) for day, bar in records if day in expected]
        previous_month = month_before(cursor)
        previous_records = sorted(grouped.get(previous_month, []), key=lambda pair: pair[1].event_time)
        previous_end = cursor - timedelta(days=1)
        previous_sessions = session_closes(previous_month, previous_end, asset_type)
        previous_expected_last = max(previous_sessions, default=None)
        previous_close = None
        if previous_records and previous_records[-1][0] == previous_expected_last:
            previous_close = float(previous_records[-1][1].close)
        observed_days = {day for day, _ in valid}
        gaps = sorted(day.isoformat() for day in closed_expected if day not in observed_days)
        calendar_partial = bool(expected) and as_of < max(expected.values())
        partial = calendar_partial or bool(gaps)
        reasons = []
        if calendar_partial:
            reasons.append("CURRENT_MONTH")
        if gaps:
            reasons.append("MISSING_SESSIONS")
        if previous_close is None:
            reasons.append("NO_PREVIOUS_MONTH_CLOSE")
        last_close = float(valid[-1][1].close) if valid else None
        return_pct = (
            (last_close / previous_close - 1) * 100
            if last_close is not None and previous_close and previous_close > 0
            else None
        )
        result.append(
            {
                "month": cursor.strftime("%Y-%m"),
                "return_pct": round(return_pct, 6) if return_pct is not None else None,
                "partial": partial,
                "reason": ",".join(reasons) or None,
                "previous_close": previous_close,
                "first_close": float(valid[0][1].close) if valid else None,
                "last_close": last_close,
                "observations": len(valid),
                "expected_observations": len(closed_expected),
                "gaps": gaps,
                "last_observation_at": valid[-1][1].close_time if valid else None,
            }
        )
        cursor = next_month(cursor)
    return result


def technical_metrics(bars, asset_type: str) -> dict:
    closes = [float(bar.close) for bar in bars]
    volumes = [float(bar.volume) for bar in bars]
    if not closes:
        return {}
    changes = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes)) if closes[i - 1] > 0]
    rsi = None
    if len(closes) >= 15:
        deltas = [closes[i] - closes[i - 1] for i in range(len(closes) - 14, len(closes))]
        gain = sum(max(delta, 0) for delta in deltas) / 14
        loss = sum(max(-delta, 0) for delta in deltas) / 14
        rsi = 100 - 100 / (1 + gain / loss) if loss else (100.0 if gain else 50.0)
    peak = closes[0]
    max_drawdown = 0.0
    for close in closes:
        peak = max(peak, close)
        max_drawdown = min(max_drawdown, close / peak - 1)
    tz = ZoneInfo("UTC" if asset_type == "crypto" else "America/New_York")
    window = bars[-21:]
    window_days = [bar.event_time.astimezone(tz).date() for bar in window]
    expected_days = set(session_closes(window_days[0], window_days[-1], asset_type))
    daily_complete = len(window_days) == len(set(window_days)) and set(window_days) == expected_days
    baseline = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else None
    return {
        "sma_20": sum(closes[-20:]) / 20 if len(closes) >= 20 else None,
        "sma_50": sum(closes[-50:]) / 50 if len(closes) >= 50 else None,
        "rsi_14": rsi,
        "volatility_20_annualized_pct": pstdev(changes[-20:]) * math.sqrt(365 if asset_type == "crypto" else 252) * 100
        if len(changes) >= 20 and daily_complete
        else None,
        "daily_volume_ratio_20": volumes[-1] / baseline if baseline else None,
        "max_drawdown_pct": max_drawdown * 100,
        "frequency_quality": "CONSECUTIVE_SESSIONS" if daily_complete else "MISSING_SESSIONS",
        "volatility_reason": None if len(changes) >= 20 and daily_complete else "INSUFFICIENT_OR_GAPPED_DAILY_WINDOW",
        "methodology": "Indicadores em candles diários fechados: RSI médias simples de 14 diferenças; volatilidade populacional de 20 retornos; SMA/RSI usam barras disponíveis; volatilidade exige 20 retornos diários consecutivos. Volume ratio usa 20 barras diárias disponíveis, não RVOL intradiário.",
    }
