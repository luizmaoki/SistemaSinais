from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import httpx

from app.adapters.base import Capability, NormalizedEvent, NormalizedQuery, ProviderHealth, RawProviderEvent
from app.database import utcnow
from app.errors import ProviderError


class CoinbaseAdapter:
    """Daily, closed candles only. Personal-use opt-in is required; no AI/redistribution."""

    provider_id = "coinbase"
    products = {"BTC-USD", "ETH-USD", "SOL-USD"}

    def __init__(self, personal_use_accepted: bool, timeout: float = 20.0, transport=None):
        self.personal_use_accepted = personal_use_accepted
        self.timeout = timeout
        self.transport = transport

    async def health(self) -> ProviderHealth:
        return ProviderHealth(self.provider_id, "READY" if self.personal_use_accepted else "NOT_CONFIGURED")

    async def capabilities(self) -> list[Capability]:
        return [Capability("daily_candles", ("crypto",), "END_OF_DAY")]

    async def fetch(self, query: NormalizedQuery) -> list[RawProviderEvent]:
        if not self.personal_use_accepted:
            raise ProviderError(
                "LICENSE_ACCEPTANCE_REQUIRED",
                self.provider_id,
                "Coinbase requer aceite local dos termos para uso pessoal; redistribuição e IA bloqueadas.",
            )
        if query.symbol not in self.products:
            raise ProviderError("DATASET_UNAVAILABLE", self.provider_id, "Produto não coberto pelo adapter.")
        now = utcnow()
        end = min(query.end or now, now).astimezone(timezone.utc)
        start = (query.start or (end - timedelta(days=180))).astimezone(timezone.utc)
        if start >= end or end - start > timedelta(days=299):
            raise ProviderError("INVALID_RANGE", self.provider_id, "Intervalo deve ter entre 1 e 299 dias.")
        url = f"https://api.exchange.coinbase.com/products/{query.symbol}/candles"
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, transport=self.transport, follow_redirects=False
            ) as client:
                response = await client.get(
                    url, params={"granularity": 86400, "start": start.isoformat(), "end": end.isoformat()}
                )
                response.raise_for_status()
                rows = response.json()
            if not isinstance(rows, list) or len(rows) > 300:
                raise ValueError("Invalid candles response")
            events = []
            for row in rows:
                if not isinstance(row, list) or len(row) != 6:
                    raise ValueError("Invalid candle")
                stamp = datetime.fromtimestamp(int(row[0]), timezone.utc)
                if start <= stamp < end and stamp + timedelta(days=1) <= now:
                    events.append(RawProviderEvent(str(int(row[0])), {"product": query.symbol, "candle": row}, now))
            return events
        except (httpx.HTTPError, ValueError, TypeError, OverflowError):
            raise ProviderError(
                "UPSTREAM_HTTP_ERROR",
                self.provider_id,
                "Coinbase indisponível ou resposta inválida; dados demo não substituem a fonte.",
            ) from None

    async def normalize(self, events: list[RawProviderEvent]) -> list[NormalizedEvent]:
        result = []
        seen = set()
        for event in events:
            try:
                stamp, low, high, opened, close, volume = event.payload["candle"]
                timestamp = datetime.fromtimestamp(int(stamp), timezone.utc)
                end = timestamp + timedelta(days=1)
                if end > event.fetched_at or stamp in seen:
                    continue
                seen.add(stamp)
                prices = [Decimal(str(value)) for value in (opened, high, low, close, volume)]
                op, hi, lo, cl, vol = prices
                if (
                    not all(value.is_finite() for value in prices)
                    or min(op, hi, lo, cl) <= 0
                    or vol < 0
                    or lo > min(op, cl)
                    or hi < max(op, cl)
                ):
                    raise ValueError("Invalid OHLCV")
                result.append(
                    NormalizedEvent(
                        native_id=event.native_id,
                        source_id=self.provider_id,
                        event_type="daily_bar",
                        published_at=end,
                        available_as_of=max(end, event.fetched_at),
                        ingested_at=event.fetched_at,
                        source_uri=f"https://api.exchange.coinbase.com/products/{event.payload['product']}/candles",
                        evidence_kind="OBSERVED",
                        data_mode="END_OF_DAY",
                        payload={
                            "event_time": timestamp,
                            "close_time": end,
                            "open": op,
                            "high": hi,
                            "low": lo,
                            "close": cl,
                            "volume": vol,
                        },
                    )
                )
            except (ValueError, KeyError, TypeError, InvalidOperation, OverflowError):
                raise ProviderError(
                    "INVALID_PROVIDER_PAYLOAD", self.provider_id, "Candle inválido; lote não persistido."
                ) from None
        return sorted(result, key=lambda item: item.payload["event_time"])
