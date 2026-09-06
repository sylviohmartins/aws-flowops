# IAM least privilege

FlowOps não concede permissões AWS. O runtime usa a identidade IAM já fornecida pela
plataforma; portanto, a role deve permitir somente as operações e recursos que os runbooks
daquele ambiente realmente precisam.

## Estratégia recomendada

1. crie roles separadas para dev, staging e production;
2. restrinja a trust policy ao workload que executa FlowOps;
3. conceda `sts:GetCallerIdentity` para validação de conta;
4. acrescente apenas as ações AWS efetivamente expostas aos runbooks;
5. restrinja `Resource` para tabelas, filas, tópicos, funções e buckets permitidos;
6. mantenha produção mais restrita que não produção;
7. correlacione executions com CloudTrail;
8. revise a policy sempre que o `generic_allowlist` mudar.

## Exemplo reduzido

Este exemplo é deliberadamente específico e deve ser adaptado aos recursos reais:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "VerifyIdentity",
      "Effect": "Allow",
      "Action": "sts:GetCallerIdentity",
      "Resource": "*"
    },
    {
      "Sid": "PaymentTable",
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:UpdateItem"
      ],
      "Resource": "arn:aws:dynamodb:sa-east-1:123456789012:table/payments"
    },
    {
      "Sid": "PaymentEvents",
      "Effect": "Allow",
      "Action": [
        "sqs:GetQueueAttributes",
        "sqs:SendMessage"
      ],
      "Resource": "arn:aws:sqs:sa-east-1:123456789012:payments-events"
    }
  ]
}
```

Não use esse exemplo como policy universal. Ele serve para mostrar o formato de least
privilege de um único runbook.

## AssumeRole

Quando o runtime assume uma role alvo, a identidade de origem deve receber somente
`sts:AssumeRole` para os ARNs aprovados. A role alvo contém as permissões de operação. Evite
permitir `sts:AssumeRole` para `*`.

## Leitura versus mutação

Mantenha políticas IAM alinhadas às responsabilidades organizacionais. Um usuário FlowOps pode
ter `aws.write` no RBAC, mas a operação ainda falhará se a role IAM não autorizar o recurso. O
inverso também é intencional: uma role IAM ampla não contorna RBAC/policy/aprovação do FlowOps.

## Ações destrutivas

Para ações classificadas como CRITICAL, prefira roles/policies específicas e escopo de recurso
estreito. `aws.destructive` é um grant do FlowOps e não substitui uma IAM policy restrita.

## Generic AWS Action

Cada entrada adicionada a `generic_allowlist` precisa de revisão IAM correspondente. Como uma
ação genérica desconhecida é tratada conservadoramente pelo FlowOps, não amplie a IAM policy
com wildcards apenas para evitar falhas de autorização.

## S3

Para S3, diferencie permissões sobre bucket e objetos:

- operações de listagem/configuração normalmente usam ARN do bucket;
- leitura/escrita de objetos normalmente usa `arn:aws:s3:::bucket/prefix/*`.

Restrinja prefixos quando o runbook operar apenas uma parte do bucket.

## SQS/SNS/Lambda/DynamoDB

Prefira ARNs explícitos ou padrões de recurso por ambiente. Evite uma única role compartilhada
entre contas. Se o fluxo precisa de poucos recursos, liste-os nominalmente.

## Validação

Antes de habilitar production live:

- execute leituras no contexto esperado;
- execute simulação FlowOps;
- valide a role com ferramentas IAM/Access Analyzer da organização;
- confirme CloudTrail para chamadas reais em staging;
- teste que recursos fora do escopo são negados.
