# Validação remota da fundação

O passo 1 foi concluído em 13 de outubro de 2026, com validação local e GitHub Actions aprovados.

Repositório: https://github.com/luizmaoki/SistemaSinais
Branch: main
Código validado: ca456adc94d48bb3b1c3eeab9508d0280dd44316
Workflow: .github/workflows/ci.yml
Execução: https://github.com/luizmaoki/SistemaSinais/actions/runs/38444822636
Resultado observado: completed / success

## Resultados efetivamente executados no GitHub

| Verificação | Resultado |
|---|---|
| Ruff do backend, scripts e migrações | Aprovado |
| Testes operacionais de segurança e limpeza | 7 testes passaram |
| Frontend lint, typecheck e build | Aprovados |
| Testes backend em instalação isolada | 33 testes passaram, 1 aviso de depreciação |
| Alembic check e seed repetido | Aprovados |
| Logs estruturados e proteção de query | Aprovados |
| Backup e restauração comparada | Aprovados |
| Persistência após recriar containers | Aprovada |
| Limpeza do projeto isolado | Aprovada |
| Compose completo e smoke com worker real | Aprovados |
| Playwright Chromium | 6 testes passaram |
| Relatório foundation-report | Publicado como artefato da execução |

O log remoto confirmou FOUNDATION OK, WORKER TASK OK e SMOKE OK. O job terminou com success. O artefato foundation-report tem ID 11837983412 e retenção configurada de sete dias; o link da execução permanece como referência após a expiração do artefato.

## Escopo e dados

A CI usou ambiente novo e datasets sintéticos identificados como DEMO. Não recebeu o contato SEC, credenciais pagas, .env local ou o banco do usuário. A integração SEC real e o backup dos 502 filings foram validados localmente e estão registrados em docs/progress.md.

A árvore publicada do commit validado foi conferida: 101 arquivos, sem .env, dumps, artifacts, dependências locais ou o arquivo pessoal da skill. Commits usam o endereço noreply da conta GitHub; o contato privado configurado para SEC não aparece nos arquivos publicados.

A atualização posterior que registra estes resultados altera somente documentação. O commit de código apontado acima é a revisão efetivamente testada pelo GitHub Actions.

## Reproduzir

No GitHub, abrir Actions, selecionar ci e executar Run workflow na branch main. Pushes e pull requests também disparam o workflow, salvo commits explicitamente marcados para não repetir CI.

Localmente:

    python -m unittest discover -s scripts/tests -v
    python scripts/foundation_check.py
    docker compose up --build -d --wait --wait-timeout 240
    python scripts/smoke.py

O procedimento de backup e recuperação está em docs/foundation-step-1.md. A evolução funcional continua no passo 2, autenticação real; as demais fases do produto permanecem no roadmap.
