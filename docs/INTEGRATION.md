# Integração com Streamlit existente

## Contrato recomendado

O host deve conhecer somente a identidade autenticada do usuário e o contexto AWS permitido.
A fronteira pública é `FlowOpsPage`:

```python
from flowops.domain.models import AWSContext, Identity
from flowops.streamlit import FlowOpsPage

identity = Identity(
    id=current_user.email,
    display_name=current_user.name,
    roles=["OPERATOR"],
    teams=["payments"],
)

context = AWSContext(
    environment="staging",
    account_id="123456789012",
    region="sa-east-1",
    mode="aws",
    profile="payments-staging",
)

FlowOpsPage(identity, context).render()
```

`Repository`, `Engine`, `LocalWorker`, action registry e boto3 são montados internamente. O
banco é resolvido por `FLOWOPS_DATABASE_URL` ou `FLOWOPS_DATABASE`.

## Responsabilidades do host

O host deve:

- autenticar o usuário;
- mapear grupos/claims corporativos para roles e teams FlowOps no servidor;
- escolher `AWSContext` a partir de configuração confiável;
- não aceitar role/profile/account/permissions diretamente de query params ou campos editáveis;
- disponibilizar credenciais AWS temporárias ao processo por profile/role/provider chain;
- fornecer PostgreSQL compartilhado quando houver múltiplas instâncias.

FlowOps reaplica RBAC e policy no engine; a segurança não depende apenas do host nem da UI.

## Permissões adicionais

O argumento `permissions` pode complementar roles quando o host usa grants mais granulares:

```python
FlowOpsPage(
    identity,
    context,
    permissions=["runbook.read", "runbook.execute.staging", "aws.read"],
).render()
```

Evite construir essa lista a partir de input do navegador.

## Generic AWS Action

Ações não curadas só entram no registry quando o host as allowlista:

```python
FlowOpsPage(
    identity,
    context,
    generic_allowlist={
        "ec2.describe_instances",
        "cloudwatch.describe_alarms",
    },
).render()
```

Mantenha a allowlist em código/configuração versionada e sujeita a review. Serviços sensíveis
continuam bloqueados pelo catálogo mesmo que apareçam na lista.

## Runtime injetado

Testes ou hosts avançados podem fornecer `repository=` ou `runtime=` explicitamente. Esse é um
escape hatch para composição, não o caminho normal de integração.

```python
FlowOpsPage(identity, context, runtime=my_runtime).render()
```

## Navegação

O componente renderiza sua navegação dentro da sidebar do Streamlit. Se o host já controla
navegação global, invoque `FlowOpsPage.render()` somente quando a rota/página FlowOps estiver
ativa. Não recrie regras de execução no roteador do host.

## Ciclo de vida

O runtime é cacheado na sessão Streamlit por fingerprint do backend/contexto/allowlist. Estado
durável permanece no banco. Reruns não submetem execução nem persistem mudanças sem submit
explícito.

## Ambientes

Prefira uma configuração de contexto por ambiente/conta em vez de permitir digitação livre.
Produção adiciona confirmação explícita na UI, mas ainda depende de RBAC, policy, aprovação e
IAM.
