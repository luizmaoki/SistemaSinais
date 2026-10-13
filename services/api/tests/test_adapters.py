import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import httpx
import pytest
from sqlalchemy import func, select
from app.adapters.base import NormalizedQuery, RawProviderEvent
from app.adapters.sec import SECAdapter
from app.adapters.coinbase import CoinbaseAdapter
from app.errors import ProviderError
from app.ingestion import persist_events
from app.models import Asset, Filing

from pathlib import Path
import json

PAYLOAD = json.loads(
    (Path(__file__).resolve().parents[3] / "fixtures/provider-contracts/contract_sec_synthetic.json").read_text(
        encoding="utf-8-sig"
    )
)


def run(awaitable):
    return asyncio.run(awaitable)


def test_sec_contract_timezone_original_url_and_no_lookahead(db):
    adapter = SECAdapter(
        "ContractTest contact@example.org",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=PAYLOAD)),
    )
    raw = run(adapter.fetch(NormalizedQuery("unused", "NVDA", "1045810")))
    events = run(adapter.normalize(raw))
    assert events[0].published_at.hour == 21
    assert events[0].source_uri == "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000001/report.htm"
    assert events[0].available_as_of >= events[0].ingested_at
    asset = db.scalar(select(Asset).where(Asset.symbol == "NVDA"))
    assert persist_events(db, asset, events) == 1
    assert persist_events(db, asset, events) == 0
    db.commit()
    changed = deepcopy(PAYLOAD)
    changed["filings"]["recent"]["primaryDocument"][0] = "correction.htm"
    updated = run(adapter.normalize(adapter._extract(changed, "0001045810", datetime.now(timezone.utc))))
    assert persist_events(db, asset, updated) == 1
    db.commit()
    assert db.scalar(select(func.count()).select_from(Filing)) == 2
    assert list(db.scalars(select(Filing.version).order_by(Filing.version))) == [1, 2]


def test_sec_absent_contact_blocks_before_network():
    with pytest.raises(ProviderError, match="SEC_USER_AGENT"):
        run(SECAdapter("").fetch(NormalizedQuery("x", "NVDA", "1045810")))


@pytest.mark.parametrize("status", [403, 404])
def test_sec_http_error_is_typed(status):
    adapter = SECAdapter(
        "ContractTest contact@example.org", transport=httpx.MockTransport(lambda req: httpx.Response(status))
    )
    with pytest.raises(ProviderError) as error:
        run(adapter.fetch(NormalizedQuery("x", "NVDA", "1045810")))
    assert error.value.code == "UPSTREAM_HTTP_ERROR"


def test_sec_invalid_arrays_and_paths():
    adapter = SECAdapter("ContractTest contact@example.org")
    broken = deepcopy(PAYLOAD)
    broken["filings"]["recent"]["form"] = []
    with pytest.raises(ValueError):
        adapter._extract(broken, "0001045810", datetime.now(timezone.utc))
    raw = adapter._extract(PAYLOAD, "0001045810", datetime.now(timezone.utc))
    raw[0].payload["primaryDocument"] = "../secret"
    with pytest.raises(ProviderError):
        run(adapter.normalize(raw))


def test_coinbase_requires_personal_acceptance_and_no_fake_fallback():
    with pytest.raises(ProviderError) as error:
        run(CoinbaseAdapter(False).fetch(NormalizedQuery("x", "BTC-USD")))
    assert error.value.code == "LICENSE_ACCEPTANCE_REQUIRED"


def test_coinbase_synthetic_contract_closed_deduplicated():
    fetched = datetime(2026, 1, 3, tzinfo=timezone.utc)
    stamp = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
    event = RawProviderEvent(str(stamp), {"product": "BTC-USD", "candle": [stamp, 90, 120, 100, 110, 500]}, fetched)
    current = RawProviderEvent(
        "current", {"product": "BTC-USD", "candle": [int(fetched.timestamp()), 90, 120, 100, 110, 500]}, fetched
    )
    rows = run(CoinbaseAdapter(True).normalize([event, event, current]))
    assert len(rows) == 1
    assert rows[0].payload["close"] == 110
    assert rows[0].data_mode == "END_OF_DAY"


@pytest.mark.parametrize("close", [0, float("nan"), 200])
def test_coinbase_invalid_ohlcv(close):
    event = RawProviderEvent(
        "x",
        {"product": "BTC-USD", "candle": [1767225600, 90, 120, 100, close, 500]},
        datetime(2026, 1, 3, tzinfo=timezone.utc),
    )
    with pytest.raises(ProviderError):
        run(CoinbaseAdapter(True).normalize([event]))
