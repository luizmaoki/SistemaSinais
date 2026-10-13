# Fontes de dados

Verificação documental: 08/10/2026. Cobertura de catálogo não significa cobertura de preços.

| Fonte | Uso inicial | Ativação | Cobertura e limites |
|---|---|---|---|
| SEC EDGAR | Submissions e metadados de filings | SEC_USER_AGENT com contato do operador | Relatórios públicos de empresas selecionadas; não extrai holdings 13F ou transações Form 4 nesta entrega |
| Coinbase Exchange | Candles históricos diários | Aceite de uso pessoal explicitamente configurado | Uma venue, somente candles fechados; máximo 300 por chamada; sem WebSocket nesta fatia |
| Fixtures demo | Séries e calendário fictícios | Demo local | SIMULADO / DEMO em toda apresentação; não contam como cobertura real |
| Trading Economics | Contrato de adapter/calendário | Credenciais e licença; integração a concluir | Consenso não presumido |
| Benzinga | Contrato de adapter/notícias | Credenciais e licença; integração a concluir | Não armazenar conteúdo integral sem autorização |
| Massive, Databento, CoinGlass, Helius, Arkham, Nansen | Planejadas | Credenciais e entitlements | Sem valores fabricados |

Documentação oficial consultada:
- https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- https://www.sec.gov/about/developer-resources
- https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles
- https://www.coinbase.com/legal/market_data
- https://docs.tradingeconomics.com/economic_calendar/streaming/
- https://docs.benzinga.com/introduction/welcome

O sucesso real de ingestão é registrado no estado do provedor e em docs/progress.md; não pode ser inferido a partir da existência do adapter. Falhas de rede, HTTP 403/429 ou configuração ausente não provocam fallback demo.
