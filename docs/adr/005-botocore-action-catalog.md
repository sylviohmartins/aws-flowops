# ADR 005 — Catálogo AWS curado com schemas botocore

- Status: Accepted
- Date: 2026-09-06

## Contexto

Duplicar manualmente todos os schemas AWS envelhece rápido, mas expor o SDK inteiro sem
metadata de risco cria uma superfície operacional perigosa.

## Decisão

Ações principais de DynamoDB, SQS, SNS, Lambda e S3 são curadas com metadata explícita. Os
modelos botocore fornecem descoberta/validação de serviços, operações, campos e tipos. Uma
operação genérica só é registrada após allowlist do host e recebe classificação conservadora
quando não existe metadata curada.

## Consequências

- schemas acompanham o SDK instalado sem liberar o SDK inteiro;
- risco, idempotência e permissões continuam decisões do produto;
- serviços de autoridade/segredo podem permanecer bloqueados independentemente do botocore.
