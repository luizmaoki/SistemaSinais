from datetime import date
from app.calendars import session_schedule


def test_calendar_dst_holiday_and_half_day(client):
    asset = client.get("/api/v1/assets?q=NVDA").json()["items"][0]
    def calendar(day):
        response = client.get(f"/api/v1/assets/{asset['id']}/calendar", params={"from": day, "to": day})
        assert response.status_code == 200
        return response.json()
    assert calendar("2026-01-05")["items"][0]["close_at"].startswith("2026-01-05T21:00")
    assert calendar("2026-07-06")["items"][0]["close_at"].startswith("2026-07-06T20:00")
    assert calendar("2026-07-03")["items"] == []
    half = calendar("2026-11-27")["items"][0]
    assert half["open_at"].startswith("2026-11-27T14:30")
    assert half["close_at"].startswith("2026-11-27T18:00")
    assert calendar("2036-01-01")["status"] == "UNAVAILABLE"
    assert client.get(f"/api/v1/assets/{asset['id']}/calendar", params={"from": "2026-01-01", "to": "2027-01-02"}).status_code == 422


def test_crypto_247_and_unsupported_venues_do_not_fall_back(client):
    crypto = client.get("/api/v1/assets?q=BTC-USD").json()["items"][0]
    response = client.get(f"/api/v1/assets/{crypto['id']}/calendar", params={"from": "2026-07-04", "to": "2026-07-05"}).json()
    assert response["calendar_id"] == "24/7" and response["timezone"] == "UTC"
    assert len(response["items"]) == 2
    assert response["items"][0]["close_at"].startswith("2026-07-05T00:00")
    for symbol in ("ES", "EUR-USD", "XAU-USD"):
        asset = next(a for a in client.get("/api/v1/assets", params={"q": symbol}).json()["items"] if a["symbol"] == symbol)
        response = client.get(f"/api/v1/assets/{asset['id']}/calendar", params={"from": "2026-01-05", "to": "2026-01-06"}).json()
        assert response["status"] == "UNAVAILABLE" and response["items"] == []
        assert client.get(f"/api/v1/assets/{asset['id']}/metrics").json()["calculation_status"] == "UNAVAILABLE"
        assert client.get(f"/api/v1/assets/{asset['id']}/returns").json()["calculation_status"] == "UNAVAILABLE"


def test_demonstration_bars_match_assigned_calendar(db):
    from sqlalchemy import select
    from app.models import Asset, MarketBar
    for asset in db.scalars(select(Asset).where(Asset.calendar_id.is_not(None))):
        bars = list(db.scalars(select(MarketBar).where(MarketBar.asset_id == asset.id)))
        if not bars:
            continue
        expected = session_schedule(date(2025, 12, 1), date(2026, 10, 31), asset.calendar_id)
        from zoneinfo import ZoneInfo
        for bar in bars:
            day = bar.event_time.astimezone(ZoneInfo(asset.timezone)).date()
            assert day in expected and bar.close_time == expected[day][1]
