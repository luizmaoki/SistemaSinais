"""Explicit, bounded calendars. No exchange/type guessing in the API path."""
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

import exchange_calendars as xcals

SUPPORTED_CALENDARS = {"XNYS": "America/New_York", "24/7": "UTC"}
# XNAS/NASDAQ/ARCX share XNYS in exchange_calendars 4.13.2. This is an explicit
# daily cash-equity pilot mapping, not a claim about every exchange product.
CASH_VENUES = {"NYSE", "NASDAQ", "NYSE ARCA", "NYSE AMERICAN", "XNYS", "XNAS", "ARCX", "XASE"}
CASH_CLASSES = {"equity", "etf", "etn", "etp", "adr", "reit"}


class CalendarUnavailable(ValueError):
    pass


@lru_cache(maxsize=1)
def nyse_calendar():
    return xcals.get_calendar("XNYS", start="2000-01-01", end="2035-12-31")


def catalog_calendar(asset_type, venue, instrument_kind=None):
    if asset_type == "crypto" and instrument_kind in {None, "spot"}:
        return "24/7"
    if asset_type in CASH_CLASSES and venue in CASH_VENUES:
        return "XNYS"
    if venue == "DEMO" and asset_type == "equity":
        return "XNYS"
    return None


def session_schedule(start: date, end: date, calendar_id: str | None) -> dict[date, tuple[datetime, datetime]]:
    if calendar_id not in SUPPORTED_CALENDARS:
        raise CalendarUnavailable("CALENDAR_NOT_CONFIGURED")
    if end < start:
        return {}
    if calendar_id == "24/7":
        return {
            start + timedelta(days=i): (
                datetime.combine(start + timedelta(days=i), datetime.min.time(), timezone.utc),
                datetime.combine(start + timedelta(days=i + 1), datetime.min.time(), timezone.utc),
            )
            for i in range((end - start).days + 1)
        }
    if start < date(2000, 1, 1) or end > date(2035, 12, 31):
        raise CalendarUnavailable("CALENDAR_OUT_OF_SUPPORTED_RANGE")
    cal = nyse_calendar()
    sessions = cal.sessions_in_range(start.isoformat(), end.isoformat())
    return {
        stamp.date(): (cal.session_open(stamp).to_pydatetime(), cal.session_close(stamp).to_pydatetime())
        for stamp in sessions
    }


def previous_session(day: date, calendar_id: str | None) -> date:
    days = session_schedule(day - timedelta(days=14), day - timedelta(days=1), calendar_id)
    if not days:
        raise CalendarUnavailable("PREVIOUS_SESSION_UNAVAILABLE")
    return max(days)
