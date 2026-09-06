# ADR 007 — RBAC, policy e aprovações em camadas

- Status: Accepted
- Date: 2026-09-06

## Contexto

Ocultar botões não é autorização suficiente para operações AWS. Produção, ações destrutivas e
mudanças de alto impacto precisam de controles independentes do frontend.

## Decisão

Roles/grants aditivos, escopo por equipe e policies são avaliados no core/engine. Produção tem
permissão explícita e reason obrigatório para execução real. Ações críticas requerem
`aws.destructive`. Policies podem impor limite de impacto e aprovação. Aprovações são
persistidas, vinculadas a digest e, por padrão, respeitam two-person rule.

## Consequências

- a UI pode melhorar a experiência, mas não é a fronteira de segurança;
- aprovação stale não autoriza inputs diferentes;
- operadores e aprovadores podem ser segregados por identidade/roles;
- IAM continua sendo uma camada adicional, não substituída pelo RBAC do FlowOps.
