# AWS FlowOps Studio

AWS FlowOps Studio transforma procedimentos operacionais em runbooks visuais, versionados,
auditáveis e governados. O domínio, o motor de execução, as políticas e a persistência são
Python puro; Streamlit é apenas uma camada de apresentação e pode rodar standalone ou ser
embutido em uma aplicação existente.

## O que está incluído

- editor visual de DAG com Start, End/Stop, Condition, Validation, Wait, For Each, Retry e
  Manual Approval;
- drafts com controle otimista de concorrência e versões publicadas imutáveis;
- execução assíncrona durável com checkpoints por nó, retomada, cancelamento e locks por
  conta/região;
- simulação FlowOps sem mutações reais e separada do `DryRun` nativo dos serviços AWS;
- RBAC, escopo por equipe, proteção de produção, `aws.destructive`, limites de impacto e
  two-person approval;
- auditoria contextual WHO / WHAT / WHEN / WHERE / WHY / RESULT com redaction central;
- ações curadas para DynamoDB, SQS, SNS, Lambda e S3, mais operações botocore adicionais
  somente quando allowlisted pelo host;
- credenciais boto3 por profile, role/AssumeRole ou provider chain; credenciais estáticas não
  são persistidas pelo FlowOps;
- SQLite para desenvolvimento/local e PostgreSQL para implantação compartilhada;
- templates Blank, Fix Stuck Payment, Lambda Invoke, Replay Event, DLQ Redrive e DynamoDB
  Record Correction;
- modo demo determinístico, inclusive para fluxos de mutação simulada, sem conta AWS.

## Requisitos

- Python 3.12+;
- para modo AWS, credenciais disponíveis ao processo via mecanismos padrão do boto3;
- para persistência PostgreSQL, o extra `postgres`.

## Rodar standalone em modo demo

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -e '.[dev]'
streamlit run standalone_app.py
```

Por padrão o arquivo local é `flowops.db`. Para alterar:

```bash
export FLOWOPS_DATABASE=/var/lib/flowops/flowops.db
streamlit run standalone_app.py
```

Para PostgreSQL:

```bash
python -m pip install -e '.[postgres]'
export FLOWOPS_DATABASE_URL='postgresql://flowops:password@db.internal:5432/flowops'
streamlit run standalone_app.py
```

O DSN é usado somente pela camada de persistência e não é exposto em chaves de sessão ou
logs do FlowOps. As migrations numeradas em `flowops/persistence/migrations/` são aplicadas
automaticamente uma única vez.

## Embutir em outro Streamlit

A fronteira pública principal é `FlowOpsPage`. O host fornece identidade e contexto AWS já
confiáveis; não precisa conhecer Repository, Engine, worker ou boto3 internamente.

```python
from flowops.domain.models import AWSContext, Identity
from flowops.streamlit import FlowOpsPage

user = Identity(
    id="sylvio@example.com",
    display_name="Sylvio",
    roles=["OPERATOR", "APPROVER"],
    teams=["payments"],
)

context = AWSContext(
    environment="staging",
    account_id="123456789012",
    region="sa-east-1",
    mode="aws",
    profile="operations-staging",
)

FlowOpsPage(user=user, aws_context=context).render()
```

O host continua responsável por autenticação, autorização de entrada na aplicação e pela
origem confiável dos dados de `Identity`/`AWSContext`. As políticas de operação do FlowOps são
aplicadas novamente no engine.

### Operações AWS genéricas

A UI mostra ações curadas por padrão. Para expor uma operação adicional presente no modelo
botocore, o host precisa allowlistá-la explicitamente:

```python
FlowOpsPage(
    user=user,
    aws_context=context,
    generic_allowlist={"ec2.describe_instances"},
).render()
```

Serviços sensíveis como IAM, STS, Organizations, Account, Secrets Manager e SSO permanecem
bloqueados. Operações genéricas desconhecidas são tratadas de modo conservador como críticas,
mutáveis e não idempotentes.

## Credenciais AWS

`AWSContext` pode usar profile, role ARN ou a provider chain padrão do boto3. Em modo AWS o
backend valida a identidade com STS e confere a conta esperada antes de executar ações. URLs,
ARNs e recursos relevantes também passam por validações de escopo quando aplicável.

Não coloque access keys, secret keys, session tokens ou segredos em runbooks, parâmetros de
exportação ou código. Use IAM roles, profiles ou o mecanismo de credenciais da plataforma em
que o Streamlit estiver implantado.

Veja `docs/SECURITY.md` e `docs/OPERATIONS.md` para o modelo de segurança e a operação em
produção.

## Produção

Uma execução real em `production` exige, cumulativamente:

1. permissão `runbook.execute.production`;
2. runbook permitindo o ambiente production;
3. motivo/change reference;
4. na UI, confirmação digitada `PRODUCTION` e a conta AWS alvo exata;
5. `aws.write` para mutações e `aws.destructive` para ações críticas;
6. aprovação quando exigida pela política; por padrão a aprovação respeita two-person rule;
7. limites de impacto configurados pela policy.

A simulação FlowOps não chama operações mutáveis reais. Ela é uma proteção do orquestrador e
não deve ser confundida com parâmetros `DryRun` específicos de alguns serviços AWS.

## Persistência

SQLite é adequado para desenvolvimento, demo e uma única instância local. Para múltiplos
processos/instâncias ou implantação compartilhada use PostgreSQL. O mesmo contrato cobre:

- drafts e versões;
- fila e snapshots de execução;
- checkpoints por nó;
- locks de escopo;
- aprovações;
- auditoria;
- fixtures do modo demo.

A CI sobe PostgreSQL 16 real e executa um fluxo dry-run e uma execução live de core para
validar migrations, queries e semântica de lock em ambos os bancos.

## Templates e demo

O template **Fix Stuck Payment** é o cenário E2E de referência: valida ambiente, lê o pagamento,
verifica `PROCESSING`, passa por aprovação, atualiza condicionalmente, emite evento SQS, espera,
relê e valida `PROCESSED`. Em simulação, o backend demo mantém estado isolado por execução e
não altera a fixture persistente.

Os templates DLQ Redrive e DynamoDB Record Correction são destinados ao modo AWS e exigem
parâmetros explícitos e as políticas correspondentes.

## Qualidade e testes

```bash
python -m pip install -e '.[dev,postgres]'
ruff format --check .
ruff check .
mypy flowops
pytest --cov=flowops --cov-report=term-missing
bandit -r flowops -ll
pip-audit
python -m build
```

Para executar também o teste PostgreSQL localmente:

```bash
export FLOWOPS_TEST_POSTGRES_DSN='postgresql://flowops:flowops@localhost:5432/flowops'
pytest tests/test_postgres.py -v
```

A pipeline `.github/workflows/quality.yml` executa todos esses gates e provisiona PostgreSQL
16 como service container.

## Documentação

- `docs/ARCHITECTURE.md` — camadas, runtime e fluxo de execução;
- `docs/SECURITY.md` — credenciais, RBAC, aprovações, secrets e produção;
- `docs/OPERATIONS.md` — configuração, banco, troubleshooting e implantação;
- `docs/PROGRESS.md` — evidências incrementais de implementação;
- `docs/adr/` — decisões arquiteturais 001–010.

## Limites intencionais

FlowOps não é um gerenciador de segredos, não cria identidade corporativa, não substitui IAM e
não tenta suportar qualquer operação AWS de forma irrestrita. A superfície genérica é
allowlistada e fail-closed. Operações reais devem ser executadas com least privilege e com um
banco PostgreSQL compartilhado quando houver mais de uma instância do aplicativo.
