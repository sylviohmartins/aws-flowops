# ADR 004 — DSL de expressões sem execução arbitrária

- Status: Accepted
- Date: 2026-09-06

## Contexto

Nós precisam referenciar parâmetros, contexto e outputs anteriores. Aceitar Python arbitrário,
`eval` ou templates com execução de código ampliaria drasticamente a superfície de ataque.

## Decisão

FlowOps suporta apenas resolução controlada de caminhos/templates e operadores lógicos
implementados pelo core. O validador permite referências apenas a parâmetros/contexto e nós
ancestrais válidos.

## Consequências

- não há execução arbitrária de código a partir de um runbook;
- ciclos de dependência lógica e referências futuras são rejeitados;
- novas capacidades de expressão devem ser adicionadas explicitamente ao DSL, com testes e
  limites, em vez de abrir um interpretador genérico.
