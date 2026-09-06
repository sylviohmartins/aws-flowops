# Aceitação do AWS FlowOps Studio

Esta matriz relaciona o prompt mestre (seções 0–129) ao produto executável e às evidências de
verificação. Os requisitos de processo estão consolidados no ciclo de CI e no contrato de
conclusão; requisitos explicitamente futuros não são apresentados como funcionalidades prontas.

## Matriz de requisitos

| ID | Seções do prompt | Resultado verificável | Evidência principal |
| --- | --- | --- | --- |
| REQ-001 | 0–6, 66, 93, 116–123 | Python-first; standalone e embedding por `FlowOpsPage`, com identidade e contexto fornecidos pelo host | `application.py`, `streamlit/integration.py`, `test_application.py`, `test_streamlit_integration_coverage.py` |
| REQ-002 | 8–9, 65, 99–102 | Canvas com seleção de propriedades, movimento, conexões, exclusão, duplicação, zoom/pan/minimap; formulários tipados e JSON; estado de edição por sessão | `streamlit/canvas.py`, `ui.py`, `typed_inputs.py`, `test_release_ui.py`, `test_typed_inputs.py`, `scripts/browser_acceptance.py` |
| REQ-003 | 10–15, 114–115 | Registry extensível, 66 ações curadas: DynamoDB 15, SQS 14, SNS 10, Lambda 18, S3 9; catálogo botocore e Generic Action opt-in | `core/actions.py`, `providers/aws/catalog.py`, `actions.py`, `resources.py`, `test_aws.py`, `test_aws_actions_coverage.py` |
| REQ-004 | 16–19 | DAG acíclico; caminhos seguros; autocomplete de fontes ancestrais; tipos/defaults/documentação; arrays/objetos convertidos para mensagens JSON | `core/graph.py`, `expressions.py`, `mapping.py`, `test_graph.py`, `test_mapping.py`, navegador |
| REQ-005 | 18, 25–27, 44–50 | Start/End, Condition, Switch, Filter, Map, For Each, Batch, Parallel, Merge, Wait, Retry, Stop, Validation, Approval e Compensation | `core/logic.py`, `engine.py`, `test_engine.py`, `test_engine_coverage.py`, `test_failure_paths.py` |
| REQ-006 | 20–24, 51–52, 61 | CRUD, clone, archive/delete lógico, pesquisa, drafts concorrentes, versões imutáveis, snapshots e import/export determinístico | `persistence/repository.py`, `core/serialization.py`, `test_repository.py`, `test_serialization.py`, `test_streamlit_business_journeys.py` |
| REQ-007 | 25–30, 49–50, 53, 99 | Execução assíncrona, token de submissão, claim/locks, fila persistente, cancelamento, checkpoints, histórico e reexecução | `core/worker.py`, `persistence/executions.py`, `test_engine.py`, `test_release_engine.py`, `test_release_ui.py` |
| REQ-008 | 31–41, 56–57, 96–97 | RBAC/teams, reason, escopo de conta/região, IAM, confirmação de produção inclusive em replay, destructive grant, aprovações vinculadas a digest e two-person | `core/policies.py`, `engine.py`, `providers/aws/backend.py`, `test_policies.py`, `test_approval_audit.py`, `test_hardening.py`, `test_release_ui.py` |
| REQ-009 | 42–43, 89–90 | Simulação FlowOps isolada, separada do DryRun nativo; nenhuma mutação AWS necessária para testes | `providers/aws/demo.py`, `test_application.py`, `test_demo_coverage.py`, `test_aws_backend_coverage.py` |
| REQ-010 | 44–48 | Retries idempotentes limitados, falhas parciais preservadas, limites agregados de lote/iteração, chunking, intervalo configurável e reconciliação humana sem repetir chamada falha | `core/engine.py`, `providers/aws/actions.py`, `test_release_engine.py`, `test_failure_paths.py` |
| REQ-011 | 51–52, 91, 103–106 | SQLite/PostgreSQL, migrations ordenadas, versões de schema/node, redaction e limites de payload | `persistence/`, `core/migrations.py`, `security.py`, `test_postgres.py`, `test_migrations.py`, `test_persistence_coverage.py` |
| REQ-012 | 54–58 | Auditoria contextual, métricas, duração/erros por nó, ator/versão/conta e correlation context | `observability.py`, `streamlit/workspace.py`, `test_observability.py`, `test_correlation.py` |
| REQ-013 | 7, 59, 76–77, 90 | Fix Stuck Payment completo em demo; também Blank, Lambda Invoke, Replay Event, DLQ Redrive e Record Correction | `templates.py`, `test_application.py`, `test_streamlit_business_journeys.py`; DLQ/Record Correction exigem recursos AWS para execução real |
| REQ-014 | 64 | Lambda CURRENT/PROPOSED/diff, configuração, runtime, versões, aliases, layers e metadados de código; ZIP/S3/container; vínculo ao RevisionId | `providers/aws/lambda_review.py`, `streamlit/lambda_review.py`, `test_lambda_review.py`, `test_release_ui.py` |
| REQ-015 | 67–73, 78–88, 107–108 | Format, lint, mypy, testes, cobertura mínima de 96%, segurança, dependências, PostgreSQL real, build e navegador Chromium | `.github/workflows/quality.yml`, `docs/TESTING.md` |
| REQ-016 | 74–75, 92–95, 109–113, 124–129 | Documentação de arquitetura/segurança/desenvolvimento/deployment, ADRs, comandos reproduzíveis, riscos e evidências; promoção da árvore validada | `README.md`, `CONTRIBUTING.md`, `docs/`, `.agents/rules/change-promotion.md` |
| REQ-017 | 60, 62–63 | Contratos permitem extensão futura para subflows/providers e GitOps por exportação revisável; operação AWS separada de IaC | ADRs 001, 002, 005, 010, 011, 012; não inclui um orquestrador de subflows ou integração GitOps automática |
| REQ-018 | 98, 100–101, 105 | Limites de grafo, payload, paginação, paralelismo, lote, intervalo e cache por contexto; cleanup de sessões AWS/workers | `core/graph.py`, `engine.py`, `worker.py`, `providers/aws/backend.py`, `streamlit/integration.py`, `test_hardening.py`, `test_release_engine.py` |

## Percurso de navegador

`python scripts/browser_acceptance.py` inicia um processo Streamlit real e Chromium. O percurso
cria um runbook, insere GetItem e SendMessage, seleciona nós no iframe, configura inputs,
mapeia `Item` para `MessageBody`, arrasta, conecta/desconecta, valida, salva, publica, executa,
abre o histórico e reexecuta. As screenshots, o resultado JSON e o log do servidor ficam no
artefato `browser-evidence` da CI. AppTest cobre adicionalmente approvals, Lambda, typed inputs,
produção e embedding.

Estado da aceitação de navegador: **VALIDATING**. A etapa só pode ser promovida com esse gate
verde na árvore candidata e novamente no SHA de `main`.

## Limites operacionais explícitos

- A CI usa SDK models/Stubber/fakes, PostgreSQL real e demo. IAM efetivo, CloudTrail, SSO do
  host e efeitos em recursos reais exigem homologação na conta sandbox da organização.
- Generic Action não libera todos os serviços. Serviços de autoridade/segredos permanecem
  bloqueados e operações desconhecidas são críticas, mutáveis e sem retry automático.
- A simulação AWS real é um plano; não reproduz todo o estado da AWS. A demonstração de
  transições de pagamento pertence ao backend demo.
- Um crash com uma chamada ainda `RUNNING` exige reconciliação operacional. Não há garantia
  universal de exactly-once nem rollback transacional entre serviços AWS.
- `MANUAL_INTERVENTION` aguarda um aprovador atestar reconciliação externa do passo inteiro.
  A continuação retorna apenas `{manual_intervention: true, reconciled: true}`; resultados AWS
  ausentes não são inventados. Um nó de leitura/validação deve verificar o estado reconciliado.
- O diff Lambda compara configuração e metadados/referências de artefatos. Não baixa código
  por URL pré-assinada e não presume edição inline de ZIPs ou containers. Fixe versões S3 ou
  digests ECR no runbook e use `RevisionId` para evitar alterações concorrentes.
- O worker é local ao processo, com fila/checkpoints duráveis. PostgreSQL e um runtime
  controlado pelo host são apropriados para uso compartilhado; executor distribuído dedicado,
  subflows compostos e publicação GitOps automática são pontos de extensão explícitos.
- Alinhamento automático, snapping e multisseleção são itens desejáveis do prompt, não gates
  de aceitação. Drag, pan, zoom, minimap e edição individual são suportados.

## Impacto e rollback da etapa 9

Não há migration nova, mudança em credenciais ou provisionamento AWS nesta etapa. Definições e
IDs de checkpoints existentes são preservados. A atualização acrescenta controles de UI,
contagem de impacto, reconciliação, retenção de resultados e dreno periódico de PENDING. A fila
consulta os IDs pendentes antes de aplicar seu limite por rodada; execuções concluídas no
histórico não ocultam trabalho antigo. O comportamento é exercitado em SQLite e PostgreSQL
por `test_pending_queue.py`, com 2.000 registros concluídos mais recentes que o pendente.

Rollback do aplicativo: retornar ao commit validado anterior, após drenar as execuções que
usam a nova reconciliação manual. Não restaurar ou reescrever versões publicadas. A aprovação
em andamento com `intervention` requer finalizar/cancelar antes de voltar a um binário que
não reconheça esse marcador.
