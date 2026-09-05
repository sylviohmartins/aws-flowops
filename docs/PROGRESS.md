# Registro de implementação e evidências

## Etapa 1 — base e persistência

Implementados contratos versionados, migrations, drafts com controle de concorrência,
publicação imutável, arquivo/exclusão lógica, auditoria transacional e fronteira de integração.
UI inicial cria e lista runbooks com submit explícito.

Validação local: unittest (migration idempotente, histórico imutável, concorrência, busca,
arquivo e importação embutida); compileall. Dependências Streamlit/boto3 e ferramentas
externas não estavam instaladas e o download local foi bloqueado pela rede. CI será usada
para verificar as dependências reais. Essa restrição não é evidência de sucesso de UI.

## Plano

1. Base, persistência e interface inicial.
2. DAG, expressões, mapeamento e canvas.
3. Engine, worker e checkpoints.
4. Provider e ações AWS.
5. Políticas, RBAC, aprovações e auditoria.
6. Interface completa, integração e templates.
7. Demonstração E2E, regressão e documentação.

## Etapa 2 — grafo, expressões e canvas

DAG determinístico, rejeição de ciclos/desconexões/edges inválidos, referências somente a
ancestrais, parâmetros tipados e DSL sem execução arbitrária de código. Canvas permanece
encapsulado atrás de contrato Python defensivo e serialização versionada.

## Etapa 3 — execução

Engine independente, worker em thread pool, fila persistente com claim transacional, token
de submissão e conflito em replay incompatível. Checkpoints por nó, reconstrução após pausa,
branches, execução paralela de leituras, mutações serializadas por conta/região, cancelamento
e simulação explícita. Retry exige idempotência e erro transitório permitido. Manual Approval
é persistida e vinculada ao digest do snapshot/contexto/inputs.

Testes locais: 16 testes cumulativos passando, incluindo corrida entre workers, nenhuma
mutação em simulação, aprovação por outra pessoa, cancelamento e retries.

## Etapa 4 — AWS

Catálogo real de 71 ações em DynamoDB, SQS, SNS, Lambda e S3. Modelos botocore descobrem
serviços, operações, schemas e campos obrigatórios. Generic AWS exige allowlist do host e
assume risco crítico para operações desconhecidas. Adapter boto3 verifica STS, contexto,
URLs, ARNs e bucket owner, limita paginação/streams e desativa retries implícitos do SDK.

Backend demo declara operações suportadas e rejeita as demais; nenhuma chamada a conta AWS
real é necessária para a suíte. O commit corretivo `33325a5` fechou a etapa com a pipeline
Quality integralmente verde: format, lint, mypy, 25 testes com coverage, Bandit, pip-audit e
build.

## Etapa 5 — políticas, RBAC, aprovações e auditoria

RBAC permanece fail-closed, com escopo por equipe, permissão explícita de execução em
produção e grant separado para ações destrutivas. Produção exige motivo para mutação real;
ações críticas, mutações em produção e operações acima do limiar passam por aprovação.

O preview de aprovação passa a ser persistido e contém o contexto operacional necessário
para revisão: runbook/versão, ambiente, conta, região, motivo, ação, risco, impacto estimado e
parâmetros já submetidos à sanitização central. A decisão continua vinculada ao digest do
snapshot/contexto/input e respeita two-person rule.

Auditoria passa a registrar de forma consistente WHO/WHAT/WHEN/WHERE/WHY/RESULT através do
ator/evento/timestamp existentes e do corpo contextual enriquecido para execução, nodes,
aprovações, cancelamento e conclusão. Payloads continuam limitados/redigidos pelo mecanismo
central de sanitização.

Validação da etapa 5 deve cobrir RBAC, produção, destructive grant, bulk limit, migration do
preview, persistência/reabertura de aprovação, two-person rule e contexto/resultados de
auditoria antes do próximo slice.
