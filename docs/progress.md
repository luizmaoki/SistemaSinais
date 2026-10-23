# Entrega — Capital Intelligence

Verificação local em 09/10/2026. O briefing integral foi usado como especificação. Esta entrega constitui uma base executável; não representa a implementação completa de todas as funcionalidades descritas no documento.

- **Fases implementadas:** Fase 0 executável, núcleo da Fase 1 e fatia vertical SEC da Fase 2. Critérios locais de inicialização, pesquisa NVDA/BTC, gráfico, retornos e disclosure real verificados. Requisitos mais amplos do briefing continuam no backlog abaixo.
- **Principais recursos utilizáveis:** dashboard responsivo, catálogo tipado de 15 instrumentos, pesquisa/filtros, páginas de ativo, candles/volume/SMA, indicadores básicos, tabela mensal, scanner básico, múltiplas watchlists persistentes, regras acima/abaixo de preço, alertas com evidência e deduplicação, calendário demonstrativo, publicações SEC e saúde/licença de 16 fontes.
- **Integrações REAIS ativas:** SEC EDGAR submissions oficial, com contato configurado somente no backend local. Ingestão periódica/manual, PostgreSQL, vínculo por empresa, links originais, checksum e preservação de versões. Banco local contém 401 registros de filings de quatro empresas (NVDA, AAPL, MSFT e NU), incluindo atualização recebida pelo job. A consulta HTTP expõe até 200 registros por chamada; ainda falta paginação dos disclosures.
- **Módulos DEMO:** sessão/usuário local, catálogo inicial limitado, OHLCV diário determinístico de ações/ETFs/cripto, métricas derivadas dessas barras e calendário ilustrativo. Actual/consensus/previous macro ficam vazios. Não há cotação ao vivo. O modo acompanha a série e os alertas.
- **Integrações dependentes de chaves/licenças:** Trading Economics, Benzinga, feeds de preços/opções/L2/L3, on-chain e análise por IA. Existem contratos tipados, registry, estados de configuração e respostas estruturadas de indisponibilidade; integrações premium não estão implementadas para simples ativação por chave. Coinbase REST possui adapter e testes sintéticos, mas permanece desativada: depende de aceite e direitos apropriados; nenhum dado real Coinbase foi acessado nesta execução. Streaming Coinbase não implementado.
- **Arquivos centrais criados/alterados:** apps/web (Next.js e fluxos Playwright), services/api/app (FastAPI, modelos, cálculos, adapters e jobs), packages/shared-types, infra/docker, infra/migrations, fixtures, docker-compose.yml, scripts, .github/workflows/ci.yml, README e docs. Credenciais/contato em .env ignorado; nenhum contato pessoal foi incorporado aos fontes ou fixtures.
- **Migrações criadas:** 0001_foundation, snapshot explícito de 15 tabelas com índices/constraints. Upgrade, downgrade e novo upgrade executados em banco PostgreSQL separado capital_migration_test; alembic check sem diferenças. Reversão destrói as tabelas: utilizar apenas em banco descartável ou após backup e plano de restauração.
- **Testes executados e resultados:** 31 testes backend passaram; Ruff passou; frontend lint e typecheck passaram; build Next.js passou; npm audit encontrou zero vulnerabilidades; seis testes Playwright Chromium passaram; smoke integrado passou, incluindo tarefa Celery executada pelo worker. Docker Compose inicializou API, banco, Redis, worker e web; serviços com healthcheck saudáveis. Dois revisores independentes aprovaram as correções financeiras e de infraestrutura/segurança. CI foi criada, mas não executada em serviço remoto nesta entrega.
- **Comandos para rodar localmente:** docker compose up --build -d; abrir http://localhost:3000; API http://localhost:8000/docs; python scripts/smoke.py. Configure .env a partir de .env.example apenas se ausente. Detalhes e comandos de testes no runbook.
- **Problemas conhecidos:** demo local não implementa autenticação real e não suporta SaaS; produção falha de forma explícita até OIDC. Sem feeds reais de preços ou calendário macro. Filings são metadados reportados, sem extração de holdings/transações ou interpretação causal. Calendário de ações usa NYSE para o universo piloto; ampliar regras por venue antes de novos instrumentos. Gráfico SVG diário ainda sem zoom/streaming. TestClient gera aviso de depreciação httpx/Starlette e Alembic aviso path_separator; testes passaram. Google Drive não oferece bind mounts Docker utilizáveis neste ambiente; imagens foram construídas por contexto e testes de navegador executados em container com arquivos copiados.
- **Próximas tarefas (ordenadas por prioridade):** 1) expandir ingestão de fontes oficiais, paginação de disclosures e feeds autorizados de preços/calendário; 2) completar catálogo, calendários por venue, corporate actions e séries ajustadas; 3) OIDC, políticas de autorização/entitlements e testes reais multi-tenant; 4) scanner avançado, comparação de séries, gráfico interativo e localização completa; 5) notícias licenciadas e IA com evidências/citações; 6) streaming cripto/on-chain com reconexão e reorgs; 7) parsing 13F/Form 4/COT e opções; 8) L2/L3 e modelos de liquidez; 9) backtests point-in-time, calibração de scores e robustez SaaS.

## Evidência de testes

| Verificação executada | Resultado |
|---|---|
| docker compose run --rm api python -m pytest -q | 31 passed, 4 avisos de depreciação |
| .venv/Scripts/ruff.exe check services/api | All checks passed |
| npm run lint / npm run typecheck no container web | Exit 0 |
| docker compose up --build -d | Build e inicialização completos |
| npm audit --audit-level=high no container web | 0 vulnerabilities |
| npm run test:e2e em imagem oficial Playwright 1.64 Chromium | 6 passed |
| python scripts/smoke.py | WORKER TASK OK; SMOKE OK |
| Alembic em PostgreSQL de teste | check sem diferenças; downgrade/upgrade concluídos |
| .env ignorado pelo Git | Confirmado por git check-ignore |

Playwright cobriu login demo, busca repetida NVDA/BTC, chart/retornos, fonte ausente sem dados substitutos, watchlist persistente, alerta persistente, calendário/fontes/filing real, falha de API, navegação mobile e rejeição de origem externa. Captura desktop foi inspecionada; lista de disclosures relacionados usa rolagem para preservar a altura do dashboard.

Testes financeiros cobrem mês sem base, lacunas, mês parcial, fechamento de sessão/feriados, dados disponíveis à época e volatilidade sem anualizar intervalos com sessões faltantes. Testes de adapters usam fixtures sintéticas separadas dos filings reais do banco local. Testes de segurança exercitam spoofing de tenant, payload/origem, produção bloqueada, revogação do opt-in e deduplicação.

## O que ainda não satisfaz o produto completo

A base F0/F1 atende o piloto local, mas as seções completas do briefing excedem esta primeira entrega: cobertura ampla de instrumentos, feed de preços real, OAuth/OIDC, séries ajustadas e ações corporativas ingeridas, weekly/indexed comparisons, scanner avançado, notícias independentes, macro real, sinais calibrados, streaming e backtesting continuam pendentes. As fases 3–6 não são consideradas entregues. Não há execução de ordens nem deploy em nuvem.

## Reversão e preservação

Encerrar com docker compose down preserva o volume PostgreSQL. Para reverter código, reconstruir uma versão anterior compatível; para alterações de schema, salvar pg_dump antes e testar restauração em banco separado. Não executar downgrade base no banco principal: apaga as tabelas e exige restauração. O teste de downgrade desta entrega atingiu exclusivamente um banco descartável e SQLite temporário.

A inspeção visual encontrou expansão indevida da página por rótulos acessíveis posicionados fora da lista rolável. Correção: contexto de posicionamento na lista, mantendo todos os links e rótulos. Experimento Chromium reduziu a altura de 16.875 para 2.987 pixels a 1440 px de largura; o fluxo desktop agora verifica altura menor que 4.000 px.

## Passo 1 Consolidar a fundação

Atualização em 13 de outubro de 2026. Código implementado e revisado; a validação operacional local com as correções finais passou. O passo 1 está concluído, incluindo a execução da CI remota; evidência em docs/ci-validation.md.

Entregas: scripts de instalação isolada, backup PostgreSQL binário com checksum e restauração em banco novo, comparação de tabelas, persistência após recriar containers, logs JSON com campos permitidos, rotação Docker, healthcheck web, teste ampliado de migração e seed, e CI com execução manual e relatórios sem dumps. Procedimento em docs/foundation-step-1.md.

Evidências de 9 de outubro: 33 testes backend passaram; instalação isolada capitalverify2dd6f46627eb PASSED, incluindo restore de 16 tabelas e persistência; backup do banco principal restaurado em banco separado com igualdade das 16 tabelas e 401 filings. O banco principal não foi substituído.

Evidências de 13 de outubro: 7 testes operacionais passaram; Ruff passou; integridade do backup existente confirmada; exclusões Git confirmadas. A revisão financeira aprovou a implementação. A revisão de infraestrutura aprovou as duas correções solicitadas: destino de backups restrito a artifacts e status FAILED quando a limpeza falhar. Os resultados anteriores do Docker não são tratados como prova da execução final das correções.

Impedimentos: Docker Desktop 4.71.0 falha no startup ao acessar o socket interno dockerInference, antes do engine Linux ficar disponível. A parada normal pelo CLI não resolveu. A revisão automática de aprovação rejeitou a tentativa de encerrar processos Docker e renomear o diretório de runtime, por risco de interromper ou corromper o ambiente sem autorização explícita. Essa tentativa não foi executada; nenhum volume ou diretório interno foi alterado por ela. Não foi usado factory reset. CI remota não executada porque git remote -v não retorna repositório configurado.

Para concluir: obter autorização para a recuperação delimitada do Docker ou aguardar sua recuperação pelo operador; executar python scripts/foundation_check.py com o código final; aplicar o Compose principal após validação; definir o repositório de destino e executar o workflow remoto. Não foi iniciada a autenticação do passo 2.

### Recuperação delimitada do Docker em 13 de outubro

O operador autorizou encerrar os processos travados do Docker e preservar por renomeação somente %LOCALAPPDATA%/Docker/run. A intervenção foi executada; a pasta anterior está preservada como run.capital-recovery-20261013-144509. Nenhum volume foi apagado e nenhum banco foi restaurado sobre o principal.

O novo startup superou dockerInference, mas falhou ao acessar %LOCALAPPDATA%/docker-secrets-engine/engine.sock. A inspeção somente leitura mostrou que essa segunda pasta contém apenas esse socket temporário de zero bytes. Como ela está fora do diretório explicitamente autorizado, foi solicitada uma extensão delimitada da autorização. A segunda pasta não foi alterada. A validação Docker final permanece pendente; os resultados de 9 de outubro continuam sendo evidência histórica, e não uma execução atual.


### Resultado final local em 13 de outubro de 2026

A extensão à pasta docker-secrets-engine foi autorizada. Ela foi preservada como docker-secrets-engine.capital-recovery-20261013-144922. Como o crash intermediário recriou o primeiro socket inacessível, Docker/run foi novamente preservado, sob a autorização existente, como run.capital-recovery-20261013-145028. O Docker voltou a funcionar, versão de engine 29.4.1. Não houve factory reset, exclusão de volumes ou restauração sobre o banco principal.

A execução atual de scripts/foundation_check.py terminou com FOUNDATION OK. Relatório: artifacts/foundation/capitalverifybaf603014c9a/report.json, status PASSED. Os 33 testes backend passaram; Ruff e Alembic check passaram; smoke confirmou tarefa real do worker; logs estruturados foram conferidos sem vazamento do sentinela de query; repetição do seed não alterou os dados; restauração correspondeu às 16 tabelas; a persistência após recriar containers foi confirmada; os recursos isolados foram removidos com sucesso.

Os 7 testes operacionais passaram novamente. Actionlint 1.7.7 validou o workflow da CI sem erros. O volume principal sistemasinais_postgres_data mantém a data de criação de 8 de outubro de 2026.

Pendência restante do passo 1: escolher o repositório GitHub, publicar a revisão aprovada e executar a CI remota. git remote -v ainda não aponta um destino. Actionlint e a execução local não são apresentados como execução remota. O passo 2 não foi iniciado.

O ambiente principal recebeu o Compose revisado: API, PostgreSQL, Redis, worker e web saudáveis. O smoke principal passou, incluindo tarefa real do worker. A aplicação está disponível em http://localhost:3000. Após atualizações da SEC, o banco contém 502 filings.

Foi criado um backup novo em 13 de outubro: artifacts/backups/capital-20261013T175618Z-ccf7363e.dump, acompanhado do manifest e do relatório .verify.json. A restauração em banco separado passou com igualdade das 16 tabelas, incluindo 502 filings, e a origem não mudou durante o backup. O banco principal não foi substituído.

### Publicação da fundação e CI remota

O operador indicou https://github.com/luizmaoki/SistemaSinais.git como destino. O repositório foi conferido vazio, com branch padrão main. O remote origin foi configurado; a publicação inicial usa a revisão local aprovada. .env, dumps, relatórios locais e o arquivo pessoal da skill permanecem fora do Git. A identidade de commit usa o endereço noreply do GitHub. A execução remota da CI será registrada após sua conclusão, sem confundir o resultado com a validação local.


### Passo 1 concluído com CI remota

Em 13 de outubro de 2026, o código foi publicado na main de https://github.com/luizmaoki/SistemaSinais. A execução https://github.com/luizmaoki/SistemaSinais/actions/runs/38444822636 terminou com completed/success para o commit ca456adc94d48bb3b1c3eeab9508d0280dd44316.

Evidência remota: 33 testes backend, 7 operacionais e 6 Playwright passaram; lint/typecheck/build, instalação limpa, migrações, logs, backup/restauração, persistência, worker real e limpeza passaram. O artefato foundation-report foi publicado sem dumps. Relatório completo em docs/ci-validation.md.

O passo 1 está concluído. O passo 2 ainda não foi iniciado. A atualização de documentação que registra a CI não altera o código testado.

## Passo 2 iniciado — 14 de outubro de 2026

Provedor escolhido pelo usuário: Keycloak local. Ambiente OIDC separado em implementação, com projeto Compose capitaloidc, portas 13000/18000/18080 e contas sintéticas de duas identidades. O Keycloak 26.8.1 iniciou, importou o realm e publicou discovery com issuer exato e suporte a S256. Nove testes operacionais e Ruff dos scripts passaram. A implementação de login, sessão e interface e suas revisões estão em andamento; ainda não se declara o passo 2 concluído. Procedimento em docs/auth-step-2.md.

## Passo 2 — validação local concluída em 17 de outubro de 2026

OIDC com Keycloak local, sessão opaca revogável, CSRF, papéis owner/viewer e isolamento de usuários/organizações implementados. Duas revisões independentes aprovaram o código e os ajustes finais. A aplicação OIDC executa no projeto separado capitaloidc em localhost:13000; o banco demo principal foi preservado.

Passaram 116 testes backend, nove operacionais, Ruff, lint, TypeScript e build. O fluxo real de Keycloak passou com Alice/Bob: dados persistem após reload, Bob não acessa recursos de Alice, logout invalida a sessão, origem externa/CSRF incorreto são rejeitados e a classificação financeira DEMO permanece explícita. Execução OIDC: 12 cenários passaram e seis específicos demo foram ignorados.

A validação PostgreSQL capitalverifyabf0b3b1d865 terminou PASSED com migração 0002, restauração verificada de 18 tabelas, seed idempotente, logs sem sentinela sensível, persistência entre recriações e limpeza dos recursos isolados. Relatório preservado em artifacts/foundation/capitalverifyabf0b3b1d865/report.json. Detalhes, comandos e limites em docs/auth-step-2.md e docs/decisions/004-oidc-session.md. A execução remota da nova CI ainda deve ser confirmada e não é inferida dos testes locais.

## Passo 2 — CI remota aprovada em 17 de outubro de 2026

A execução 39045560779 terminou com jobs checks e oidc em success no commit de código e612462b83e28ba960e1c649ef1facb3657d8d49. Confirmados remotamente: 116 testes backend, nove operacionais, instalação limpa, migração/restauração, persistência, smoke, build e regressão web nos modos demo (16 cenários) e OIDC real (12 cenários). São 18 cenários web distintos entre os modos. O passo 2 está concluído para desenvolvimento local. Evidência: docs/auth-ci-validation.md. PR 1 disponível para revisão; não houve merge ou deploy em produção. As dependências e os recursos futuros permanecem registrados em docs/auth-step-2.md.

## Passo 3 iniciado em 17 de outubro de 2026

Escopo confirmado pelo roteiro Word: catálogo e integridade dos dados. O resumo anterior de cinco itens do README foi alinhado às 13 etapas para evitar confundir este passo com notícias/IA, que pertencem ao passo 7. Em implementação: importação validada, identidade e vigência, calendários explícitos, eventos corporativos e visões de preços ajustadas com proveniência. Não se declara a etapa concluída antes dos testes e das duas revisões independentes dos cálculos. Decisões e dependências em docs/catalog-step-3.md e docs/decisions/005-catalog-integrity.md.

## Passo 3 — validação integrada em 21/22 de outubro de 2026

A instalação isolada capitalverify895423bed0e4 terminou PASSED: migração 0003, backup/restauração com igualdade das 20 tabelas, seed idempotente, persistência após recriar containers, smoke de calendários e ajustes, logs e limpeza. A suíte backend passou com 165 testes; nove testes operacionais passaram. A interface passou em lint, tipagem, build e 25 cenários Playwright DEMO, incluindo a fixture real SPLIT-DEMO; dois cenários exclusivos OIDC foram ignorados nessa execução.

Em ambiente isolado, os arquivos verificados acrescentaram GOOG, GOOGL, BRK.A e BRK.B sem criar preços. Reimportação retornou UNCHANGED. A resolução por CIK compartilhado retornou 409 com os dois UUIDs corretos para cada emissor.

A revisão independente encontrou falhas que impedem encerrar a etapa: reidentificação de opções ao alterar tipo/strike no mesmo UUID, denominação inconsistente de preços/indicadores sem moeda, mapeamento Coinbase que usava só ticker sem conferir venue/moeda e alertas que comparavam valores sem unidade compatível, exibindo a moeda atual do cadastro em observações históricas. A prova Coinbase usou exclusivamente transporte e candles sintéticos; nenhuma API real foi consultada. Correções e nova revisão estão em andamento. Os testes acima são anteriores a essas correções e não constituem aceite do código final.

O ambiente OIDC principal permanece na revisão 0002; backup oidc-pre-step3-20261021T104447Z.dump teve restauração verificada das 18 tabelas. Nenhum banco do operador foi substituído. Procedimento, limites, comandos e dependências em docs/catalog-step-3.md.


## Passo 3 — correções testadas, aceite pendente em 22/10/2026

As quatro falhas da revisão foram corrigidas com regressões dirigidas: imutabilidade de tipo/strike de opções, coerência da denominação em catálogo/scanner, vínculo Coinbase por UUID/produto/venue/moeda e alertas com unidades válidas e apresentação da moeda histórica observada. Os 21 testes específicos passaram; o teste web de moeda dos alertas falhou antes e passou após a correção.

A execução final local passou em 186 testes backend e nove operacionais. Lint, tipagem e build passaram. No navegador, passaram 26 cenários DEMO (dois OIDC ignorados) e 21 OIDC com Keycloak real (sete DEMO ignorados). A instalação isolada capitalverify583792d684a6 terminou PASSED com migração 0003, restauração de 20 tabelas, igualdade de conteúdo, seed idempotente, persistência, logs, worker, smoke e limpeza. Evidências em artifacts/catalog-foundation-20261022.log, artifacts/catalog-demo-e2e-20261022.log e artifacts/catalog-oidc-e2e-20261022.log; relatório em artifacts/foundation/capitalverify583792d684a6/report.json. O snapshot de 82 arquivos de código/testes está registrado em artifacts/catalog-source-snapshot-20261022.json.

A branch local codex/catalog-data-integrity preserva as alterações ainda sem commit. Os dois revisores independentes atingiram limite de uso; a rechecagem final das correções permanece pendente. Não houve publicação do passo 3, CI remota nova ou migração do banco OIDC do operador, que continua em 0002 com backup/restauração conferidos. Os ambientes isolados de navegador foram encerrados preservando seus volumes; os dados do operador e o arquivo Word foram preservados. O passo 3 ainda não está encerrado. Procedimento e dependências externas em docs/catalog-step-3.md.


## Passo 3 — duas revisões aprovadas em 23/10/2026

A revisão de contratos, compatibilidade e reversão aprovou o código final após repetir 21 testes. A revisão financeira e de dados também aprovou, repetindo 42 testes sem rede, incluindo as provas independentes das correções de ingestão e alertas. Não há bloqueantes remanescentes nos pareceres. Os 82 hashes correspondem ao snapshot final testado; cobertura externa de dados continua fora desse aceite. Publicação/CI e atualização local serão registradas após execução.
