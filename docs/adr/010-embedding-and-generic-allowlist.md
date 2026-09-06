# ADR 010 — Embedding simples e extensão AWS allowlisted

- Status: Accepted
- Date: 2026-09-06

## Contexto

O componente precisa ser acoplado a um Streamlit existente sem exigir que o host monte engine,
repository, worker e provider manualmente. Ao mesmo tempo, a facilidade de integração não pode
abrir automaticamente todo o SDK AWS.

## Decisão

A API de embedding principal é `FlowOpsPage(user, aws_context, permissions=...)`. Persistência
é resolvida por configuração de ambiente e o runtime é criado/cached internamente. Hosts
avançados ainda podem injetar Repository/Runtime. Operações botocore não curadas só são
registradas por `generic_allowlist` explícita e versionável do host.

## Consequências

- integração normal conhece identidade/contexto, não detalhes internos;
- standalone e embedded compartilham o mesmo runtime;
- extensão AWS é opt-in e pode passar por code review/config review;
- serviços bloqueados e classificação conservadora continuam valendo mesmo quando o host pede
  uma operação genérica.
