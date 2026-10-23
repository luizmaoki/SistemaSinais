# API

OpenAPI: http://localhost:8000/docs e /openapi.json. Prefixo /api/v1.

Health, readiness, auth/config, auth/login e auth/callback são públicos. As rotas de dados dependem da identidade demo local ou da sessão OIDC, conforme AUTH_MODE. O proxy Next.js encaminha a API pelo servidor e limita rotas/métodos, tamanho do corpo, origem das mutações e tempo de espera.

Contrato base: listas em {items}; catálogo em {items,total,page,page_size}. Instrumentos usam id estável, symbol, display_name, asset_type, currency e venue. Séries retornam items e proveniência, com classificação de modo. Retornos mensais têm month, return_pct e partial.

Rotas iniciais: assets, assets/{id}, assets/{id}/bars, assets/{id}/returns, scanner, macro/calendar, news, institutional/filings, providers, coverage, watchlists, alert-rules e alerts. Implementação e limites completos constam do OpenAPI gerado.

Sem dataset contratado, retornar indisponibilidade tipada. Não preencher dados reais ausentes com DEMO. Consultas de filings retornam metadados de relatórios, não posições atuais. A execução de sync é CLI/job do backend, não uma ação de trading.

## Autenticação do passo 2

GET auth/config informa o modo e o caminho de entrada. GET auth/login inicia OIDC; GET auth/callback valida o retorno e cria a sessão HttpOnly. GET auth/session retorna identidade, papel, organização, expiração e token CSRF para uso em memória. POST auth/logout exige CSRF em OIDC, revoga a sessão local e limpa os cookies.

As mutações pessoais exigem papel owner e X-CSRF-Token válido em OIDC. O papel viewer permite leitura dos próprios recursos. O servidor define usuário/organização pela sessão; nunca aceita identidade via Authorization ou campos do cliente. Sessão ausente/expirada retorna 401; conta inativa, papel insuficiente ou CSRF inválido retorna 403. Cookies do provedor não são encaminhados pelo proxy da aplicação.

## Catálogo e integridade do passo 3

GET assets/resolve recebe identifier_type, value e os escopos opcionais venue/chain_id. as_of é a data de vigência do identificador; known_at é o instante UTC de conhecimento. Identidades distintas retornam 409 com candidate_ids. CIK compartilhado entre classes não escolhe um instrumento automaticamente.

GET assets/{id}/identifiers informa vigência, revisões e proveniência conhecidas em known_at. GET assets/{id}/calendar recebe from/to como datas inclusivas, limitadas a 366 dias, e retorna sessões com abertura/fechamento ou status UNAVAILABLE. GET assets/{id}/corporate-actions aceita source e as_of, com eventos, cancelamentos e cobertura explícita do dataset.

Barras, retornos e indicadores aceitam source, adjustment, as_of e corporate_action_source. Os modos são unadjusted, split_adjusted e split_dividend_adjusted. As respostas informam moeda, calendário, fonte, modo DEMO/real, instante de conhecimento e metodologia. O modo ajustado pode retornar ADJUSTMENT_UNAVAILABLE; o cliente deve apresentar a indisponibilidade sem exibir preços brutos sob um rótulo de ajuste. O método BACKWARD_PRICE_V1 é ajuste de preço histórico, sem simulação de reinvestimento.

Importações administrativas de catálogo e eventos são comandos locais do backend, sem endpoint HTTP de escrita global. Consulte docs/catalog-step-3.md e o OpenAPI para os campos e limites efetivos.

Os eventos de alerta incluem observed_currency, obtida da barra referenciada, sem usar a moeda atual do cadastro como substituição. Uma regra nova exige série com moeda válida; o worker também recusa observações sem unidade compatível. As projeções de catálogo/scanner informam quote_status, quote_reason e quote_currency, mantendo currency como metadado do instrumento.
