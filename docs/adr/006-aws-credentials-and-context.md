# ADR 006 — Credenciais efêmeras e contexto AWS confiável

- Status: Accepted
- Date: 2026-09-06

## Contexto

O produto precisa operar em múltiplas contas/regiões sem virar um cofre de access keys nem
permitir que parâmetros do runbook escolham arbitrariamente outra conta.

## Decisão

FlowOps não persiste credenciais AWS. O runtime usa profile, AssumeRole ou provider chain do
boto3. `AWSContext` é fornecido por configuração confiável do host. Em modo AWS o provider
valida a identidade via STS e verifica conta/região/identificadores de recursos quando
aplicável.

## Consequências

- segredos de autenticação permanecem na plataforma/IAM;
- a mesma credencial não autoriza silenciosamente desvio de contexto;
- o host precisa proteger a origem do `AWSContext` e não aceitá-lo diretamente de input não
  confiável do navegador.
