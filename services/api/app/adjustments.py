"""Backward price adjustment v1; never a total-return or reinvestment model."""
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal, DecimalException, localcontext
from zoneinfo import ZoneInfo

from app.calendars import CalendarUnavailable, SUPPORTED_CALENDARS, previous_session, session_schedule
from app.corporate_actions import latest_actions, latest_coverage

METHODOLOGY = {
    "unadjusted": "RAW_V1: preços e volumes originais, sem ajustes ou conversão cambial.",
    "split_adjusted": "BACKWARD_PRICE_V1: OHLC anteriores × old_shares/new_shares; volume inverso. Sem dividendos ou conversão cambial.",
    "split_dividend_adjusted": "BACKWARD_PRICE_V1: splits e dividendos em dinheiro ajustam OHLC anteriores. Dividendo por ação após splits: 1-D/fechamento anterior normalizado. Volume só por splits. Ajuste de preço, sem retorno total, reinvestimento, taxas ou conversão cambial.",
}


class AdjustmentUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class PriceBar:
    id: str
    asset_id: str
    source_id: str
    timeframe: str
    event_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    data_mode: str
    evidence_kind: str
    adjustment: str
    currency: str | None
    source_uri: str | None
    available_as_of: datetime
    ingested_at: datetime

    @classmethod
    def from_row(cls, row):
        return cls(**{name: getattr(row, name) for name in cls.__dataclass_fields__})


def has_coverage(rows, start, end):
    cursor = start
    for row in rows:
        if not row.complete or row.coverage_to < cursor:
            continue
        if row.coverage_from > cursor:
            return False
        cursor = max(cursor, row.coverage_to + timedelta(days=1))
        if cursor > end:
            return True
    return False


def checked(value, *, allow_zero=False):
    if not value.is_finite() or value < 0 or (not allow_zero and value == 0) or value > Decimal("1e100") or (value and value < Decimal("1e-100")):
        raise AdjustmentUnavailable("NUMERIC_RANGE_UNSUPPORTED")
    return value


def adjust_series(session, asset, bars, adjustment, action_source, as_of):
    snapshots = [PriceBar.from_row(b) for b in bars]
    if adjustment == "unadjusted":
        return snapshots
    if not snapshots:
        raise AdjustmentUnavailable("NO_CLOSED_RAW_BARS")
    if asset.calendar_id not in SUPPORTED_CALENDARS or asset.timezone != SUPPORTED_CALENDARS[asset.calendar_id]:
        raise AdjustmentUnavailable("CALENDAR_UNAVAILABLE")
    tz = ZoneInfo(asset.timezone)
    days = [b.event_time.astimezone(tz).date() for b in snapshots]
    try:
        schedule = session_schedule(min(days), max(days), asset.calendar_id)
    except CalendarUnavailable as error:
        raise AdjustmentUnavailable(str(error)) from None
    modes = {b.data_mode for b in snapshots}
    if len(modes) != 1:
        raise AdjustmentUnavailable("MIXED_DATA_MODES")
    mode = next(iter(modes))
    if mode not in {"DEMO", "END_OF_DAY"} or (mode == "DEMO") != action_source.startswith("demo"):
        raise AdjustmentUnavailable("ACTION_SOURCE_MODE_MISMATCH")
    if any(b.currency != asset.currency for b in snapshots):
        raise AdjustmentUnavailable("BAR_CURRENCY_UNKNOWN_OR_MISMATCH")
    if len(days) != len(set(days)):
        raise AdjustmentUnavailable("DUPLICATE_SESSION")
    for day, bar in zip(days, snapshots):
        if bar.adjustment != "unadjusted" or bar.timeframe != "1d":
            raise AdjustmentUnavailable("RAW_DAILY_BARS_REQUIRED")
        if day not in schedule or bar.close_time != schedule[day][1] or not schedule[day][0] <= bar.event_time < bar.close_time:
            raise AdjustmentUnavailable("BAR_SESSION_MISMATCH")
        if bar.close_time > as_of or bar.available_as_of > as_of or bar.ingested_at > as_of:
            raise AdjustmentUnavailable("BAR_NOT_KNOWN_OR_CLOSED")
        if not (0 < bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high) or bar.volume < 0:
            raise AdjustmentUnavailable("INVALID_OHLCV")
    coverages = latest_coverage(session, asset.id, action_source, mode, as_of)
    if not has_coverage(coverages, min(days), max(days)):
        raise AdjustmentUnavailable("INCOMPLETE_ACTION_COVERAGE")
    groups = defaultdict(list)
    for action in latest_actions(session, asset.id, action_source, mode, as_of):
        day = action.effective_at.astimezone(tz).date()
        if min(days) < day <= max(days) and action.effective_at <= snapshots[-1].close_time:
            groups[day].append(action)
    index = dict(zip(days, snapshots))
    factors = {}
    try:
        with localcontext() as context:
            context.prec = 50
            for day, events in sorted(groups.items()):
                split_factor = Decimal(1)
                dividend = Decimal(0)
                for event in sorted(events, key=lambda e: e.native_id):
                    if day not in schedule or event.effective_at != schedule[day][0]:
                        raise AdjustmentUnavailable("ACTION_SESSION_MISMATCH")
                    if event.action_type == "split":
                        split_factor *= checked(Decimal(event.details["old_shares"])) / checked(Decimal(event.details["new_shares"]))
                    elif event.action_type == "cash_dividend" and adjustment == "split_dividend_adjusted":
                        if event.details["currency"] != asset.currency:
                            raise AdjustmentUnavailable("DIVIDEND_CURRENCY_MISMATCH")
                        dividend += checked(Decimal(event.details["amount"]))
                    elif event.action_type != "cash_dividend":
                        raise AdjustmentUnavailable("UNSUPPORTED_ACTION")
                split_factor = checked(split_factor)
                price_factor = split_factor
                if dividend:
                    try:
                        previous = previous_session(day, asset.calendar_id)
                    except CalendarUnavailable as error:
                        raise AdjustmentUnavailable(str(error)) from None
                    basis = index.get(previous)
                    if basis is None:
                        raise AdjustmentUnavailable("PREVIOUS_SESSION_CLOSE_MISSING")
                    # Cash distribution is per post-split share; same-day splits
                    # normalize the prior close before computing the dividend factor.
                    reference = checked(basis.close * split_factor)
                    dividend_factor = Decimal(1) - dividend / reference
                    if dividend_factor <= 0:
                        raise AdjustmentUnavailable("NONPOSITIVE_DIVIDEND_FACTOR")
                    price_factor *= dividend_factor
                factors[day] = (checked(price_factor), split_factor)
            adjusted = []
            for day, bar in zip(days, snapshots):
                price_factor = volume_factor = Decimal(1)
                for event_day, (price, split) in factors.items():
                    if day < event_day:
                        price_factor = checked(price_factor * price)
                        volume_factor = checked(volume_factor / split)
                adjusted.append(replace(bar, adjustment=adjustment, open=checked(bar.open * price_factor), high=checked(bar.high * price_factor), low=checked(bar.low * price_factor), close=checked(bar.close * price_factor), volume=checked(bar.volume * volume_factor, allow_zero=True)))
            return adjusted
    except (DecimalException, KeyError, ValueError) as error:
        if isinstance(error, AdjustmentUnavailable):
            raise
        raise AdjustmentUnavailable("INVALID_ACTION_NUMERICS") from None
