# ADR 003: gráfico nativo na primeira entrega

Status: aceito em 08/10/2026.

A primeira fatia usa SVG responsivo para visualizar séries históricas e respectivas fontes/modos, mantendo a interface sem dependência de engine financeira complexa. O gráfico é uma apresentação da série recebida do backend; não gera preços nem substitui barras ausentes.

Lightweight Charts/ECharts serão introduzidos quando ferramentas de candles, zoom, estudos sincronizados e camadas de liquidez justificarem esse custo. O gráfico inicial não representa um terminal de execução nem um heatmap de ordens.
