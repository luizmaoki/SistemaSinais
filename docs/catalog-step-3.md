# Passo 3 — catálogo e integridade dos dados

Iniciado em 17 de outubro de 2026. Concluído para processamento local em 23 de outubro de 2026, com duas revisões independentes e CI remota aprovada.

Esta etapa segue o passo 3 do roteiro Word: ampliar instrumentos e identificadores, usar calendários explícitos, validar moedas e contratos, ingerir splits/dividendos e distinguir preços brutos de preços ajustados. Notícias e IA pertencem ao passo 7 do roteiro de 13 etapas.

## Implementação em validação

- UUID estável do instrumento, histórico de identificadores com vigência e proveniência; ticker ambíguo retorna candidatos, sem escolher silenciosamente.
- Importação local de JSON validado para metadados e ações corporativas autorizadas, transacional, idempotente e com revisões preservadas.
- Calendário por instrumento: sessões de bolsas suportadas, feriados, horário de verão e fechamento antecipado; cripto em UTC 24/7. Calendário não configurado permanece indisponível.
- Identificação explícita de raiz de futuro, contrato com vencimento e ativo spot. Campos ausentes não são inventados; preços conservam sua moeda, sem conversão fixa para BRL.
- Ações corporativas com data efetiva, fonte, disponibilidade, ingestão, identidade nativa e revisão; cobertura explícita para evitar assumir que ausência de eventos significa ausência de splits/dividendos.
- Séries brutas preservadas, com visões ajustadas por splits ou por splits/dividendos em dinheiro, construídas com fatores documentados. Retornos e indicadores usam a mesma visão selecionada.
- Exemplo SPLIT-DEMO claramente simulado, incluindo eventos e barras coerentes, para testar o fluxo sem contratar um feed.

## Limites e dependências

O catálogo não equivale a cobertura de preços. Os novos instrumentos não recebem cotações fictícias. Importar um arquivo exige que o operador tenha direitos de uso desse dataset. Metadados oficiais SEC são associações entre filer, ticker e exchange; CIK não identifica sozinho um instrumento e não fornece uma classificação completa de títulos.

O conector de preços e ações corporativas de um fornecedor contratado permanece uma dependência externa. Nenhuma chave nova é necessária para validar o caminho local com dados sintéticos. Dados reais Coinbase continuam fora de processamento por IA nesta sessão.

Os ajustes são uma convenção explícita de preço histórico, sem simular dividendos reinvestidos, impostos, taxas ou retorno total de carteira. Sem cobertura de eventos, moeda compatível ou referência necessária, a visão ajustada fica indisponível; a aplicação não a substitui silenciosamente por preços brutos.

## Fontes primárias verificadas

- [exchange_calendars 4.13.2](https://github.com/gerrymanoim/exchange_calendars/blob/4.13.2/exchange_calendars/calendar_utils.py): XNAS/NASDAQ são aliases de XNYS nessa biblioteca; não são calendários independentes. A aplicação mantém o calendário utilizado visível.
- [SEC — Accessing EDGAR Data](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data): associações CIK/ticker/exchange, requisitos de identificação e fair access.
- [Massive — ajustes de preços](https://massive.com/knowledge-base/article/is-massives-stock-data-adjusted-for-splits-or-dividends): agregados podem já vir ajustados por splits. A aplicação precisa verificar a convenção de origem e impedir ajuste duplo.
- [Massive — dividendos](https://massive.com/docs/rest/stocks/corporate-actions/dividends): distingue valores em dinheiro, datas e fatores cumulativos. A disponibilidade técnica do endpoint não comprova licença de uso ou redistribuição.
- [LEAN — modos de normalização](https://www.lean.io/docs/v2/lean-engine/class-reference/cs/namespaceQuantConnect.html): modos de ajuste de preço e retorno total têm definições distintas. A metodologia adotada aqui é descrita no ADR 005.

## Operação local

Os exemplos abaixo usam o projeto OIDC local. O banco deve estar migrado antes da importação; o comando não executa migrações nem busca arquivos na internet.

```powershell
docker compose -p capitaloidc -f docker-compose.yml -f infra/docker/compose.oidc.yml --env-file .env.oidc.local exec -T api python -m app.cli import-catalog --file /app/fixtures/catalog/alphabet_verified.json
docker compose -p capitaloidc -f docker-compose.yml -f infra/docker/compose.oidc.yml --env-file .env.oidc.local exec -T api python -m app.cli import-catalog --file /app/fixtures/catalog/berkshire_verified.json
```

Esses dois arquivos acrescentam somente GOOG, GOOGL, BRK.A e BRK.B, com metadados verificados em documentos SEC. O instante available_as_of registra a verificação local da referência, sem alegar o instante original de publicação de todos os campos. As classes compartilham CIK por emissor e têm UUIDs distintos. Não acompanham preços, FIGI/ISIN ou histórico de eventos não verificados. Repetir o mesmo documento retorna UNCHANGED.

Para um dataset autorizado próprio, copie o JSON para o container e execute python -m app.cli import-catalog --file ou python -m app.cli import-actions --file. Os modelos CatalogDocument e ActionsDocument definem o esquema validado; fixtures/catalog/demo_catalog.json e demo_actions.json exemplificam os campos. Arquivos têm limite de 5 MB. URLs de origem não aceitam credenciais, query string ou fragmento; fixture: é reservado a DEMO. O instante de ingestão é atribuído pelo servidor, sem retroagir por um campo fornecido no JSON.

O exemplo SPLIT-DEMO é incluído no seed: UUID 46c77014-7d43-5613-b8e7-6e71ca081111, 40 sessões entre 31/12/2025 e 27/02/2026. Entre 30/01 e 03/02, os fechamentos brutos são 100, 50 e 49; com split/dividendo, são 49, 49 e 49. Isso demonstra a convenção matemática e a preservação dos originais, sem representar rentabilidade real.

## Evidências já executadas

Em 21/10/2026, antes das correções da revisão final:

- 165 testes backend passaram, com dois avisos de depreciação já existentes em dependências.
- Nove testes operacionais passaram; Ruff dos scripts passou.
- Frontend: lint, tipagem e build passaram; 25 cenários Playwright passaram em DEMO e dois exclusivos OIDC foram ignorados. Inclui oito mocks de catálogo e o fluxo real da fixture SPLIT-DEMO.
- Validação isolada capitalverify895423bed0e4: PASSED, revisão 0003, 20 tabelas restauradas com igualdade de conteúdo, seed idempotente, persistência entre recriações, logs e limpeza verificados. Relatório local: artifacts/foundation/capitalverify895423bed0e4/report.json.
- Importação dos quatro instrumentos verificados em outro ambiente isolado: repetição UNCHANGED, nenhum preço inventado e resolução de cada CIK compartilhado retornou 409 com dois UUIDs. Evidência local: artifacts/catalog-import-20261021.json.
- Backup anterior à migração do ambiente OIDC: artifacts/backups/oidc-pre-step3-20261021T104447Z.dump, revisão 0002, restauração verificada em banco separado para 18 tabelas. O banco do operador não foi substituído.

A revisão independente encontrou correções necessárias: impedir alteração de tipo/strike de uma opção sob o mesmo UUID; manter indisponibilidade de moeda consistente nas projeções de catálogo/scanner; impedir associar candles Coinbase a outro venue/moeda por ticker; e impedir alertas com unidades ausentes ou divergentes, preservando a moeda observada na apresentação histórica. As provas de ingestão e alertas usaram exclusivamente dados sintéticos. A etapa permanece em validação até a correção, nova execução e os dois pareceres independentes. A regressão OIDC do código final e a CI remota também permanecem pendentes.

## O que ainda depende de desenvolvimento ou APIs externas

O caminho local de importação não oferece sincronização automática de um catálogo mundial. O conjunto inicial cobre o piloto, a fixture sintética e quatro classes de ações com referências verificadas. Novos calendários, políticas de revisão completas de metadados e fornecedores automatizados exigem expansão posterior.

Preços reais e histórico completo de splits/dividendos exigem fornecedor autorizado, credenciais, contrato de cobertura e validação da convenção de ajuste. Sem esses elementos, a aplicação demonstra o processamento local e apresenta indisponibilidade para cobertura ausente. A integração de preços autorizados é o passo 4.

A restrição legada de unicidade symbol/venue/asset_type foi preservada para compatibilidade. Tickers históricos são resolvidos por aliases com vigência; uma tentativa de cadastrar outro UUID com a mesma chave canônica atual é recusada integralmente. Não se declara um universo histórico completo ou livre de viés de sobrevivência.

## Correções da revisão — 22/10/2026

Os quatro problemas reproduzidos receberam correções e testes de regressão: identidade de opções imutável; preços/indicadores sem denominação válida indisponíveis; ingestão Coinbase vinculada aos UUIDs/produtos explícitos do piloto, com moeda validada da fonte; e regras/alertas com unidade compatível e moeda histórica da observação. O mapeamento Coinbase continua limitado aos três produtos originais BTC-USD, ETH-USD e SOL-USD; importar um criptoativo não o habilita automaticamente no conector.

Os 21 testes específicos passaram. A suíte completa do backend corrigido passou em 186 testes, com os mesmos dois avisos de depreciação de dependências. O teste de interface dos alertas demonstrou a falha antes e passou após a correção para USD, EUR e moeda ausente; lint, tipagem e build passaram. A regressão completa DEMO passou em 26 cenários, com dois exclusivos OIDC ignorados.

A rechecagem independente das correções está pendente por limite de uso dos subagentes. A validação integrada corrigida capitalverify583792d684a6 terminou PASSED: migração 0003, restauração de 20 tabelas com igualdade de conteúdo, seed idempotente, persistência, logs, worker, smoke de catálogo/ajustes e limpeza confirmados. A regressão OIDC corrigida passou em 21 cenários com Keycloak real; sete exclusivos DEMO foram ignorados. Os nove testes operacionais passaram novamente. Logs locais: artifacts/catalog-foundation-20261022.log, catalog-demo-e2e-20261022.log e catalog-oidc-e2e-20261022.log. Os containers dos dois ambientes de navegador foram encerrados preservando seus volumes de teste. O ambiente OIDC do operador permanece na migração 0002. Não há aceite final, publicação do passo 3 ou migração do banco do operador nesta situação.


## Aceite das correções — 23/10/2026

As duas revisões independentes aprovaram o snapshot final sem bloqueantes remanescentes. O revisor de contratos/compatibilidade/reversão repetiu 21 testes e conferiu os módulos/testes da imagem contra o manifesto. O revisor financeiro/dados repetiu 42 testes, com rede desativada, e confirmou por provas sintéticas a recusa de Coinbase para outro venue/UUID/moeda, as unidades dos alertas e sua idempotência, além da preservação de None/EUR/USD nas observações históricas.

O parecer financeiro também confirmou identidade imutável de opções, fatores de split/dividendo, referência da sessão anterior, volume inverso, limites por disponibilidade/ingestão, cobertura obrigatória e preservação das barras brutas. Os dois avisos de dependências são deprecações já conhecidas, sem falhas de testes. O código aprovado corresponde ao snapshot SHA-256 6bcf8b5bee6c8b18990c4491389f3a23abea6d6fe603b79e4e368d3781fcd152, registrado localmente em artifacts/catalog-source-snapshot-20261022.json.

O bloqueio de cota descrito nos registros anteriores foi superado. O aceite cobre o processamento local, sem certificar cobertura mundial de fornecedores, novos calendários ou retorno total. Publicação, CI remota e atualização do ambiente local serão registradas com seus resultados efetivos.


## Atualização do ambiente local — 23/10/2026

Após as duas aprovações, o ambiente capitaloidc recebeu a migração 0003 e iniciou com API, web, worker, PostgreSQL, Redis e Keycloak saudáveis. O check de configuração confirmou issuer exato, PKCE S256 e rejeição de sessão anônima. A aplicação está em http://localhost:13000/login.

Antes da atualização foi criado oidc-pre-step3-20261023T101725Z.dump e sua restauração confirmou 18 tabelas na revisão 0002. Após a atualização, uma nova restauração em banco descartável permitiu comparar todas as linhas antigas nas 17 tabelas de dados, projetadas nas colunas antigas: valores originais, UUIDs, 1.800 barras, três usuários, duas watchlists e uma regra foram preservados. A única exceção esperada nessa comparação é assets.updated_at, avançado pelo enriquecimento de metadados. O relatório local é artifacts/catalog-primary-preservation-20261023.json.

O seed acrescentou SPLIT-DEMO com 40 barras e dois eventos. As duas importações manuais verificadas acrescentaram GOOG, GOOGL, BRK.A e BRK.B, chegando a 20 instrumentos, sem inventar cotações para esses quatro. O backup posterior oidc-post-step3-20261023T102317Z.dump teve restauração verificada das 20 tabelas na revisão 0003, já incluindo as importações. Os dumps e configurações locais continuam ignorados pelo Git. O arquivo Word do operador foi preservado.

O código foi publicado no PR 2, baseado no PR 1 de autenticação, sem merge ou deploy em produção. A execução remota 39938471944 está em validação; o registro final de CI será incluído após conclusão.


## Conclusão — 23/10/2026

O passo 3 está concluído no escopo local documentado. A execução remota 39938471944 terminou com checks e oidc em success no commit 32b2007ffde27933475e9519c9b8d076d730c8e3. Os resultados confirmam 186 testes backend, nove operacionais, 26 cenários DEMO e 21 OIDC, build e validação de dados/infraestrutura. Registro em docs/catalog-ci-validation.md. As pendências e o bloqueio de cota registrados acima são históricos e foram resolvidos; as dependências externas permanecem nas etapas posteriores.
