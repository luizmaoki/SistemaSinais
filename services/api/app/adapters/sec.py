import asyncio
import hashlib
import json
import re
import threading
import time
from datetime import date, datetime, time as day_time, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from app.adapters.base import Capability, NormalizedEvent, NormalizedQuery, ProviderHealth, RawProviderEvent
from app.database import utcnow
from app.errors import ProviderError


class SECAdapter:
    provider_id = "sec_edgar"
    _rate_lock = threading.Lock()
    _next_request_at = 0.0

    def __init__(self, user_agent: str, timeout: float = 20.0, transport=None):
        self.user_agent = user_agent
        self.timeout = timeout
        self.transport = transport

    @property
    def configured(self) -> bool:
        return bool(re.search(r"\b[^\s@]+@[^\s@]+\.[A-Za-z]{2,}\b", self.user_agent)) and len(self.user_agent) >= 12

    async def health(self) -> ProviderHealth:
        return ProviderHealth(self.provider_id, "READY" if self.configured else "NOT_CONFIGURED")

    async def capabilities(self) -> list[Capability]:
        return [Capability("submissions", ("equity", "adr", "etf", "reit"), "END_OF_DAY")]

    async def _throttle(self) -> None:
        # One request per second in this process; the worker also holds a distributed provider lock.
        with self._rate_lock:
            now = time.monotonic()
            wait = max(0.0, type(self)._next_request_at - now)
            type(self)._next_request_at = max(now, type(self)._next_request_at) + 1.05
        if wait:
            await asyncio.sleep(wait)

    async def fetch(self, query: NormalizedQuery) -> list[RawProviderEvent]:
        if not self.configured:
            raise ProviderError(
                "PROVIDER_NOT_CONFIGURED",
                self.provider_id,
                "Configure SEC_USER_AGENT com nome do aplicativo e contato válido.",
            )
        if not query.cik or not re.fullmatch(r"\d{1,10}", query.cik):
            raise ProviderError("INVALID_CIK", self.provider_id, "CIK inválido ou ausente.")
        url = f"https://data.sec.gov/submissions/CIK{query.cik.zfill(10)}.json"
        async with httpx.AsyncClient(
            timeout=self.timeout,
            transport=self.transport,
            follow_redirects=False,
            headers={"User-Agent": self.user_agent, "Accept": "application/json", "Accept-Encoding": "gzip, deflate"},
        ) as client:
            for attempt in range(3):
                await self._throttle()
                try:
                    response = await client.get(url)
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt < 2:
                            try:
                                delay = min(30.0, max(1.0, float(response.headers.get("Retry-After", 2**attempt))))
                            except ValueError:
                                delay = float(2**attempt)
                            await asyncio.sleep(delay)
                            continue
                    response.raise_for_status()
                    if len(response.content) > 8_000_000:
                        raise ProviderError(
                            "PAYLOAD_TOO_LARGE", self.provider_id, "Resposta SEC excedeu o limite local."
                        )
                    payload = response.json()
                    return self._extract(payload, query.cik.zfill(10), utcnow())
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                    if isinstance(exc, httpx.RequestError) and attempt < 2:
                        await asyncio.sleep(2**attempt)
                        continue
                    code = "UPSTREAM_HTTP_ERROR" if isinstance(exc, httpx.HTTPError) else "INVALID_PROVIDER_PAYLOAD"
                    raise ProviderError(
                        code, self.provider_id, "SEC indisponível ou resposta inválida; tente novamente depois."
                    ) from None
        raise ProviderError("UPSTREAM_HTTP_ERROR", self.provider_id, "SEC indisponível.")

    def _extract(self, payload: dict, cik: str, fetched_at: datetime) -> list[RawProviderEvent]:
        recent = payload["filings"]["recent"]
        required = ("accessionNumber", "filingDate", "form", "primaryDocument")
        lengths = [len(recent[key]) for key in required]
        if len(set(lengths)) != 1:
            raise ValueError("SEC required arrays must have equal lengths")
        events = []
        for i in range(min(lengths[0], 100)):
            row = {key: values[i] for key, values in recent.items() if isinstance(values, list) and i < len(values)}
            row["cik"] = cik
            row["company_name"] = str(payload.get("name", ""))[:200]
            events.append(RawProviderEvent(str(row["accessionNumber"]), row, fetched_at))
        return events

    async def normalize(self, events: list[RawProviderEvent]) -> list[NormalizedEvent]:
        normalized = []
        for event in events:
            row = event.payload
            try:
                accession = str(row["accessionNumber"])
                cik = str(row["cik"]).zfill(10)
                document = str(row["primaryDocument"])
                if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession) or not re.fullmatch(r"\d{10}", cik):
                    raise ValueError("Invalid accession")
                if not document or any(part in {"..", "."} for part in document.split("/")) or document.startswith("/"):
                    raise ValueError("Invalid document path")
                filing_date = date.fromisoformat(row["filingDate"])
                accepted = row.get("acceptanceDateTime")
                if accepted:
                    published = datetime.fromisoformat(accepted.replace("Z", "+00:00"))
                    if published.tzinfo is None:
                        published = published.replace(tzinfo=ZoneInfo("America/New_York"))
                    precision = "timestamp"
                else:
                    published = datetime.combine(filing_date, day_time.min, tzinfo=ZoneInfo("America/New_York"))
                    precision = "date"
                published = published.astimezone(timezone.utc)
                period = date.fromisoformat(row["reportDate"]) if row.get("reportDate") else None
                checksum = (
                    "sha256:"
                    + hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                )
                uri = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{quote(document, safe='/')}"
                normalized.append(
                    NormalizedEvent(
                        native_id=accession,
                        source_id=self.provider_id,
                        event_type="filing_published",
                        published_at=published,
                        available_as_of=max(published, event.fetched_at),
                        ingested_at=event.fetched_at,
                        source_uri=uri,
                        evidence_kind="REPORTED",
                        data_mode="END_OF_DAY",
                        payload={
                            "cik": cik,
                            "form": str(row["form"])[:30],
                            "filing_date": filing_date,
                            "filing_period_end": period,
                            "publication_precision": precision,
                            "raw_payload_checksum": checksum,
                            "metadata": row,
                        },
                    )
                )
            except (KeyError, TypeError, ValueError):
                raise ProviderError(
                    "INVALID_PROVIDER_PAYLOAD",
                    self.provider_id,
                    "Metadados de filing SEC inválidos; lote não persistido.",
                ) from None
        return normalized
