from datetime import timedelta

from sqlalchemy.orm import Session

from app.adapters.sec import SECAdapter
from app.config import Settings
from app.database import utcnow
from app.models import ProviderState

REGISTRY = [
    {
        "id": "demo",
        "name": "Demonstração local",
        "dataset": "synthetic_daily_bars_and_calendar",
        "asset_classes": ["equity", "etf", "crypto", "index", "commodity", "forex", "bond"],
        "documentation_url": "/sources",
        "license_type": "SYNTHETIC",
        "allowed_redistribution": True,
        "commercial_use": True,
        "ai_processing_allowed": True,
        "rate_limit": "Local",
        "coverage_scope": "Fixture determinística; não representa mercado real",
    },
    {
        "id": "sec_edgar",
        "name": "SEC EDGAR",
        "dataset": "submissions",
        "asset_classes": ["equity", "adr", "etf", "reit"],
        "documentation_url": "https://www.sec.gov/search-filings/edgar-application-programming-interfaces",
        "license_type": "PUBLIC_OFFICIAL",
        "allowed_redistribution": None,
        "commercial_use": None,
        "ai_processing_allowed": None,
        "rate_limit": "1 req/s local (limite oficial: 10 req/s)",
        "coverage_scope": "Até 100 filings recentes por CIK do catálogo; metadados, sem extração de holdings",
    },
    {
        "id": "coinbase",
        "name": "Coinbase Exchange",
        "dataset": "daily_candles",
        "asset_classes": ["crypto"],
        "documentation_url": "https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles",
        "terms_url": "https://www.coinbase.com/legal/market_data",
        "license_type": "PERSONAL_USE_OPT_IN",
        "allowed_redistribution": False,
        "commercial_use": False,
        "ai_processing_allowed": False,
        "rate_limit": "300 candles/request; worker serial",
        "coverage_scope": "BTC-USD, ETH-USD, SOL-USD; somente candles diários fechados, venue Coinbase",
    },
    {
        "id": "massive",
        "name": "Massive",
        "dataset": "market_data",
        "asset_classes": ["equity", "option", "index"],
        "documentation_url": "https://massive.com/docs",
    },
    {
        "id": "trading_economics",
        "name": "Trading Economics",
        "dataset": "economic_calendar",
        "asset_classes": ["macro"],
        "documentation_url": "https://docs.tradingeconomics.com/economic_calendar/streaming/",
    },
    {
        "id": "benzinga",
        "name": "Benzinga",
        "dataset": "news",
        "asset_classes": ["equity"],
        "documentation_url": "https://docs.benzinga.com/",
    },
    {
        "id": "databento",
        "name": "Databento",
        "dataset": "orderbook",
        "asset_classes": ["future", "equity", "option"],
        "documentation_url": "https://databento.com/docs/knowledge-base",
    },
    {
        "id": "coinglass",
        "name": "CoinGlass",
        "dataset": "derivatives",
        "asset_classes": ["crypto"],
        "documentation_url": "https://docs.coinglass.com/",
    },
    {
        "id": "helius",
        "name": "Helius",
        "dataset": "solana_transactions",
        "asset_classes": ["crypto"],
        "documentation_url": "https://www.helius.dev/",
    },
    {
        "id": "aave",
        "name": "Aave",
        "dataset": "defi_positions",
        "asset_classes": ["crypto"],
        "documentation_url": "https://aave.com/docs",
    },
    {
        "id": "cftc",
        "name": "CFTC COT",
        "dataset": "cot_reports",
        "asset_classes": ["future"],
        "documentation_url": "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm",
    },
    {
        "id": "finra",
        "name": "FINRA",
        "dataset": "reported_trades",
        "asset_classes": ["bond", "equity"],
        "documentation_url": "https://www.finra.org/filing-reporting",
    },
    {
        "id": "occ",
        "name": "OCC",
        "dataset": "open_interest",
        "asset_classes": ["option"],
        "documentation_url": "https://www.theocc.com/market-data",
    },
    {
        "id": "arkham",
        "name": "Arkham",
        "dataset": "wallet_labels",
        "asset_classes": ["crypto"],
        "documentation_url": "https://arkm.com/docs",
    },
    {
        "id": "nansen",
        "name": "Nansen",
        "dataset": "wallet_intelligence",
        "asset_classes": ["crypto"],
        "documentation_url": "https://docs.nansen.ai/",
    },
    {
        "id": "llm",
        "name": "Análise por IA",
        "dataset": "evidence_analysis",
        "asset_classes": [],
        "documentation_url": "https://platform.openai.com/docs",
    },
]


def provider_rows(session: Session, settings: Settings) -> list[dict]:
    rows = []
    for entry in REGISTRY:
        row = {
            "provider_id": entry["id"],
            "license_type": "UNKNOWN",
            "allowed_redistribution": False,
            "commercial_use": False,
            "ai_processing_allowed": False,
            "allowed_retention": "Pending licence review",
            "rate_limit": "Não configurado",
            "coverage_scope": "Adapter tipado; dataset não habilitado",
            "last_checked_at": "2026-10-08",
            "depth_level": None,
            "data_delay_seconds": None,
            **entry,
        }
        state = session.get(ProviderState, entry["id"])
        configured = (
            entry["id"] == "demo"
            or (entry["id"] == "sec_edgar" and SECAdapter(settings.sec_user_agent).configured)
            or (entry["id"] == "coinbase" and settings.coinbase_personal_use_accepted)
        )
        status = "NOT_CONFIGURED"
        if configured:
            status = "DEMO" if entry["id"] == "demo" else (state.status if state else "PENDING")
            if (
                state
                and state.last_success_at
                and state.last_success_at < utcnow() - timedelta(hours=24)
                and status == "HEALTHY"
            ):
                status = "STALE"
        row.update(
            configured=configured,
            status=status,
            data_mode=("DEMO" if entry["id"] == "demo" else "END_OF_DAY" if status == "HEALTHY" else status),
            last_success_at=state.last_success_at if state else None,
            last_error=state.last_error if state else None,
            latency_ms=state.latency_ms if state else None,
            records_ingested=state.records_ingested if state else 0,
        )
        rows.append(row)
    return rows
