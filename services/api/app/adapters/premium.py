from app.adapters.base import Capability, NormalizedEvent, NormalizedQuery, ProviderHealth, RawProviderEvent
from app.errors import ProviderError


class UnconfiguredAdapter:
    """Typed extension point. Entitlements and a real implementation are required."""

    def __init__(self, provider_id: str, dataset: str, asset_classes: tuple[str, ...] = ()):
        self.provider_id = provider_id
        self.dataset = dataset
        self.asset_classes = asset_classes

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            self.provider_id, "NOT_CONFIGURED", "Fonte não configurada; credenciais e licença necessárias."
        )

    async def capabilities(self) -> list[Capability]:
        return [Capability(self.dataset, self.asset_classes, "NOT_CONFIGURED")]

    async def fetch(self, query: NormalizedQuery) -> list[RawProviderEvent]:
        raise ProviderError(
            "PROVIDER_NOT_CONFIGURED", self.provider_id, "Fonte não configurada; nenhum dado é simulado."
        )

    async def normalize(self, events: list[RawProviderEvent]) -> list[NormalizedEvent]:
        raise ProviderError(
            "PROVIDER_NOT_CONFIGURED", self.provider_id, "Normalização depende do contrato do fornecedor."
        )
