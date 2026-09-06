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

## Etapa 6 — workspace Streamlit, integração e templates

A camada de apresentação agora oferece Dashboard, catálogo de Runbooks, Editor visual,
execução, histórico/checkpoints, aprovações, auditoria e Resource Explorer, preservando o
engine/domínio fora do Streamlit. Alterações duráveis permanecem dependentes de submit
explícito. O editor mantém working copy em sessão, valida o DAG antes de persistir, expõe
parâmetros, configuração por nó, política de falha e retry, e impede publicação com alterações
não salvas.

A execução diferencia explicitamente simulação FlowOps de `DryRun` nativo de serviços AWS.
Execução real em produção exige confirmação digitada `PRODUCTION` e a conta AWS de 12 dígitos,
além das políticas/RBAC/aprovações do engine. O cancelamento da UI passa pelo `Engine.cancel`,
sem acesso direto ao store. Importações não podem ampliar silenciosamente o escopo de equipe
do usuário.

Export/import determinístico em YAML/JSON, runtime compartilhável entre standalone e host,
backend demo com estado de simulação isolado por execução e templates reutilizáveis foram
adicionados. Os templates incluem Blank, Fix Stuck Payment, Lambda Invoke, Replay Event,
DLQ Redrive e DynamoDB Record Correction. O DLQ Redrive separa URL de inspeção do ARN de
origem e usa destino explícito para produzir uma chamada SDK válida.

Evidência da branch no SHA `7508a23`: workflow Quality `34009887428` integralmente verde;
44 arquivos já formatados, Ruff sem violações, mypy sem issues em 30 source files, 37 testes
passando em 6,97 s, coverage total de 63%, Bandit sem findings, `pip-audit` sem vulnerabilidades
conhecidas nas dependências auditáveis e build de sdist/wheel concluído com sucesso.

## Etapa 7 — hardening de produção, E2E e entrega

A persistência agora suporta SQLite e PostgreSQL reais pelo mesmo contrato transacional. A CI
provisiona PostgreSQL 16 e valida migrations, round-trip do repositório, execução dry-run e
execução live com aquisição/liberação de locks. O DSN não é exposto na identificação pública
do Repository.

O editor recebeu Data Mapper orientado pelos schemas de botocore: browser de campos, tipos,
required/default/enum/documentação, autocomplete de parâmetros/contexto/outputs ancestrais,
preview de mapping e validação fail-closed de incompatibilidades de tipos conhecidas. Import de
Runbook passa por estratégia explícita de `schema_version`/`node_version`; versões futuras ou
antigas sem migration registrada são rejeitadas em vez de reinterpretadas silenciosamente.

O engine ganhou rotas `FAIL_BRANCH` explícitas e `core.compensation`: uma falha pode seguir
somente pela aresta `failure`, enquanto a Action compensatória usa o mesmo caminho governado de
policy, approval, simulation e retry das demais Actions. Não há promessa de rollback
transacional. Correlation context fornecido pelo host é persistido, exposto ao DSL e propagado
como message attributes em SQS/SNS quando tecnicamente suportado.

Observabilidade passa a emitir audit events também como JSON sanitizado e fornece snapshot das
métricas canônicas de execução/nodes/AWS calls. O Dashboard apresenta métricas, runbooks mais
utilizados, falhas e execução por ambiente. O histórico ganhou filtros por usuário, período,
status, ambiente, runbook e conta, além de duração, drill-down, input/output sanitizados e
visualização readonly do DAG com status dos nodes.

A fronteira de embedding aceita identidade, permissões, contexto AWS e correlation context sem
expor Repository/Engine/boto3 ao host. Generic AWS Action continua require allowlist explícita e
serviços sensíveis permanecem fail-closed. Sessões/clientes AWS são liberados após o worker.
Produção mantém confirmação digitada, RBAC, destructive grant, limites e two-person approval.

A documentação final inclui README, Architecture, Security, Operations, Development,
Deployment, Integration, IAM, Testing, Contributing e ADRs 001–010.

Evidência final da branch no SHA `3f5c89e`: workflow Quality `34012271755` integralmente verde.
Ruff confirmou 77 arquivos formatados e lint sem violações; mypy reportou zero issues em 37
source files; **53/53 testes** passaram em 8,81 s, incluindo PostgreSQL 16, Fix Stuck Payment,
AWS fakes/stubs, mapping, migrations, failure/compensation, observability/correlation e smoke
Streamlit. Cobertura real: **65,89%** (floor 60%), com engine 81%, graph 82%, policies 93%,
security 90%, observability 90%, execution store 92% e AWS actions 81%. Bandit não identificou
issues em 4.828 linhas de código, `pip-audit` não encontrou vulnerabilidades conhecidas nas
dependências auditáveis e o build produziu sdist e wheel com sucesso.
