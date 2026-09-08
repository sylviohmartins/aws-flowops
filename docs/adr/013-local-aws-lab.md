# ADR 013 — Laboratório AWS sem conta externa

Status: accepted.

## Contexto

A POC precisa exercitar chamadas SDK e efeitos entre serviços sem acesso a uma conta AWS.
A simulação interna não valida transporte HTTP, contratos reais nem execução de Lambda.

## Decisão

Adicionar `AWSContext.mode=local`, com backend dedicado a `http://127.0.0.1:5000`, conta
fictícia, ambiente dev e credenciais explicitamente locais. O modo AWS real continua
ignorando endpoints configurados externamente e validando identidade por STS.

Usar Moto Server 5.2.3 em Docker, Lambda Python 3.12 executada em container e PostgreSQL 16
em volume persistente. Não desativar `use_docker`. O setup inicia e verifica os serviços,
semeia recursos/dados ausentes e publica definições ordinárias editáveis.

## Consequências

Docker e downloads iniciais são necessários; nenhuma conta AWS ou conta de serviço externo
é necessária. Moto perde recursos ao reiniciar, enquanto o PostgreSQL preserva o histórico.
O socket Docker dá ao emulador capacidade de criar containers: este Compose é somente para
máquina de desenvolvimento com código fictício confiável, não um isolamento multiusuário.
As portas ficam vinculadas a loopback. Não há qualquer implantação ou chamada a AWS real.

A validação expôs dois defeitos: o schema da saída Lambda não refletia o JSON decodificado,
e o ramo `default` de Switch rodava mesmo quando um caso havia sido selecionado. Corrigir
esses comportamentos e testar o fallback exclusivo, inclusive após retomar uma aprovação.
Campos JSON dinâmicos são verificados em runtime; campos conhecidos continuam fail-closed.

Adicionar a ação composta `sqs.redrive_messages`: no máximo 10 mensagens, sem retry
automático, confirmação apenas após todos os envios, ReceiptHandle só em memória. Seus
efeitos parciais são explícitos e exigem reconciliação. Isso não simula a API AWS
`StartMessageMoveTask`, não implementada nessa versão de Moto.

Não há migração SQL. Snapshots novos podem conter modo local e ação composta; rollback
para binários anteriores requer encerrar essas execuções e preservar o banco do lab
separadamente. Runbooks com Switch devem usar default como fallback, conforme o contrato
pretendido; a correção impede efeitos indevidos no ramo alternativo.

## Referências

- https://docs.getmoto.org/en/latest/docs/server_mode.html
- https://docs.getmoto.org/en/latest/docs/services/lambda.html
- https://docs.getmoto.org/en/latest/docs/services/sqs.html
- https://github.com/getmoto/moto/releases/tag/5.2.3
