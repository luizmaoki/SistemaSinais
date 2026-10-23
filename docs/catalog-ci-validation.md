# CI remota do passo 3

Validada em 23 de outubro de 2026 no código 32b2007ffde27933475e9519c9b8d076d730c8e3.

- [Execução 39938471944](https://github.com/luizmaoki/SistemaSinais/actions/runs/39938471944): jobs checks e oidc concluídos com success.
- [Job checks](https://github.com/luizmaoki/SistemaSinais/actions/runs/39938471944/job/120363761909): 186 testes backend, nove operacionais, Ruff, lint, tipagem, build, instalação limpa, migração 0003, seed, logs, backup/restauração, persistência, worker e smoke passaram. Playwright: 26 cenários DEMO passaram, com dois exclusivos OIDC ignorados.
- [Job oidc](https://github.com/luizmaoki/SistemaSinais/actions/runs/39938471944/job/120363761621): Keycloak real, 21 cenários passaram, com sete exclusivos DEMO ignorados. Login Alice/Bob, isolamento, CSRF, persistência e revogação foram validados.
- A suíte tem 28 cenários web distintos entre os dois modos. As contagens compartilham testes de interface e proxy.
- O relatório remoto capitalverify0aeb92d13ec6 passou; foundation-report publica somente JSON, sem dumps ou configurações locais, com retenção de sete dias.

Duas revisões independentes aprovaram as correções sem bloqueantes. A revisão de contratos repetiu 21 testes; a financeira/dados repetiu 42 testes com rede desativada. As provas Coinbase usaram apenas transporte e dados sintéticos. O commit posterior de documentação não modifica o código testado.

Entrega: [PR 2](https://github.com/luizmaoki/SistemaSinais/pull/2), baseado no PR 1 de autenticação ainda aberto. Não houve merge ou deploy em produção. O ambiente local foi atualizado para 0003 após backup verificado, com preservação dos dados anteriores e novo backup/restauração de 20 tabelas. Aplicação em http://localhost:13000/login.

O passo 3 está concluído para o processamento local descrito em docs/catalog-step-3.md. Preços reais, cobertura completa, novos calendários e contratos de fornecedores continuam como dependências de etapas posteriores.
