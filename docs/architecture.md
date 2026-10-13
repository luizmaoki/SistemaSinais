# Arquitetura

Capital Intelligence usa um monólito modular FastAPI, PostgreSQL, Redis/Celery e frontend Next.js. Os adaptadores normalizam dados no backend; a interface consulta a API pelo proxy de mesma origem. Nenhum segredo de fornecedor faz parte do bundle web.

O Compose é exclusivamente local: portas publicadas em 127.0.0.1, banco e Redis sem portas externas. A identidade demo é fixa e restrita a desenvolvimento. Produção depende de autenticação OIDC validada e não deve permitir acesso demo.

IDs de ativos são estáveis, independentes de ticker. Séries são separadas por fonte e modo. Dados demo jamais preenchem silenciosamente falhas de fontes reais. Filings preservam versões e horários de publicação, ingestão e disponibilidade.

Infra inicial: PostgreSQL 17, Redis 7, Python 3.13 e Node 24. Versões Python e JavaScript devem estar fixadas nos manifestos/lockfiles. Particionamento, ClickHouse e Kafka serão considerados somente com volume medido.

Não há execução de ordens, custódia, conexão de chaves de trading ou promessa de resultado financeiro.
