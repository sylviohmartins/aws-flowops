# ADR 009 — Simulação FlowOps distinta de DryRun nativo

- Status: Accepted
- Date: 2026-09-06

## Contexto

Nem todos os serviços AWS implementam `DryRun`, e um runbook precisa validar seu fluxo sem
executar mutações reais. Ao mesmo tempo, simular apenas respostas vazias impediria testar
passos posteriores que dependem do efeito lógico de uma mutação.

## Decisão

`Execution.dry_run` representa simulação do orquestrador. Para ações mutáveis, o engine chama
`preview()` e não `execute()`. O backend demo mantém cópia de estado isolada por execução e
permite transições simuladas sem alterar a fixture persistente. Qualquer `DryRun` específico de
serviço AWS continua sendo outra funcionalidade.

## Consequências

- operadores podem validar o fluxo sem mutação real;
- a UI deve nomear claramente a simulação FlowOps;
- um preview não prova que IAM/condições reais de uma mutação AWS terão sucesso;
- testes E2E podem verificar efeitos lógicos e também provar que o estado persistente não foi
  alterado.
