"""Smoke do stack local. Não chama fornecedores externos nem executa ordens."""

import argparse
from datetime import datetime, timezone
import json
import os
from docker_utils import add_compose_arguments, compose_from_args, run_compose
import time
import urllib.error
import urllib.request

API = os.getenv("SMOKE_API_URL", "http://localhost:8000") + "/api/v1"
WEB = os.getenv("SMOKE_WEB_URL", "http://localhost:3000")


def request(path, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        API + path, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.load(response)


def verify_catalog_integrity(asset_id):
    calendar = request(f"/assets/{asset_id}/calendar?from=2026-11-26&to=2026-11-27")
    assert calendar["status"] == "AVAILABLE" and calendar["calendar_id"] == "XNYS"
    assert len(calendar["items"]) == 1 and calendar["items"][0]["session_date"] == "2026-11-27"
    close_at = datetime.fromisoformat(calendar["items"][0]["close_at"].replace("Z", "+00:00"))
    assert close_at == datetime(2026, 11, 27, 18, tzinfo=timezone.utc), "Meia sessão NYSE incorreta"
    future = next(row for row in request("/assets?q=ES")["items"] if row["symbol"] == "ES")
    unavailable = request(f"/assets/{future['id']}/calendar?from=2026-11-26&to=2026-11-27")
    assert unavailable["status"] == "UNAVAILABLE" and not unavailable["items"], "Futuro herdou calendário NYSE"
    matches = request("/assets?q=SPLIT-DEMO")["items"]
    assert len(matches) == 1 and matches[0]["data_mode"] == "DEMO"
    demo_id = matches[0]["id"]
    query = "source=demo&corporate_action_source=demo&as_of=2026-10-09T12:00:00Z&from=2026-01-30T00:00:00Z&to=2026-02-04T00:00:00Z"
    raw_path = f"/assets/{demo_id}/bars?{query}&adjustment=unadjusted"
    raw = request(raw_path)
    adjusted = request(f"/assets/{demo_id}/bars?{query}&adjustment=split_dividend_adjusted")
    assert [row["close"] for row in raw["items"]] == [100, 50, 49]
    assert [row["close"] for row in adjusted["items"]] == [49, 49, 49]
    assert [row["volume"] for row in adjusted["items"]] == [2000, 2000, 2000]
    assert adjusted["adjustment"] == "split_dividend_adjusted" and adjusted["data_mode"] == "DEMO"
    assert adjusted["currency"] == "USD" and adjusted["action_source_id"] == "demo"
    assert [row["close"] for row in request(raw_path)["items"]] == [100, 50, 49], "Ajuste alterou barras originais"
    print("CATALOG INTEGRITY OK: calendars, raw preservation, split and dividend factors")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_compose_arguments(parser)
    compose = compose_from_args(parser.parse_args())
    for attempt in range(60):
        try:
            request("/ready")
            break
        except (urllib.error.URLError, TimeoutError):
            if attempt == 59:
                raise
            time.sleep(2)
    request("/health")
    assets = request("/assets?q=NVDA")["items"]
    assert any(a["symbol"] == "NVDA" for a in assets), "NVDA ausente"
    asset_id = next(a["id"] for a in assets if a["symbol"] == "NVDA")
    btc = request("/assets?q=BTC")["items"]
    assert btc, "BTC ausente"
    bars = request(f"/assets/{asset_id}/bars")
    assert bars["items"] and bars["data_mode"] == "DEMO", "Série demo não identificada"
    returns = request(f"/assets/{asset_id}/returns")
    assert returns["items"], "Retornos ausentes"
    verify_catalog_integrity(asset_id)
    assert request("/providers")["items"], "Registry de fontes vazio"
    assert request("/macro/calendar")["items"], "Calendário demo vazio"
    request("/institutional/filings")
    request("/news")
    watchlist = request("/watchlists", {"name": "Smoke local"})
    watchlist_id = watchlist.get("id") or watchlist.get("item", {}).get("id")
    assert watchlist_id, "POST watchlist não retornou id"
    request(f"/watchlists/{watchlist_id}/assets", {"asset_id": asset_id})
    rule = request(
        "/alert-rules", {"asset_id": asset_id, "threshold": 1, "direction": "above"}
    )
    assert rule, "Regra não persistiu"
    request("/alerts")
    for attempt in range(30):
        try:
            with urllib.request.urlopen(WEB + "/dashboard", timeout=5) as response:
                assert response.status == 200
            break
        except (urllib.error.URLError, TimeoutError):
            if attempt == 29:
                raise
            time.sleep(2)
    task_code = "from app.tasks import alerts; result=alerts.delay().get(timeout=20); assert isinstance(result.get('created'),int); print('WORKER TASK OK')"
    run_compose(compose, "exec", "-T", "api", "python", "-c", task_code)
    with urllib.request.urlopen(WEB + "/dashboard", timeout=15) as response:
        assert response.status == 200, "Dashboard não abriu"
    print(
        "SMOKE OK: health, catálogo, séries, retornos, calendário, fontes, filings, watchlist, alerta e web"
    )


if __name__ == "__main__":
    main()

