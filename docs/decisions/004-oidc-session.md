# ADR 004 — OIDC com sessão opaca no servidor

Data: 14 de outubro de 2026. Decisão para o passo 2.

## Contexto

A identidade demo fixa não permite testar isolamento entre usuários nem operar fora do desenvolvimento. O usuário escolheu Keycloak local. O terminal continua exibindo explicitamente as séries financeiras simuladas, mesmo após login real.

## Decisão

Usar Authorization Code com PKCE S256, state vinculado a cookie de navegador independente, nonce e validação criptográfica RS256 do ID token. A identidade é a dupla issuer/subject validada. Email e claims de tenant/papel não concedem acesso.

Persistir apenas o hash de um identificador de sessão aleatório, associado ao usuário, token CSRF e vencimento limitado pela validade do ID token. Cookies da aplicação são HttpOnly, SameSite Lax e têm escopo /api/v1. Tokens do provedor são transitórios e não são persistidos ou enviados ao JavaScript. Fluxos OIDC vencem e são consumidos uma única vez.

Cada nova identidade recebe uma organização própria. Watchlists, regras e alertas usam o usuário e organização da sessão, nunca valores fornecidos pelo cliente. Papéis owner/viewer e contas ativas são definidos no banco da aplicação. Escritas exigem owner e CSRF; logout pode ser executado por viewer com CSRF.

AUTH_MODE=oidc elimina o acesso demo anônimo. AUTH_MODE=demo é permitido somente em development/test com DEMO_MODE=true. Produção exige HTTPS, cookies Secure, client confidencial e hosts/origens explícitos. O mapeamento de issuer público para o endereço interno Docker é restrito ao desenvolvimento/teste e ao prefixo validado do issuer.

## Consequências e reversão

A migração 0002 adiciona campos de identidade e tabelas de fluxos/sessões preservando os registros existentes. O usuário demo não se torna proprietário dos dados de uma identidade real. O ambiente OIDC local utiliza outro projeto e outros volumes; não altera o banco demo principal.

O downgrade invalida todas as sessões e perde os vínculos OIDC e seus fluxos, mas preserva os registros anteriores e dados pessoais das tabelas existentes. Antes de aplicar alterações em um banco usado, crie e verifique backup. Restauração deve ocorrer em banco novo verificado; não sobrescreva automaticamente o banco existente.

O logout é local: revoga a sessão da aplicação. MFA, convite e compartilhamento de organizações, administração de contas e logout global no provedor não fazem parte desta etapa.
