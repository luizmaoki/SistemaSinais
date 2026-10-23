import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo
from app.calendars import CalendarUnavailable, SUPPORTED_CALENDARS, nyse_calendar, session_schedule  # noqa: F401

LEGACY_CALENDAR = "__legacy__"


def resolved_calendar(asset_type, calendar_id):
    # Only legacy pure-function callers infer a calendar; API callers pass it explicitly.
    return ("24/7" if asset_type == "crypto" else "XNYS") if calendar_id == LEGACY_CALENDAR else calendar_id


def session_closes(start: date, end: date, asset_type: str, calendar_id=LEGACY_CALENDAR) -> dict[date, datetime]:
    return {day: times[1] for day, times in session_schedule(start, end, resolved_calendar(asset_type, calendar_id)).items()}


def month_before(value: date) -> date:
    return (value.replace(day=1) - timedelta(days=1)).replace(day=1)


def next_month(value: date) -> date:
    return (value.replace(day=28) + timedelta(days=4)).replace(day=1)


def known_closed(bar, as_of):
    return bar.close_time <= as_of and bar.available_as_of <= as_of and (getattr(bar, "ingested_at", None) is None or bar.ingested_at <= as_of)


def monthly_returns(bars, asset_type: str, timezone_name: str, as_of: datetime, calendar_id=LEGACY_CALENDAR) -> list[dict]:
    """Last close / previous calendar-month last close; never bridge missing months."""
    calendar_key = resolved_calendar(asset_type, calendar_id)
    if calendar_key not in SUPPORTED_CALENDARS:
        return []
    tz = ZoneInfo(timezone_name)
    grouped = defaultdict(list)
    for bar in bars:
        if known_closed(bar, as_of):
            local_date = bar.event_time.astimezone(tz).date()
            grouped[local_date.replace(day=1)].append((local_date, bar))
    if not grouped:
        return []
    cursor, final = min(grouped), max(grouped)
    result = []
    while cursor <= final:
        month_end = date(cursor.year, cursor.month, calendar.monthrange(cursor.year, cursor.month)[1])
        try:
            expected = session_closes(cursor, month_end, asset_type, calendar_key)
            previous_month = month_before(cursor)
            previous_sessions = session_closes(previous_month, cursor - timedelta(days=1), asset_type, calendar_key)
        except CalendarUnavailable:
            return []
        closed_expected = {day: close for day, close in expected.items() if close <= as_of}
        records = sorted(grouped.get(cursor, []), key=lambda pair: pair[1].event_time)
        valid = [(day, bar) for day, bar in records if day in closed_expected and (calendar_id == LEGACY_CALENDAR or bar.close_time == expected[day])]
        previous_records = sorted(grouped.get(previous_month, []), key=lambda pair: pair[1].event_time)
        previous_expected_last = max(previous_sessions, default=None)
        previous_close = None
        if previous_records and previous_records[-1][0] == previous_expected_last:
            if calendar_id == LEGACY_CALENDAR or previous_records[-1][1].close_time == previous_sessions[previous_expected_last]:
                previous_close = Decimal(previous_records[-1][1].close)
        observed_days = {day for day, _ in valid}
        gaps = sorted(day.isoformat() for day in closed_expected if day not in observed_days)
        calendar_partial = bool(expected) and as_of < max(expected.values())
        reasons = []
        if calendar_partial:
            reasons.append("CURRENT_MONTH")
        if gaps:
            reasons.append("MISSING_SESSIONS")
        if len(observed_days) != len(valid):
            reasons.append("DUPLICATE_SESSIONS")
        if previous_close is None:
            reasons.append("NO_PREVIOUS_MONTH_CLOSE")
        last_close = Decimal(valid[-1][1].close) if valid else None
        with localcontext() as context:
            context.prec = 50
            value = ((last_close / previous_close - 1) * 100) if last_close is not None and previous_close and previous_close > 0 else None
        result.append({
            "month": cursor.strftime("%Y-%m"),
            "return_pct": float(round(value, 6)) if value is not None else None,
            "partial": calendar_partial or bool(gaps) or len(observed_days) != len(valid),
            "reason": ",".join(reasons) or None,
            "previous_close": float(previous_close) if previous_close is not None else None,
            "first_close": float(valid[0][1].close) if valid else None,
            "last_close": float(last_close) if last_close is not None else None,
            "observations": len(valid), "expected_observations": len(closed_expected), "gaps": gaps,
            "last_observation_at": valid[-1][1].close_time if valid else None,
        })
        cursor = next_month(cursor)
    return result


def technical_metrics(bars, asset_type: str, calendar_id=LEGACY_CALENDAR, timezone_name=None) -> dict:
    calendar_key = resolved_calendar(asset_type, calendar_id)
    if calendar_key not in SUPPORTED_CALENDARS:
        return {"calculation_status": "UNAVAILABLE", "frequency_quality": "CALENDAR_UNAVAILABLE", "volatility_reason": "CALENDAR_UNAVAILABLE"}
    if not bars:
        return {}
    tz = ZoneInfo(timezone_name or SUPPORTED_CALENDARS[calendar_key])
    days = [b.event_time.astimezone(tz).date() for b in bars]
    try:
        schedule = session_schedule(min(days), max(days), calendar_key)
    except CalendarUnavailable:
        return {"calculation_status": "UNAVAILABLE", "frequency_quality": "CALENDAR_UNAVAILABLE", "volatility_reason": "CALENDAR_UNAVAILABLE"}
    if calendar_id != LEGACY_CALENDAR and any(day not in schedule or bar.close_time != schedule[day][1] for day, bar in zip(days, bars)):
        return {"calculation_status": "UNAVAILABLE", "frequency_quality": "INVALID_SESSION", "volatility_reason": "BAR_SESSION_MISMATCH"}
    closes = [Decimal(b.close) for b in bars]
    volumes = [Decimal(b.volume) for b in bars]
    if any(c <= 0 for c in closes) or any(v < 0 for v in volumes):
        return {"calculation_status": "UNAVAILABLE", "frequency_quality": "INVALID_PRICE"}
    with localcontext() as context:
        context.prec = 50
        changes = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
        rsi = None
        if len(closes) >= 15:
            deltas = [closes[i] - closes[i - 1] for i in range(len(closes) - 14, len(closes))]
            gain = sum(max(delta, Decimal(0)) for delta in deltas) / 14
            loss = sum(max(-delta, Decimal(0)) for delta in deltas) / 14
            rsi = 100 - 100 / (1 + gain / loss) if loss else (Decimal(100) if gain else Decimal(50))
        peak, max_drawdown = closes[0], Decimal(0)
        for close in closes:
            peak = max(peak, close)
            max_drawdown = min(max_drawdown, close / peak - 1)
        window_days = days[-21:]
        expected_days = {day for day in schedule if window_days[0] <= day <= window_days[-1]}
        complete = len(window_days) == len(set(window_days)) and set(window_days) == expected_days
        baseline = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else None
        volatility = None
        if len(changes) >= 20 and complete:
            mean = sum(changes[-20:]) / 20
            variance = sum((v - mean) ** 2 for v in changes[-20:]) / 20
            volatility = variance.sqrt() * Decimal(365 if calendar_key == "24/7" else 252).sqrt() * 100
        values = {
            "sma_20": sum(closes[-20:]) / 20 if len(closes) >= 20 else None,
            "sma_50": sum(closes[-50:]) / 50 if len(closes) >= 50 else None,
            "rsi_14": rsi, "volatility_20_annualized_pct": volatility,
            "daily_volume_ratio_20": volumes[-1] / baseline if baseline else None,
            "max_drawdown_pct": max_drawdown * 100,
        }
    return {
        **{key: float(value) if value is not None else None for key, value in values.items()},
        "calculation_status": "AVAILABLE",
        "frequency_quality": "CONSECUTIVE_SESSIONS" if complete else "MISSING_SESSIONS",
        "volatility_reason": None if volatility is not None else "INSUFFICIENT_OR_GAPPED_DAILY_WINDOW",
        "methodology": "Indicadores em candles diários fechados: RSI médias simples de 14 diferenças; volatilidade populacional de 20 retornos; SMA/RSI usam barras disponíveis; volatilidade exige 20 retornos diários consecutivos. Volume ratio usa 20 barras diárias disponíveis, não RVOL intradiário.",
    }
