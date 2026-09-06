# Operação e implantação

## Modos suportados

### Demo/local

Use SQLite e `AWSContext(mode="demo")`. Não requer credenciais AWS e é adequado para
avaliação, desenvolvimento e testes funcionais.

### AWS compartilhado

Use PostgreSQL e `AWSContext(mode="aws")`. O host deve fornecer identidade autenticada,
contexto AWS confiável e credenciais via provider chain/profile/role.

## Variáveis de ambiente

- `FLOWOPS_DATABASE`: caminho SQLite local;
- `FLOWOPS_DATABASE_URL`: DSN PostgreSQL; tem precedência sobre `FLOWOPS_DATABASE`;
- `FLOWOPS_TEST_POSTGRES_DSN`: DSN usado apenas pela suíte de integração PostgreSQL.

Não coloque access keys AWS nessas variáveis de configuração do produto.

## PostgreSQL

Instale:

```bash
python -m pip install -e '.[postgres]'
```

Configure:

```bash
export FLOWOPS_DATABASE_URL='postgresql://flowops:password@postgres.internal:5432/flowops'
```

Recomendações:

- PostgreSQL 16 ou compatível;
- TLS obrigatório fora de rede local controlada;
- usuário dedicado ao schema/tabelas FlowOps;
- backup e point-in-time recovery conforme criticidade;
- monitorar conexões, latência e crescimento de `audit_events`/`node_executions`;
- DSN entregue por secret manager da plataforma, nunca versionado.

As migrations são executadas no bootstrap e registradas em `schema_versions`. Faça backup
antes de atualização de produção e execute uma instância de migração controlada antes de
liberar múltiplas réplicas quando o ambiente exigir change management estrito.

## SQLite

SQLite abre uma conexão curta por transação e usa WAL/locking do próprio arquivo conforme a
plataforma. Não use `:memory:` porque workers e sessões precisam compartilhar persistência.
Para múltiplos processos/containers prefira PostgreSQL.

## AWS

### Profile

Defina `AWSContext(profile="nome", mode="aws", ...)`. O profile precisa existir no ambiente do
processo.

### AssumeRole

Defina o role ARN no contexto suportado pela aplicação host. A credencial de origem deve ter
somente `sts:AssumeRole` para a role permitida.

### Provider chain

Em workloads AWS, prefira credenciais temporárias da plataforma. O boto3 pode resolver a
provider chain padrão; FlowOps valida a conta real com STS antes da operação.

## Embedding

No Streamlit corporativo:

```python
FlowOpsPage(user=identity, aws_context=context).render()
```

A aplicação host deve construir `identity` e `context` a partir de fontes autenticadas. Não
aceite account, role, profile ou roles de RBAC diretamente de query params/client-side sem
validação do servidor.

Se precisar expor uma operação botocore adicional:

```python
FlowOpsPage(
    user=identity,
    aws_context=context,
    generic_allowlist={"ec2.describe_instances"},
).render()
```

Mantenha a allowlist em configuração versionada/revisada, não em input do operador.

## Rollout recomendado

1. instalar release em ambiente dev com modo demo e executar suíte;
2. validar PostgreSQL/migrations;
3. integrar identidade do host e roles/teams;
4. configurar contextos AWS de dev com IAM mínimo;
5. executar templates/read-only e simulações;
6. habilitar staging live;
7. revisar allowlists e policies;
8. habilitar produção somente após confirmação de CloudTrail, auditoria e two-person approval.

## Observabilidade

O banco guarda status e checkpoints duráveis. Em produção, complemente com logs estruturados
do processo e métricas da plataforma para:

- backlog de PENDING;
- quantidade/duração de RUNNING;
- WAITING_APPROVAL envelhecidas;
- failures por action id;
- latência de banco;
- falhas STS/AssumeRole;
- crescimento de audit events;
- restarts de processo/worker.

Use execution id como chave de correlação com logs do runtime e CloudTrail.

## Recovery

O worker reconstrói execuções pendentes a partir da persistência ao iniciar. Checkpoints por
nó evitam repetir etapas já concluídas. Retries automáticos só ocorrem para ações declaradas
idempotentes e erros transitórios permitidos.

O runtime inicia um dispatcher periódico de PENDING; um lock ocupado não exige um novo clique
na UI para liberar a fila posteriormente. O descarte do runtime encerra esse dispatcher sem
cancelar trabalhos já submetidos. Hosts que injetam runtimes duradouros devem chamar `close()`
no encerramento controlado. Erros temporários de acesso ao banco são registrados sem DSN e o
dispatcher tenta novamente.

Falhas de provider com `MANUAL_INTERVENTION` geram aprovação contendo o erro, contexto e input
do passo inteiro. O aprovador deve confirmar a reconciliação externa e registrar o motivo.
O engine continua sem repetir chamadas nem preencher outputs AWS desconhecidos. Use uma
leitura seguida de Validation para verificar o resultado operacional da intervenção.

Depois de crash/restart:

1. confirme banco disponível;
2. suba a mesma versão compatível da aplicação;
3. verifique PENDING/RUNNING/WAITING_APPROVAL;
4. confirme que não há mudança de IAM/contexto inesperada;
5. deixe `dispatch_pending()` reencaminhar PENDING;
6. investigue RUNNING antigos antes de intervenção manual.

## Troubleshooting

### `Published definition integrity check failed`

A versão publicada armazenada não corresponde ao digest. Trate como integridade comprometida;
não edite a linha manualmente. Restaure backup ou publique nova versão a partir de fonte
confiável após investigação.

### `Draft changed in another session`

Conflito otimista. Recarregue o draft, reconcilie mudanças e salve novamente.

### `Execution is not waiting for approval`

A aprovação está stale ou a execução já foi decidida/cancelada. Reabra o histórico e use o
preview atual.

### conta AWS divergente

O STS retornou conta diferente da configurada. Corrija profile/role/contexto; não contorne a
validação.

### ação genérica não aparece

Ela precisa existir no modelo botocore, não estar em serviço bloqueado e constar em
`generic_allowlist` no bootstrap do host.

### PostgreSQL falha no startup

Verifique DSN, DNS, TLS, usuário e migrations. A CI usa PostgreSQL real para detectar queries
não portáveis; reproduza com `FLOWOPS_TEST_POSTGRES_DSN` e `pytest tests/test_postgres.py -v`.

## Upgrade e rollback

Antes de upgrade:

- backup do PostgreSQL;
- quality workflow verde;
- revisar migrations e ADRs;
- evitar rollback de binário através de uma migration incompatível sem plano explícito.

Runbooks publicados são imutáveis; rollback operacional normalmente significa selecionar uma
versão anterior compatível para nova execução, não alterar a versão histórica.
