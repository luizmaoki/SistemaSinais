# Passo 1 Consolidar a fundação

Status em 13 de outubro de 2026: implementação revisada e validação local completa aprovada; CI remota pendente do repositório de destino.

Esta etapa verifica a instalação local, as migrações, os logs e a recuperação dos dados. A execução em GitHub Actions faz parte do aceite, mas depende de um repositório remoto definido. A base continua destinada a desenvolvimento local; autenticação real pertence ao passo 2.

## O que foi implementado

- scripts/foundation_check.py inicia um projeto Compose isolado, com volume novo e portas locais dinâmicas. O contato SEC é vazio e Coinbase fica desativada; essa validação não consulta feeds externos.
- O script executa testes backend, lint, Alembic check e smoke com uma tarefa Celery real; verifica repetição do seed, logs, backup, restauração e persistência após recriar os containers.
- A limpeza só aceita o nome aleatório gerado pelo script. Uma falha de limpeza marca FAILED no relatório e não imprime sucesso.
- scripts/db_backup.py cria um arquivo PostgreSQL custom por fluxo binário, verifica SHA256 e restaura exclusivamente em um banco novo com nome aleatório. O banco principal não é substituído. Na validação isolada, todas as tabelas restauradas são comparadas por quantidade de linhas e fingerprint dos dados.
- Backups só são aceitos dentro de artifacts, sem sobrescrever arquivos existentes. Dumps e manifests também são ignorados globalmente pelo Git e pelo contexto Docker.
- Logs da aplicação usam JSON com campos permitidos de evento, correlação, status e duração. Conteúdo de requisições, URLs, queries, credenciais e detalhes arbitrários de exceções não entram nesse logger. O access log do Uvicorn foi desativado para evitar exposição da query string.
- Os cinco serviços têm rotação de logs Docker de 10 MB por arquivo e três arquivos; a web passou a ter healthcheck próprio.
- O teste de migração verifica colunas, chaves primárias e estrangeiras, seed repetido e downgrade com dados. As foreign keys do SQLite estão habilitadas também no Alembic. O aviso de path_separator foi corrigido.
- A CI inclui execução manual, limite de tempo, validação isolada e publicação apenas do report.json. Arquivos de banco não são enviados como artefatos da CI.

## Como validar a instalação limpa

Com Python 3.10 ou superior e Docker Desktop com engine Linux em execução, na raiz do projeto:

    python scripts/foundation_check.py

O script requer Docker Compose 2.24.4 ou superior para o override das portas. Não altera os containers, os volumes ou a configuração do projeto principal. Ao terminar, remove apenas os recursos descartáveis criados para a verificação; preserva relatório e backup em artifacts/foundation/<projeto-gerado>.

O resultado esperado é FOUNDATION OK e report.json com status PASSED, persistence_verified=true, seed_idempotent=true, restore.status=RESTORE_VERIFIED e isolated_resources_removed=true. Em falha, consulte o relatório e a saída do comando; não interprete um relatório antigo como evidência de uma execução nova.

Verificações rápidas dos scripts:

    python -m unittest discover -s scripts/tests -v
    python -m ruff check --select E4,E7,E9,F scripts infra/migrations

## Como criar e conferir um backup

Com o PostgreSQL do projeto principal em execução:

    python scripts/db_backup.py backup artifacts/backups/capital-20261013.dump
    python scripts/db_backup.py verify artifacts/backups/capital-20261013.dump

Escolha um nome novo para cada backup. Preserve o .dump e o .dump.json juntos: o segundo contém revisão, tamanho e checksum. O comando verify cria um banco de teste, restaura o arquivo, verifica schema e revisão, e remove somente esse banco. Ele não restaura sobre o banco capital.

Arquivos de backup contêm os dados do usuário e devem ter acesso restrito. O checksum identifica corrupção; não autentica a origem do arquivo. Restaure apenas backups confiáveis. Redis não é incluído: filas/cache são transitórios nesta versão, enquanto os dados persistentes do produto estão no PostgreSQL.

Para recuperação efetiva após perda do banco, primeiro restaurar em um banco novo, validar schema/conteúdo e compatibilidade com a versão do código; depois preparar a mudança de configuração e testar o aplicativo apontando para ele. A troca do banco principal não é automatizada por este script. Downgrade base apaga tabelas e não substitui um plano de restauração.

## CI remota

O workflow .github/workflows/ci.yml está preparado para push, pull_request e workflow_dispatch. Ainda é necessário definir o repositório de destino, publicar uma revisão do código e executar o workflow. Nenhum repositório remoto foi configurado ou criado nesta etapa. Não enviar .env, dumps, arquivos de QA ou dados pessoais.

Referência oficial sobre disparo de workflows: https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow

## Evidências já obtidas em 9 de outubro de 2026

- 33 testes backend passaram, incluindo a verificação ampliada de migração e dois testes de logging; permaneceu um aviso de depreciação do TestClient.
- A instalação isolada capitalverify2dd6f46627eb terminou com PASSED, restauração comparada das 16 tabelas e persistência após recriar containers. O relatório está em artifacts/foundation/capitalverify2dd6f46627eb/report.json.
- O backup do banco principal capital-20261009T191811Z-ac1b583f.dump foi restaurado em banco separado. As 16 tabelas corresponderam aos dados de origem, incluindo 401 filings; o relatório está em artifacts/backups/capital-20261009T191811Z-ac1b583f.verify.json.
- A revisão financeira aprovou o passo 1. A revisão de infraestrutura solicitou proteção adicional de arquivos e relato correto de falha na limpeza; ambas as correções foram aplicadas e cobertas pelos testes operacionais.

A conferência final das correções e do ambiente após a retomada em 13 de outubro será registrada em docs/progress.md. A aprovação da CI remota continua pendente até uma execução no repositório indicado.

## Retomada em 13 de outubro de 2026

Os sete testes operacionais e o lint passaram novamente; o checksum do backup de 9 de outubro foi conferido. A revisão de infraestrutura aprovou as correções finais. A validação Docker final permanece impedida pelo crash de inicialização do Docker Desktop no socket dockerInference; a revisão automática bloqueou a recuperação que encerraria processos e renomearia o runtime. Nenhum factory reset, apagamento de volumes ou substituição do banco foi realizado.

A aprovação da revisão de código é distinta do aceite operacional completo. Próxima execução exigida após recuperar o engine: python scripts/foundation_check.py. A CI remota depende da escolha do repositório GitHub.

A recuperação de Docker/run foi autorizada e executada em 13 de outubro, preservando a pasta como run.capital-recovery-20261013-144509. O engine encontrou em seguida um segundo socket inacessível, docker-secrets-engine/engine.sock. Essa segunda pasta contém apenas o socket e aguarda autorização específica para preservação por renomeação; não foi alterada. Volumes e banco permanecem preservados.


## Validação final local em 13 de outubro de 2026

A recuperação delimitada das duas pastas temporárias foi autorizada e concluída; o Docker voltou a funcionar sem apagar volumes. A execução atual capitalverifybaf603014c9a terminou com PASSED e limpeza completa, incluindo as correções de proteção de backups e relato de falha na limpeza. Os 33 testes backend e os 7 testes operacionais passaram; Ruff, Alembic check, smoke com worker, logs, seed idempotente, restore comparado das 16 tabelas e persistência passaram. Relatório: artifacts/foundation/capitalverifybaf603014c9a/report.json.

O workflow passou no Actionlint 1.7.7. Sua execução remota permanece pendente do repositório GitHub; não foi declarada como executada. As referências anteriores a bloqueios do Docker descrevem o diagnóstico anterior à recuperação.

O ambiente principal foi reconstruído e os cinco serviços ficaram saudáveis; o smoke com tarefa Celery real passou. Backup atual: artifacts/backups/capital-20261013T175618Z-ccf7363e.dump. Sua restauração em banco separado correspondeu às 16 tabelas e aos 502 filings atuais. Preserve esse arquivo junto a capital-20261013T175618Z-ccf7363e.dump.json. Evidência: artifacts/backups/capital-20261013T175618Z-ccf7363e.verify.json.
