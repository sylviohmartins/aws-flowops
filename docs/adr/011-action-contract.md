# ADR 011 — Contrato extensível de Action

- Status: Accepted
- Date: 2026-09-06

## Decisão

O core conhece `Action`, `ActionContext`, `Metadata` e `ActionRegistry`. Providers implementam
`validate`, `preview` e `execute`; transporte, credenciais e adaptação de payload pertencem
ao provider. A UI descobre catálogo e schemas pelo registro, incluindo os mesmos schemas no
modo demo. Campos de mensagens aceitam objetos/arrays Python que o provider converte em JSON.

Um provider que encapsula operações em lote deve implementar `affected_records(config)`.
A policy avalia o impacto total antes de executar; `For Each` soma o impacto de todos os itens
e vincula uma aprovação ao conjunto. O contrato padrão de uma Action simples é um recurso.

## Consequências

HTTP, SQL ou outros providers podem usar o mesmo engine sem importar boto3 no core. Uma nova
ação ainda precisa de metadata conservadora, schemas, estimativa de impacto quando composta e
testes de autorização, simulação, falhas parciais e limites. O registro não é uma autorização
para carregar código arbitrário enviado pelo usuário.
