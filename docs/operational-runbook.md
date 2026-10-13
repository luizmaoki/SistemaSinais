# Operação local

1. Instale Docker Desktop com engine Linux ativo.
2. Na raiz, copie .env.example para .env somente se .env ainda não existir.
3. Configure SEC_USER_AGENT com nome da aplicação e contato do operador para ativar SEC; não é uma chave paga.
4. Rode docker compose up --build -d.
5. Abra http://localhost:3000 e http://localhost:8000/docs.
6. Verifique docker compose ps e execute python scripts/smoke.py.

Sincronização manual: docker compose exec api python -m app.cli sync --provider sec_edgar. A forma final dos argumentos é mostrada por python -m app.cli --help.

Diagnóstico: docker compose logs --tail=100 api worker web; /api/v1/health e /api/v1/ready; página /sources. A ausência de um fornecedor não deve derrubar as demais telas. Não cole .env ou logs com informações pessoais em issues.

Encerramento: docker compose down mantém o volume do PostgreSQL. Não use down -v sem intenção de apagar os dados locais. Antes de uma migração futura, faça backup com pg_dump. As migrações inicial e seguintes precisam ter downgrade revisado antes de uso fora do ambiente local.

Coinbase permanece desativada por padrão. Leia docs/licensing.md e os termos oficiais antes de habilitar uso pessoal. Não use esse dataset em LLM, agentes de IA ou distribuição a terceiros sem permissão da fonte.

Produção/SaaS não habilitados: requer OIDC, autorização, entitlements, TLS, backups e licenças comerciais verificadas. O Compose entregue destina-se exclusivamente a desenvolvimento local.

## Verificações reproduzíveis

Backend:

    docker compose run --rm api python -m pytest -q
    docker compose run --rm api python -m ruff check app tests

Frontend:

    docker compose exec -T web npm run lint
    docker compose exec -T web npm run typecheck
    docker compose exec -T web npm audit --audit-level=high

E2E em ambiente com Node 24 e Chromium Playwright instalados, a partir de apps/web:

    npm ci
    npx playwright install chromium
    npm run test:e2e

E2E_BASE_URL define o endereço (padrão http://localhost:3000). E2E_EXPECT_SEC=true exige filing real previamente ingerido; a CI sem contato SEC verifica o estado vazio. O smoke também valida uma tarefa real no worker; API pronta sozinha não é suficiente.

O proxy aceita mutações apenas com Origin autorizado e Host correspondente. PUBLIC_APP_ORIGINS é uma lista explícita, separada por vírgulas; padrão local: http://localhost:3000,http://127.0.0.1:3000,http://web:3000. Se mudar domínio/porta, configure esse valor no ambiente do serviço web. Não libera produção ou OIDC.

## Consolidação da fundação e recuperação

O passo 1 tem procedimento completo em docs/foundation-step-1.md. Para validar instalação com banco novo, logs, migrações, backup/restauração e persistência, execute python scripts/foundation_check.py. Esse comando usa um projeto isolado e preserva o banco principal.

Backup local: python scripts/db_backup.py backup artifacts/backups/<nome-novo>.dump. Conferência: python scripts/db_backup.py verify artifacts/backups/<nome>.dump. Preserve o manifest .dump.json junto ao arquivo. A restauração de verificação usa somente um banco novo; não substitui capital.
