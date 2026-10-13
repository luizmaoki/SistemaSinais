# API

OpenAPI: http://localhost:8000/docs e /openapi.json. Prefixo /api/v1.

Health e readiness são públicos. O restante depende de identidade demo local nesta entrega. O proxy Next.js encaminha a API pelo servidor e limita rotas/métodos, tamanho do corpo, origem das mutações e tempo de espera.

Contrato base: listas em {items}; catálogo em {items,total,page,page_size}. Instrumentos usam id estável, symbol, display_name, asset_type, currency e venue. Séries retornam items e proveniência, com classificação de modo. Retornos mensais têm month, return_pct e partial.

Rotas iniciais: assets, assets/{id}, assets/{id}/bars, assets/{id}/returns, scanner, macro/calendar, news, institutional/filings, providers, coverage, watchlists, alert-rules e alerts. Implementação e limites completos constam do OpenAPI gerado.

Sem dataset contratado, retornar indisponibilidade tipada. Não preencher dados reais ausentes com DEMO. Consultas de filings retornam metadados de relatórios, não posições atuais. A execução de sync é CLI/job do backend, não uma ação de trading.
