# ADR 005 — identidade, calendários e ajustes corporativos

Data: 17 de outubro de 2026. Decisão do passo 3.

## Identidade e proveniência

Conservar asset_id UUID como identidade canônica e todos os IDs existentes. Ticker é um identificador com escopo e vigência, usando intervalos [início, fim). Uma busca que encontre instrumentos diferentes deve retornar ambiguidade e candidatos. CIK representa o filer e pode ser compartilhado por classes de ações; não será uma chave exclusiva do instrumento.

A importação é uma operação administrativa local sobre arquivo autorizado. Não criar endpoints HTTP de gravação global de catálogo nesta etapa. Validar o documento inteiro e aplicar uma transação; repetições não criam duplicatas e correções mantêm revisões anteriores. Horários de disponibilidade e ingestão limitam consultas históricas, sem assumir que uma correção posterior já era conhecida no passado.

## Calendários

Associar calendário e timezone ao instrumento. XNAS/NASDAQ usam o alias XNYS fornecido pela versão fixada de exchange_calendars; essa dependência deve ficar explícita. Cripto utiliza sessões UTC 24/7. Não aplicar calendário de ações NYSE a futuros, OTC ou instrumentos sem configuração verificada. Datas fora da cobertura do calendário devem produzir indisponibilidade explícita.

## Ajustes

Armazenar barras brutas imutáveis e construir visões derivadas. A convenção da barra de origem deve ser verificada antes de aplicar fatores. Não misturar barras de provedores, timeframes ou convenções diferentes; não modificar o preço histórico armazenado.

O modo unadjusted preserva preços e volumes. Para split_adjusted, o fator de preço de um evento é ações antigas / ações novas; preços anteriores são multiplicados e volumes anteriores divididos por esse fator. Um split reverso usa a mesma regra.

O modo split_dividend_adjusted acrescenta um fator de preço 1 - dividendo / fechamento de referência da sessão imediatamente anterior. Se houver split na mesma data efetiva, a referência é colocada na base posterior ao split; o dividendo é expresso por ação nessa mesma base. Eventos distintos na data são combinados de forma determinística. Dividendos não modificam volume.

Recusar cálculo quando a referência estiver ausente, ainda indisponível, em moeda incompatível ou resultar em fator não positivo. Somente eventos efetivos até a base final da série e conhecidos no instante consultado podem participar. Cobertura explícita do dataset é necessária mesmo quando a lista de eventos está vazia.

Essa transformação é uma convenção multiplicativa de preço histórico; não representa dividendos reinvestidos nem retorno total de carteira. Não copiar fatores cumulativos de um fornecedor e multiplicá-los novamente como se fossem fatores individuais. A interface e a resposta HTTP devem informar o método e a visão utilizada em barras, retornos e indicadores.

## Migração e reversão

A migração deve preservar os dados anteriores e ser validada com banco populado. Antes de aplicar ao ambiente local usado pelo operador, criar backup e demonstrar restauração em banco novo. O downgrade que remover campos/tabelas novos perde metadados e revisões do passo 3; por isso, reverter código exige plano explícito e backup, sem apagar automaticamente os dados do operador.
