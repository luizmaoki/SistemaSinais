# ADR 001: monólito modular e demonstração local

Status: aceito em 08/10/2026.

Contexto: projeto vazio; objetivo entregar uma base executável sem assinaturas de mercado.

Decisão: Next.js + FastAPI + SQLAlchemy/Alembic + PostgreSQL + Celery/Redis, com SQLite exclusivamente para desenvolvimento/testes. Compose publica apenas localhost. Acesso demo identifica workspace fixo, sem permitir escolha arbitrária de tenant por headers. Não habilitar produção até implementar OIDC e autorização real.

Consequência: infraestrutura simples e jobs destacados, sem complexidade de microsserviços. Demo serve a desenvolvimento pessoal, não prova segurança de autenticação comercial. APIs reais ficam separadas de fixtures e exigem licença/configuração adequada.

Reversão: parar os serviços preservando volumes; backups PostgreSQL antes de migrações futuras. Não executar docker compose down -v para encerrar normalmente, pois isso apagaria dados.
