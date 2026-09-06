# Segurança

## Princípios

FlowOps adota fail-closed, least privilege, defesa em profundidade e separação entre identidade
do host, autorização do FlowOps e permissões IAM da credencial usada pelo processo.

## Identidade e RBAC

O host autentica o usuário e constrói `Identity` com `id`, roles, teams e grants opcionais.
FlowOps não confia apenas na visibilidade da UI: o engine reaplica as permissões antes de
submeter ou executar uma ação.

Roles padrão:

- VIEWER: leitura de runbooks;
- AUTHOR: leitura, edição e publicação;
- OPERATOR: leitura, execução dev/staging, leitura/escrita AWS;
- APPROVER: leitura e aprovação dev/staging/production;
- ADMIN: grant global.

Roles são aditivas. Runbooks podem ser limitados por equipe. Produção exige permissão explícita
`runbook.execute.production`.

## Ações destrutivas e impacto

Mutações requerem `aws.write`. Ações críticas requerem ainda `aws.destructive`. A policy pode
limitar `estimated_affected`; operações acima do limite falham antes do provider. Mutações em
produção, ações críticas e operações acima do threshold de aprovação exigem decisão humana.

## Produção

A UI exige `PRODUCTION` digitado e a conta de 12 dígitos para uma execução live em ambiente
production. O engine também exige reason/change reference e as permissões correspondentes.
Essa confirmação visual não substitui policy nem IAM; é apenas uma camada adicional.

## Two-person approval

Com `two_person=True`, o solicitante não pode aprovar a própria mudança. A aprovação é
vinculada ao digest do snapshot, contexto e inputs resolvidos. Alterações materiais geram outro
digest e invalidam a decisão anterior.

## Credenciais AWS

Não armazene access key, secret key ou session token em FlowOps. O backend usa as fontes
padrão do boto3:

- profile local/gerenciado;
- role ARN com AssumeRole;
- credential provider chain da plataforma (por exemplo instance/task/IRSA credentials).

Antes de executar em modo AWS, o backend usa STS para confirmar a conta esperada. Contextos
são fornecidos pelo host e devem ser tratados como configuração confiável.

## Escopo de recursos

O provider valida conta/região e, quando possível, ARNs, URLs de filas, bucket owner e outros
identificadores antes da chamada. O objetivo é impedir que parâmetros de um runbook desviem a
execução para outro contexto autorizado pela mesma credencial.

## Operações genéricas

Ações curadas são preferidas. Operações adicionais via botocore exigem `generic_allowlist` do
host no formato `service.operation`. Serviços que podem alterar autoridade do worker ou expor
segredos permanecem bloqueados, incluindo IAM, STS, Organizations, Account, Secrets Manager e
SSO.

Uma operação genérica sem metadata curada é classificada como CRITICAL, mutável e não
idempotente. Assim ela exige grants/aprovações conservadores em vez de assumir que uma operação
com nome aparentemente inofensivo é segura.

## Segredos e dados sensíveis

- export/import de runbook rejeita formatos com campos de segredo conhecidos;
- auditoria passa por sanitização central antes da persistência;
- nomes como password/token/secret/authorization são redigidos;
- padrões de Bearer token e outros valores sensíveis são mascarados;
- outputs/previews são limitados para impedir logs sem limite.

Mesmo com redaction, não use FlowOps como transporte de segredos. Referencie identificadores de
recursos ou mecanismos externos de secret delivery quando uma aplicação operacional precisar
de segredo.

## Simulação

`dry_run=True` é simulação FlowOps e evita a chamada `execute` de ações mutáveis. A implementação
demo simula os efeitos em estado isolado por execução. Ações de leitura podem consultar o
provider porque não são mutações. Não confunda esse mecanismo com opções `DryRun` específicas
de alguns serviços AWS.

## Persistência

Para múltiplas instâncias use PostgreSQL com TLS e credenciais de banco gerenciadas pela
plataforma. Restrinja o usuário do banco ao schema FlowOps. Backups e retenção da auditoria
fazem parte da operação da plataforma e devem obedecer à política corporativa.

## Auditoria

Eventos registram ator, evento, timestamp, execução e contexto operacional. Para execução e
aprovação são preservados environment, account, region, reason e result. Payloads são
sanitizados antes do insert.

## Recomendações de IAM

Crie roles por ambiente e conceda somente as operações realmente expostas aos runbooks. Evite
wildcards amplos. Separe produção de não produção e use trust policies restritas ao runtime.
O catálogo mostra as permissões esperadas por ação, mas a policy IAM final continua sob
responsabilidade da plataforma.

## Resposta a incidentes

Em suspeita de abuso:

1. revogue/rotacione a role ou credencial do runtime;
2. suspenda execução live no host;
3. preserve banco e audit events;
4. correlacione execution id com CloudTrail;
5. arquive runbooks envolvidos sem apagar versões publicadas;
6. só reabilite após corrigir policy/allowlist/IAM e validar a suíte.
