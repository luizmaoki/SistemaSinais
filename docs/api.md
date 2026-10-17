# API

OpenAPI: http://localhost:8000/docs e /openapi.json. Prefixo /api/v1.

Health, readiness, auth/config, auth/login e auth/callback são públicos. As rotas de dados dependem da identidade demo local ou da sessão OIDC, conforme AUTH_MODE. O proxy Next.js encaminha a API pelo servidor e limita rotas/métodos, tamanho do corpo, origem das mutações e tempo de espera.

Contrato base: listas em {items}; catálogo em {items,total,page,page_size}. Instrumentos usam id estável, symbol, display_name, asset_type, currency e venue. Séries retornam items e proveniência, com classificação de modo. Retornos mensais têm month, return_pct e partial.

Rotas iniciais: assets, assets/{id}, assets/{id}/bars, assets/{id}/returns, scanner, macro/calendar, news, institutional/filings, providers, coverage, watchlists, alert-rules e alerts. Implementação e limites completos constam do OpenAPI gerado.

Sem dataset contratado, retornar indisponibilidade tipada. Não preencher dados reais ausentes com DEMO. Consultas de filings retornam metadados de relatórios, não posições atuais. A execução de sync é CLI/job do backend, não uma ação de trading.

## Autenticação do passo 2

GET auth/config informa o modo e o caminho de entrada. GET auth/login inicia OIDC; GET auth/callback valida o retorno e cria a sessão HttpOnly. GET auth/session retorna identidade, papel, organização, expiração e token CSRF para uso em memória. POST auth/logout exige CSRF em OIDC, revoga a sessão local e limpa os cookies.

As mutações pessoais exigem papel owner e X-CSRF-Token válido em OIDC. O papel viewer permite leitura dos próprios recursos. O servidor define usuário/organização pela sessão; nunca aceita identidade via Authorization ou campos do cliente. Sessão ausente/expirada retorna 401; conta inativa, papel insuficiente ou CSRF inválido retorna 403. Cookies do provedor não são encaminhados pelo proxy da aplicação.
