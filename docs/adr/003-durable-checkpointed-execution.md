# ADR 003 — Execução durável com checkpoints

- Status: Accepted
- Date: 2026-09-06

## Contexto

Runbooks operacionais não podem depender da memória de uma sessão Streamlit nem reiniciar do
zero após crash, pausa para aprovação ou restart do processo.

## Decisão

Submissões, snapshots, status, checkpoints por nó, cancelamento, aprovações e locks são
persistidos. O worker faz claim transacional e reconstrói resultados concluídos na retomada.
Retries automáticos ficam limitados a ações idempotentes e erros transitórios permitidos.

## Consequências

- restart do processo não perde fila PENDING;
- passos concluídos não precisam ser repetidos;
- ações mutáveis exigem semântica explícita de idempotência;
- o banco passa a ser componente crítico e deve ser PostgreSQL em deployment compartilhado.
