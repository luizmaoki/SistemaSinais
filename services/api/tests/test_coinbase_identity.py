"""Coinbase identity checks use an offline transport; no external request is made."""
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app import ingestion
from app.adapters.base import NormalizedQuery, RawProviderEvent
from app.adapters.coinbase import CoinbaseAdapter
from app.config import Settings
from app.errors import ProviderError
from app.models import Asset, MarketBar

UTC = timezone.utc
NOW = datetime(2026, 10, 10, tzinfo=UTC)
STAMP = int(datetime(2026, 10, 9, tzinfo=UTC).timestamp())


def configure_offline_sync(db, monkeypatch):
    seen = []
    def handle(request):
        seen.append(request.url.path)
        return httpx.Response(200, json=[[STAMP, 90, 110, 100, 100, 500]])
    class OfflineCoinbase(CoinbaseAdapter):
        def __init__(self, personal_use_accepted, timeout):
            super().__init__(personal_use_accepted, timeout, transport=httpx.MockTransport(handle))
    monkeypatch.setattr(ingestion, "CoinbaseAdapter", OfflineCoinbase)
    monkeypatch.setattr(ingestion, "SessionLocal", sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    monkeypatch.setattr(ingestion, "get_settings", lambda: Settings(APP_ENV="test", auth_mode="demo", demo_mode=True, coinbase_personal_use_accepted=True))
    monkeypatch.setattr("app.adapters.coinbase.utcnow", lambda: NOW)
    return seen


def impostor(venue="Kraken", currency="USD"):
    return Asset(id=str(uuid4()), symbol="BTC-USD", display_name="Separate listing", asset_type="crypto", venue=venue, currency=currency, timezone="UTC", calendar_id="24/7", instrument_kind="spot")


@pytest.mark.parametrize("currency", ["USD", "EUR"])
def test_sync_skips_same_symbol_on_other_venue(db, monkeypatch, currency):
    other = impostor(currency=currency)
    db.add(other)
    db.commit()
    seen = configure_offline_sync(db, monkeypatch)
    result = asyncio.run(ingestion.sync_provider("coinbase"))
    assert result["status"] == "HEALTHY" and result["inserted"] == 3
    assert len(seen) == 3 and seen.count("/products/BTC-USD/candles") == 1
    assert db.scalar(select(func.count()).select_from(MarketBar).where(MarketBar.asset_id == other.id)) == 0
    rows = list(db.scalars(select(MarketBar).where(MarketBar.source_id == "coinbase")))
    assert {r.asset_id for r in rows} == set(CoinbaseAdapter.listings)
    assert {r.currency for r in rows} == {"USD"}


def test_sync_rejects_mapped_uuid_with_incompatible_currency(db, monkeypatch):
    asset = db.scalar(select(Asset).where(Asset.symbol == "BTC-USD"))
    asset.currency = "EUR"
    db.commit()
    seen = configure_offline_sync(db, monkeypatch)
    result = asyncio.run(ingestion.sync_provider("coinbase"))
    assert result["status"] == "HEALTHY" and result["inserted"] == 2
    assert "/products/BTC-USD/candles" not in seen
    assert db.scalar(select(func.count()).select_from(MarketBar).where(MarketBar.asset_id == asset.id, MarketBar.source_id == "coinbase")) == 0


def test_venue_and_symbol_alone_never_create_a_mapping(db, monkeypatch):
    original = db.scalar(select(Asset).where(Asset.symbol == "BTC-USD"))
    original.symbol = "LEGACY-BTC"
    db.flush()
    other = impostor(venue="Coinbase")
    db.add(other)
    db.commit()
    seen = configure_offline_sync(db, monkeypatch)
    result = asyncio.run(ingestion.sync_provider("coinbase"))
    assert result["inserted"] == 2 and "/products/BTC-USD/candles" not in seen
    assert db.scalar(select(func.count()).select_from(MarketBar).where(MarketBar.asset_id == other.id)) == 0


def test_missing_mapping_is_unavailable_without_network(db, monkeypatch):
    for asset in db.scalars(select(Asset).where(Asset.asset_type == "crypto")):
        asset.currency = "EUR"
    db.commit()
    seen = configure_offline_sync(db, monkeypatch)
    result = asyncio.run(ingestion.sync_provider("coinbase"))
    assert result["status"] == "UNAVAILABLE" and result["error_code"] == "ASSET_MAPPING_UNAVAILABLE"
    assert seen == []


def normalized_bitcoin():
    raw = RawProviderEvent(str(STAMP), {"product": "BTC-USD", "candle": [STAMP, 90, 110, 100, 100, 500]}, NOW)
    return asyncio.run(CoinbaseAdapter(True).normalize([raw]))[0]


def test_persistence_independently_checks_uuid_product_and_source_currency(db):
    asset = db.scalar(select(Asset).where(Asset.symbol == "BTC-USD"))
    other = impostor()
    db.add(other)
    db.flush()
    event = normalized_bitcoin()
    assert event.payload["currency"] == "USD" and event.payload["provider_asset_id"] == asset.id
    with pytest.raises(ProviderError) as error:
        ingestion.persist_events(db, other, [event])
    assert error.value.code == "PROVIDER_IDENTITY_MISMATCH"
    for currency in (None, "EUR"):
        wrong = replace(event, payload={**event.payload, "currency": currency})
        with pytest.raises(ProviderError) as error:
            ingestion.persist_events(db, asset, [wrong])
        assert error.value.code == "PROVIDER_CURRENCY_MISMATCH"
    assert db.scalar(select(func.count()).select_from(MarketBar).where(MarketBar.source_id == "coinbase")) == 0
    assert ingestion.persist_events(db, asset, [event]) == 1
    assert db.scalar(select(MarketBar.currency).where(MarketBar.source_id == "coinbase")) == "USD"


def test_adapter_rejects_unmapped_uuid_before_transport():
    seen = []
    adapter = CoinbaseAdapter(True, transport=httpx.MockTransport(lambda request: seen.append(request)))
    with pytest.raises(ProviderError) as error:
        asyncio.run(adapter.fetch(NormalizedQuery(str(uuid4()), "BTC-USD")))
    assert error.value.code == "DATASET_UNAVAILABLE" and seen == []
