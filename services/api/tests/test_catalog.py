"""Identity invariants: imports never infer a listing from its ticker or issuer."""
from copy import deepcopy
from datetime import date, datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.catalog import ImportRejected, import_catalog, resolve_identifiers
from app.models import Asset, AssetIdentifier, CatalogImport, MarketBar

UTC = timezone.utc
KNOWN = datetime(2026, 3, 1, tzinfo=UTC)
FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "catalog"


def instrument(symbol="TEST", venue="NYSE", **extra):
    return {
        "id": str(uuid4()), "symbol": symbol, "display_name": symbol,
        "asset_type": "equity", "currency": "USD", "venue": venue,
        "timezone": "America/New_York", "calendar_id": "XNYS",
        "identifiers": [{"native_id": "ticker", "version": 1, "identifier_type": "ticker", "value": symbol, "venue": venue}],
        **extra,
    }


def document(*assets, **extra):
    return {"source_id": "demo_catalog_test", "source_uri": "fixture:test_catalog", "available_as_of": "2026-02-01T00:00:00Z", "metadata_status": "DEMO", "assets": list(assets), **extra}


def apply(db, payload, ingested=KNOWN):
    return import_catalog(db, payload, _demo_ingested_at=ingested)


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def resolve(db, kind, value, day=date(2026, 2, 15), known=KNOWN, **scope):
    return resolve_identifiers(db, kind, value, day, known, **scope)


def test_verified_share_classes_remain_separate_and_no_prices(db, client):
    bars_before = count(db, MarketBar)
    for filename in ("berkshire_verified.json", "alphabet_verified.json"):
        payload = json.loads((FIXTURES / filename).read_text(encoding="utf-8"))
        first = import_catalog(db, payload)
        assert first["inserted"] == 2
        assert import_catalog(db, payload)["status"] == "UNCHANGED"
    db.commit()
    assert count(db, MarketBar) == bars_before
    response = client.get("/api/v1/assets/resolve", params={"identifier_type": "cik", "value": "1067983"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "AMBIGUOUS_IDENTIFIER"
    assert len(response.json()["detail"]["candidate_ids"]) == 2
    response = client.get("/api/v1/assets/resolve", params={"identifier_type": "ticker", "value": "brk.a", "venue": "NYSE"})
    assert response.status_code == 200
    row = response.json()["asset"]
    assert row["symbol"] == "BRK.A" and row["latest_price"] is None
    assert row["metadata_status"] == "VERIFIED"
    assert row["metadata_ingested_at"] >= row["metadata_available_as_of"]
    assert row["cik"] == "0001067983"
    assert len(client.get("/api/v1/assets", params={"q": "0001067983"}).json()["items"]) == 2


def test_alias_validity_reuse_and_knowledge_time(db):
    first = instrument("OLD")
    early = document(first, available_as_of="2026-01-01T00:00:00Z")
    apply(db, early, datetime(2026, 1, 2, tzinfo=UTC))
    corrected = deepcopy(first)
    corrected["symbol"] = "NEW"
    corrected["identifiers"][0].update(version=2, effective_to="2026-02-01")
    corrected["identifiers"].append({"native_id": "new-ticker", "version": 1, "identifier_type": "ticker", "value": "NEW", "venue": "NYSE", "effective_from": "2026-02-01"})
    second = instrument("REUSED")
    second["identifiers"][0].update(value="OLD", effective_from="2026-02-01")
    apply(db, document(corrected, second), datetime(2026, 2, 2, tzinfo=UTC))
    assert resolve(db, "ticker", "OLD", day=date(2026, 1, 31)) == [first["id"]]
    assert resolve(db, "ticker", "OLD", day=date(2026, 2, 1)) == [second["id"]]
    # The future correction was published Feb 1 but only ingested Feb 2.
    assert resolve(db, "ticker", "OLD", known=datetime(2026, 2, 1, 12, tzinfo=UTC)) == [first["id"]]
    assert resolve(db, "ticker", "NEW") == [first["id"]]
    assert count(db, AssetIdentifier) >= 4


def test_same_ticker_different_venues_requires_disambiguation(db, client):
    first, second = instrument("SHARED"), instrument("SHARED", venue="NASDAQ")
    apply(db, document(first, second))
    db.commit()
    response = client.get("/api/v1/assets/resolve", params={"identifier_type": "ticker", "value": "SHARED"})
    assert response.status_code == 409
    assert response.json()["detail"]["candidate_ids"] == sorted([first["id"], second["id"]])
    assert resolve(db, "ticker", "SHARED", venue="NASDAQ") == [second["id"]]


def test_catalog_key_collision_rejects_entire_document(db):
    original = instrument("DUP")
    apply(db, document(original))
    before = count(db, Asset), count(db, CatalogImport)
    new = instrument("SHOULD-NOT-EXIST")
    duplicate = instrument("DUP")
    with pytest.raises(ImportRejected, match="KEY_COLLISION"):
        apply(db, document(new, duplicate))
    assert (count(db, Asset), count(db, CatalogImport)) == before
    assert db.get(Asset, new["id"]) is None
    assert db.get(Asset, original["id"]).symbol == "DUP"


def test_bad_identifier_revision_rolls_back_other_metadata(db):
    item = instrument("IMMUTABLE")
    apply(db, document(item))
    item["display_name"] = "Must roll back"
    item["identifiers"][0]["value"] = "FORGED"
    before = count(db, CatalogImport)
    with pytest.raises(ImportRejected, match="revision is immutable"):
        apply(db, document(item))
    db.expire_all()
    assert db.get(Asset, item["id"]).display_name == "IMMUTABLE"
    assert count(db, CatalogImport) == before
    assert resolve(db, "ticker", "FORGED") == []


@pytest.mark.parametrize("changes", [
    {"currency": ""}, {"timezone": "Unknown/Mars"},
    {"venue": "OTC", "calendar_id": "XNYS"},
    {"asset_type": "future", "instrument_kind": "contract", "calendar_id": None},
    {"asset_type": "future", "instrument_kind": "root", "expiration": "2026-12-01", "calendar_id": None},
    {"asset_type": "option", "instrument_kind": "contract", "calendar_id": None},
    {"asset_type": "crypto", "timezone": "UTC", "calendar_id": "24/7", "contract_address": "0x123"},
    {"strike": "-1"}, {"contract_multiplier": "NaN"},
])
def test_invalid_metadata_cannot_partially_import(db, changes):
    valid, invalid = instrument("VALID-FIRST"), instrument("INVALID", **changes)
    before = count(db, Asset)
    with pytest.raises((ValidationError, ImportRejected)):
        apply(db, document(valid, invalid))
    assert count(db, Asset) == before


def test_valid_dated_derivative_and_underlying_cycle(db):
    underlying = instrument("UNDERLYING")
    future = instrument("FUT-DEC26", venue="CME", asset_type="future", instrument_kind="contract", calendar_id=None, expiration="2026-12-18", underlying_asset_id=underlying["id"], contract_multiplier="50")
    apply(db, document(future, underlying))
    assert db.get(Asset, future["id"]).underlying_asset_id == underlying["id"]
    assert db.scalar(select(Asset).where(Asset.symbol == "ES")).instrument_kind == "root"
    assert db.scalar(select(Asset).where(Asset.symbol == "ES")).expiration is None
    bad = instrument("SELF", venue="CME", asset_type="future", instrument_kind="contract", calendar_id=None, expiration="2026-12-18", contract_multiplier="50")
    bad["underlying_asset_id"] = bad["id"]
    with pytest.raises(ImportRejected, match="self-referential"):
        apply(db, document(bad))


def test_contract_address_is_scoped_by_chain(db):
    assets = []
    for number, chain in enumerate(("eip155:1", "eip155:137")):
        item = instrument(f"TOKEN{number}", venue="Onchain", asset_type="crypto", timezone="UTC", calendar_id="24/7", chain_id=chain, contract_address="0xabc")
        item["identifiers"] = [{"native_id": "address", "identifier_type": "contract_address", "value": "0xabc", "chain_id": chain}]
        assets.append(item)
    apply(db, document(*assets))
    assert resolve(db, "contract_address", "0xabc") == sorted(a["id"] for a in assets)
    assert resolve(db, "contract_address", "0xabc", chain_id="eip155:1") == [assets[0]["id"]]


@pytest.mark.parametrize("uri", ["https://user:secret@example.com/data", "https://example.com/data?api_key=secret", "https://example.com/data#token", "javascript:alert(1)"])
def test_source_uri_rejects_credentials_and_unsafe_schemes(db, uri):
    with pytest.raises(ValidationError):
        apply(db, document(instrument(), source_uri=uri))


def test_real_ingestion_time_cannot_be_backdated_by_payload(db):
    payload = document(instrument(), source_id="verified_source", source_uri="https://example.com/authorized", metadata_status="VERIFIED")
    payload["ingested_at"] = "2000-01-01T00:00:00Z"
    with pytest.raises(ValidationError):
        import_catalog(db, payload)
    payload.pop("ingested_at")
    with pytest.raises(ImportRejected, match="Only built-in DEMO"):
        import_catalog(db, payload, _demo_ingested_at=KNOWN)


@pytest.mark.parametrize("field,value", [("currency", "EUR"), ("timezone", "UTC"), ("calendar_id", None)])
def test_units_and_calendars_of_existing_prices_cannot_change(db, field, value):
    row = db.scalar(select(Asset).where(Asset.symbol == "SPLIT-DEMO"))
    payload = json.loads((FIXTURES / "demo_catalog.json").read_text(encoding="utf-8"))
    payload["assets"][0][field] = value
    if field == "timezone":
        payload["assets"][0]["calendar_id"] = None
    with pytest.raises((ImportRejected, ValidationError)):
        apply(db, payload, datetime(2026, 10, 9, tzinfo=UTC))
    assert row.currency == "USD" and row.timezone == "America/New_York" and row.calendar_id == "XNYS"
