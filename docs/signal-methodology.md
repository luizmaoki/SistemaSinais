# Metodologia analítica inicial

Retorno mensal: (último fechamento do mês / último fechamento do mês anterior - 1) * 100. O primeiro mês sem base anterior tem retorno indisponível, não zero. Mês atual é parcial. Uma lacuna de mês anterior impede comparar meses não consecutivos como se fossem um retorno mensal. Séries usam a timezone do instrumento e não misturam adjusted/unadjusted nem fontes/modos.

Fechamentos históricos Coinbase usam buckets UTC de 24 horas encerrados. Não são cotações ao vivo. Dados envelhecidos são STALE; atualizar uma linha no banco não torna seu evento recente.

Médias móveis e RSI são indicadores da série disponível; insuficiência de histórico produz null. Volume relativo intradiário exige sessões/janelas equivalentes e não é inferido a partir de dados diários incomparáveis.

Alertas desta entrega são regras determinísticas de preço acima/abaixo de limiar, com evidência da barra utilizada, modo e deduplicação. Não são recomendação de compra/venda nem probabilidade de retorno.

Filing é REPORTADO: data do filing e período reportado não provam uma negociação naquele dia. Não são calculadas posições atuais de fundos ou insiders a partir de metadados.

Backtesting, scores de confluência, probabilidades calibradas, gamma, HFT e zonas de liquidação ainda dependem de implementação e validação. Todo motor futuro deve rejeitar evidência com available_as_of posterior ao instante da decisão.

Volatilidade anualizada usa desvio populacional de 20 retornos diários e fator sqrt(252) em ações/ETFs ou sqrt(365) em cripto. Exige 21 barras com sessões consecutivas segundo o calendário; lacunas retornam null com motivo, evitando anualizar retornos de vários dias como diários. SMA/RSI e razão de volume usam barras disponíveis, conforme metodologia retornada pela API; o RSI inicial usa médias simples, sem suavização Wilder. Drawdown descreve somente a amostra observada.
