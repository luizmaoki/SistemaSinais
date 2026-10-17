# CI remota do passo 2

Validada em 17 de outubro de 2026 no código e612462b83e28ba960e1c649ef1facb3657d8d49.

- [Execução 39045560779](https://github.com/luizmaoki/SistemaSinais/actions/runs/39045560779): jobs checks e oidc concluídos com success.
- [Job checks](https://github.com/luizmaoki/SistemaSinais/actions/runs/39045560779/job/117433459498): 116 testes backend, nove operacionais, Ruff, lint, TypeScript, build, instalação limpa, migrações, seed, logs, backup/restauração, persistência, smoke Celery e 16 cenários web demo passaram. Dois cenários exclusivamente OIDC foram ignorados nesse modo.
- [Job oidc](https://github.com/luizmaoki/SistemaSinais/actions/runs/39045560779/job/117433459199): Keycloak real, 12 cenários web passaram, incluindo login Alice/Bob, persistência, isolamento, CSRF e revogação de sessão. Seis cenários exclusivamente demo foram ignorados.
- A suíte tem 18 cenários web distintos, cobertos entre os dois modos; as contagens de cada execução compartilham os testes de interface e proxy.
- O artifact foundation-report contém somente relatórios JSON e tem retenção de sete dias. Dumps, configurações locais e tokens não são publicados nesse artifact.

As duas revisões independentes de domínio e infraestrutura aprovaram o código, incluindo as correções finais. A revisão de documentação que registra esta evidência não modifica o código testado.

Entrega para revisão: [PR 1](https://github.com/luizmaoki/SistemaSinais/pull/1). Não houve merge ou deploy em produção. O ambiente local permanece em http://localhost:13000/login.
