# ADR 008 — SQLite local e PostgreSQL compartilhado

- Status: Accepted
- Date: 2026-09-06

## Contexto

A experiência standalone precisa de zero infraestrutura, mas execução por múltiplas instâncias
precisa de persistência e concorrência compartilhadas.

## Decisão

SQLite permanece o backend local/demo. PostgreSQL é suportado como backend de produção usando
o mesmo Repository e migrations SQL portáveis, com um pequeno adapter DB-API para placeholders
e rows. A CI provisiona PostgreSQL real e executa testes de migrations, engine e locks.

## Consequências

- desenvolvimento não exige banco externo;
- deployment horizontal deve usar PostgreSQL;
- novas queries/migrations precisam continuar compatíveis com os dois backends ou introduzir
  abstração explícita;
- portabilidade é verificada em CI, não apenas assumida pela sintaxe.
