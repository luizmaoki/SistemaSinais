"""Smoke do stack local. Não chama fornecedores externos nem executa ordens."""

import argparse
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

