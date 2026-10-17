# Passo 2 — autenticação OIDC e isolamento

Implementação local concluída e validada em 17 de outubro de 2026. Publicação no PR 1 e nova CI remota aprovadas; evidências em docs/auth-ci-validation.md.

O provedor escolhido é Keycloak local. O login identifica o usuário; a classificação DEMO dos dados financeiros continua indicando a origem simulada das séries.

## Executar o ambiente local

Na raiz do projeto, com Docker Desktop Linux e Python disponíveis:

    python scripts/oidc_local.py up

Abra http://localhost:13000/login. A API separada fica em http://localhost:18000 e o Keycloak em http://localhost:18080. O projeto Compose capitaloidc utiliza seus próprios volumes e não compartilha o banco do ambiente demo principal.

Contas sintéticas para desenvolvimento e testes: alice / Alice-local-only-2026! e bob / Bob-local-only-2026!. Essas credenciais constam deliberadamente no fixture local. Não habilite esse realm em um endereço público.

O script cria uma senha administrativa aleatória em .env.oidc.local, ignorado pelo Git. Não substitui um arquivo existente. O administrador local se chama capital-admin. Nenhum segredo precisa ser informado no chat.

Verifique a configuração com python scripts/oidc_local.py check. Para parar preservando todos os dados, use python scripts/oidc_local.py down. Não use down --volumes para encerrar normalmente.

A importação do realm acontece apenas na primeira inicialização. O Keycloak preserva um realm existente, incluindo alterações feitas pelo administrador. Alterar o fixture não substitui automaticamente esse realm.

## Validação no navegador

Com o ambiente iniciado:

    cd apps/web
    npm ci
    npx playwright install chromium

No PowerShell:

    $env:E2E_AUTH_MODE = 'oidc'
    $env:E2E_BASE_URL = 'http://localhost:13000'
    npm run test:e2e

Na CI, um job separado inicia Keycloak e executa o fluxo real de login. O job original continua cobrindo a instalação e os fluxos demo.

## Dependências e limites

O Keycloak local não exige contas, chaves ou serviços de terceiros. A primeira instalação requer baixar imagens Docker e dependências. Produção exige provedor/realm administrado, HTTPS, client confidencial, segredo protegido, cookies Secure, hosts e origens explícitos. O start-dev e as contas deste fixture servem apenas ao ambiente local.

O logout encerra a sessão do Capital Intelligence. Encerrar sessões globais no provedor, recuperação de conta, MFA, convites e administração comercial de organizações ficam para etapas posteriores. Cada nova identidade OIDC recebe seu próprio espaço de dados; convites para compartilhar uma organização ainda não estão implementados.

Fontes oficiais: [containers Keycloak](https://www.keycloak.org/server/containers), [versão distribuída](https://www.keycloak.org/downloads), [OpenID Connect Core](https://openid.net/specs/openid-connect-core-1_0.html).

## Entrega e evidências

- OIDC Authorization Code com PKCE S256, nonce, state vinculado ao navegador e consumo atômico de uso único. Assinatura RS256 e claims do ID token verificadas.
- Sessões opacas no servidor, identificadores armazenados como hash, cookies HttpOnly, expiração e revogação por logout. Tokens do provedor não entram no armazenamento do navegador ou no banco da aplicação.
- Identidade por issuer/subject, organização própria para cada nova conta, isolamento de watchlists/regras/alertas, papéis owner/viewer e bloqueio de contas inativas também no worker.
- Proteção CSRF e origem nas gravações. O proxy preserva os cookies individuais, filtra credenciais e limita os redirecionamentos.
- Migração 0002 aditiva, com teste de downgrade/upgrade preservando dados anteriores. Nenhuma migração aplicada ao banco demo principal nesta etapa.
- Duas revisões independentes de domínio e infraestrutura aprovaram o código e as correções finais.

116 testes backend passaram. Nove testes operacionais passaram. Ruff, lint, TypeScript e build Next passaram. O navegador confirmou 12 cenários no modo OIDC, incluindo os dois testes de integração real com Keycloak; os seis cenários exclusivamente demo são ignorados nessa execução, intencionalmente.

A validação isolada de PostgreSQL terminou PASSED em artifacts/foundation/capitalverifyabf0b3b1d865/report.json: revisão 0002, restauração verificada das 18 tabelas, seed idempotente, logs conferidos, persistência após recriação e remoção dos recursos de teste confirmadas. Logs do navegador em artifacts/auth-20261017/oidc-browser.log. Artifacts, backups e configurações locais ficam fora do Git.

A suíte reproduziu e levou à correção de falhas no retorno de claims inválidas (ClaimError do joserfc), do redirecionamento de login quando o provedor falha e dos perfis sintéticos inicialmente sem email. Os testes continuam rejeitando os tokens e verificam a volta controlada ao login.

## O que ainda depende de outras etapas

A autenticação local não depende de API externa contratada. Produção requer configuração segura de um provedor e infraestrutura HTTPS. Integrações financeiras licenciadas e APIs premium continuam no estado descrito em docs/data-sources.md; esta etapa não fornece novas cotações reais nem altera licenças. Administração comercial de usuários, convites, organizações compartilhadas, MFA e logout global no provedor permanecem fora do escopo implementado.

As versões estão fixadas. A suíte registra depreciações de Authlib jose e do transporte TestClient; uma atualização futura deve migrar essas interfaces mantendo os mesmos testes de rejeição e isolamento.
A regressão no modo demo também passou em 17/10: 16 cenários e dois testes exclusivos OIDC ignorados. Os 18 cenários distintos da suíte foram cobertos entre os dois modos. O projeto descartável capitaldemoe2e20261017 foi removido após salvar os resultados; o ambiente capitaloidc permanece disponível.
