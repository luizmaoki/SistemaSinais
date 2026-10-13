# Capital Intelligence

Aplicação pessoal de inteligência financeira: frontend Next.js, API FastAPI, PostgreSQL, Redis e worker Celery. Especificação principal: BRIEFING_CAPITAL_INTELLIGENCE_CODEX.md. Entrega e verificações efetivas: docs/progress.md.

## Executar

Na raiz do projeto, com Docker Desktop ativo:

    docker compose up --build -d

Abra http://localhost:3000. API/OpenAPI: http://localhost:8000/docs.

Sem .env, copie .env.example para .env. Não sobrescreva uma configuração existente. O sistema inicia sem chaves pagas e exibe DEMO ou fonte não configurada. Para SEC, configure SEC_USER_AGENT com nome da aplicação e e-mail do operador. As credenciais e o contato ficam apenas no backend e fora do Git.

Windows:

    powershell -File scripts/setup.ps1 -Build

Verificação do stack:

    python scripts/smoke.py
    docker compose ps

Encerrar preservando dados:

    docker compose down

## Escopo

Catálogo de ativos, pesquisa, séries históricas demo identificadas, retornos mensais, watchlists e regras de alerta locais, calendário demonstrativo, fontes e metadados de filings SEC. Dados reais nunca são substituídos silenciosamente por fixtures. Dados Coinbase exigem aceite de uso pessoal e ficam desativados por padrão; sem acesso por agentes de IA ou processamento LLM.

Demo é restrita a desenvolvimento pessoal. Produção/SaaS exige implementação de OIDC e autorização real, revisão de licenças/entitlements e infraestrutura adequada. Não há execução de ordens.

## Documentação

- docs/progress.md: o que foi concluído, testes realmente executados e pendências.
- docs/architecture.md: estrutura e responsabilidades.
- docs/data-sources.md e docs/licensing.md: fontes, cobertura e restrições.
- docs/signal-methodology.md: cálculos e limites das interpretações.
- docs/operational-runbook.md: operação, diagnóstico e preservação de dados.
- docs/api.md e OpenAPI: contratos HTTP.
- docs/decisions/: decisões e simplificações da primeira fatia.

## Evolução

1. Consolidar os critérios restantes das fases 0/1 e integrar calendários oficiais.
2. Autenticação OIDC com isolamento multi-tenant e testes de autorização.
3. Notícias licenciadas e análise fundamentada com citações, somente para fontes que permitam IA.
4. Streaming cripto e reorgs/on-chain; depois 13F/Form 4/COT/opções.
5. L2/L3 licenciado, backtests point-in-time, scores calibrados e robustez SaaS.

O status de cada recurso precisa ser conferido em docs/progress.md; uma rota existente não implica integração completa ou dados ao vivo.

## Passo 1 da evolução

Procedimento e evidências em docs/foundation-step-1.md. Validação isolada: python scripts/foundation_check.py. Backup com conferência de restauração: scripts/db_backup.py. O workflow de CI inclui essas verificações; execução remota depende do repositório de destino.

CI remota da fundação aprovada em 13/10/2026: https://github.com/luizmaoki/SistemaSinais/actions/runs/38444822636. Evidências e escopo em docs/ci-validation.md. O passo 1 está concluído.
