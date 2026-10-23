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

Demo é restrita a desenvolvimento pessoal. OIDC com Keycloak local está implementado e validado no passo 2; veja docs/auth-step-2.md. Produção/SaaS exige configuração segura do provedor, revisão de licenças/entitlements e infraestrutura adequada. Não há execução de ordens.

## Documentação

- docs/progress.md: o que foi concluído, testes realmente executados e pendências.
- docs/architecture.md: estrutura e responsabilidades.
- docs/data-sources.md e docs/licensing.md: fontes, cobertura e restrições.
- docs/signal-methodology.md: cálculos e limites das interpretações.
- docs/operational-runbook.md: operação, diagnóstico e preservação de dados.
- docs/api.md e OpenAPI: contratos HTTP.
- docs/decisions/: decisões e simplificações da primeira fatia.

## Evolução

O roteiro de 13 etapas segue o arquivo Word do projeto:

1. Consolidar a fundação — concluído.
2. Implementar autenticação real — concluído para desenvolvimento local.
3. Completar catálogo e integridade dos dados — concluído para processamento local; veja docs/catalog-step-3.md.
4. Adicionar preços reais autorizados.
5. Completar dashboard, gráficos e scanner.
6. Completar macro e disclosures.
7. Implementar notícias e análise fundamentada por IA.
8. Implementar cripto, carteiras e alavancagem.
9. Implementar institucionais e opções.
10. Implementar liquidez e microestrutura.
11. Implementar sinais e Strategy Lab.
12. Preparar operação em nuvem e SaaS.
13. Executar o aceite final.

O status de cada recurso precisa ser conferido em docs/progress.md; uma rota existente não implica integração completa ou dados ao vivo.
## Passo 1 da evolução

Procedimento e evidências em docs/foundation-step-1.md. Validação isolada: python scripts/foundation_check.py. Backup com conferência de restauração: scripts/db_backup.py. O workflow de CI inclui essas verificações; execução remota depende do repositório de destino.

CI remota da fundação aprovada em 13/10/2026: https://github.com/luizmaoki/SistemaSinais/actions/runs/38444822636. Evidências e escopo em docs/ci-validation.md. O passo 1 está concluído.

## Passo 2 — Keycloak local

Ambiente separado: python scripts/oidc_local.py up. Acesse http://localhost:13000/login. Contas de teste, comandos e limites em [docs/auth-step-2.md](docs/auth-step-2.md). O login não altera a classificação DEMO das séries financeiras.

CI remota do passo 2 aprovada em 17/10/2026: [evidências](docs/auth-ci-validation.md). Login OIDC, isolamento, migração e regressão demo validados; [PR 1](https://github.com/luizmaoki/SistemaSinais/pull/1).


## Passo 3 — catálogo e integridade

Concluído com duas revisões independentes e CI remota aprovada em 23/10/2026: [evidências](docs/catalog-ci-validation.md). Catálogo com UUIDs/aliases, calendários, importações versionadas e ajustes corporativos preservando preços brutos. Procedimento, cobertura e dependências em [docs/catalog-step-3.md](docs/catalog-step-3.md); [PR 2](https://github.com/luizmaoki/SistemaSinais/pull/2).
