from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5
from sqlalchemy import select
from app.auth import DEMO_TENANT_ID, DEMO_USER_ID
from app.calculations import session_closes
from app.models import Asset, MacroEvent, MarketBar, ProviderState, Tenant, User, Watchlist

CATALOG = [
    ("NVDA", "NVIDIA", "equity", "NASDAQ", "0001045810"),
    ("AAPL", "Apple", "equity", "NASDAQ", "0000320193"),
    ("MSFT", "Microsoft", "equity", "NASDAQ", "0000789019"),
    ("SPY", "SPDR S&P 500 ETF", "etf", "NYSE ARCA", None),
    ("QQQ", "Invesco QQQ", "etf", "NASDAQ", None),
    ("BTC-USD", "Bitcoin / dólar", "crypto", "Coinbase", None),
    ("ETH-USD", "Ethereum / dólar", "crypto", "Coinbase", None),
    ("SOL-USD", "Solana / dólar", "crypto", "Coinbase", None),
    ("SPX", "S&P 500 (índice)", "index", "S&P DJI", None),
    ("NU", "Nu Holdings ADR", "adr", "NYSE", "0001691493"),
    ("O", "Realty Income", "reit", "NYSE", None),
    ("EUR-USD", "Euro / dólar", "forex", "OTC", None),
    ("XAU-USD", "Ouro spot (catálogo)", "commodity", "OTC", None),
    ("UST-10Y", "Treasury 10 anos (catálogo)", "bond", "OTC", None),
    ("ES", "E-mini S&P 500 (raiz de futuros)", "future", "CME", None),
]


def stable_id(value):
    return str(uuid5(NAMESPACE_URL, "capital-intelligence/" + value))


def seed(session):
    if not session.get(Tenant, DEMO_TENANT_ID):
        session.add(Tenant(id=DEMO_TENANT_ID, name="Workspace demo local"))
        session.flush()
    if not session.get(User, DEMO_USER_ID):
        session.add(User(id=DEMO_USER_ID, tenant_id=DEMO_TENANT_ID, name="Usuário demo", role="owner"))
        session.flush()
    for index, (symbol, name, kind, venue, cik) in enumerate(CATALOG):
        asset_id = stable_id(venue + "/" + symbol)
        if not session.get(Asset, asset_id):
            session.add(
                Asset(
                    id=asset_id,
                    symbol=symbol,
                    display_name=name,
                    asset_type=kind,
                    venue=venue,
                    primary_exchange=venue,
                    currency="USD",
                    timezone="UTC" if kind == "crypto" else "America/New_York",
                    cik=cik,
                )
            )
            session.flush()
        # Only clearly identified synthetic equity/ETF/crypto series, fixed dates for reproducibility.
        if kind not in {"equity", "etf", "crypto"}:
            continue
        if session.scalar(
            select(MarketBar.id).where(MarketBar.asset_id == asset_id, MarketBar.source_id == "demo").limit(1)
        ):
            continue
        closes = session_closes(datetime(2026, 1, 1).date(), datetime(2026, 10, 7).date(), kind)
        base = [120, 180, 400, 520, 470, 60000, 3000, 130][index]
        for n, (day, close_at) in enumerate(closes.items()):
            value = Decimal(str(round(base * (1 + n * 0.0007 + 0.02 * ((n % 17) - 8) / 8), 4)))
            event_time = (
                datetime.combine(day, datetime.min.time(), timezone.utc)
                if kind == "crypto"
                else close_at - timedelta(hours=1)
            )
            session.add(
                MarketBar(
                    id=stable_id(f"demo/{asset_id}/{day}"),
                    asset_id=asset_id,
                    source_id="demo",
                    event_time=event_time,
                    close_time=close_at,
                    open=value * Decimal(".997"),
                    high=value * Decimal("1.012"),
                    low=value * Decimal(".988"),
                    close=value,
                    volume=Decimal(1000000 + n * 713),
                    data_mode="DEMO",
                    evidence_kind="SIMULATED",
                    adjustment="unadjusted",
                    available_as_of=close_at,
                    source_uri="fixture:demo_daily_bars_v1",
                    ingested_at=datetime(2026, 10, 8, tzinfo=timezone.utc),
                )
            )
    if not session.get(ProviderState, "demo"):
        session.add(ProviderState(id="demo", status="DEMO", records_ingested=0))
    for i, title in enumerate(
        ["CPI — evento demonstrativo", "Payroll — evento demonstrativo", "FOMC — evento demonstrativo"]
    ):
        event_id = stable_id("demo/macro/" + str(i))
        if not session.get(MacroEvent, event_id):
            session.add(
                MacroEvent(
                    id=event_id,
                    title=title,
                    country="US",
                    importance="high",
                    scheduled_at=datetime(2026, 10, 8 + i, 12, 30, tzinfo=timezone.utc),
                    actual=None,
                    consensus=None,
                    previous=None,
                    revised_previous=None,
                    released_at=None,
                    unit="%" if i != 1 else "mil empregos",
                    data_mode="DEMO",
                    source_id="demo",
                    evidence_kind="SIMULATED",
                )
            )
    if not session.scalar(select(Watchlist.id).where(Watchlist.user_id == DEMO_USER_ID)):
        session.add(Watchlist(tenant_id=DEMO_TENANT_ID, user_id=DEMO_USER_ID, name="Minha watchlist"))
    session.commit()
