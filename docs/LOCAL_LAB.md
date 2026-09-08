# Laboratório operacional sem conta AWS

O objetivo é explorar a aplicação com dados fictícios e efeitos verificáveis: consultar,
corrigir, transformar, enfileirar, notificar e reutilizar um procedimento salvo.

## Iniciar

Instale **Python 3.12+** e **Docker com Compose v2**. No Windows/macOS, inicie o Docker
Desktop com containers Linux. No Linux, o usuário precisa conseguir executar `docker info`.
Não é necessário instalar banco, AWS CLI, configurar credenciais ou criar uma conta externa.

```powershell
.\setup.cmd --local
```

```bash
bash setup.sh --local
# Alternativa para qualquer sistema:
python scripts/setup.py --local
```

Abra `http://127.0.0.1:8501`. O setup cria/reutiliza o venv, instala os pacotes, baixa as
imagens, aguarda a saúde dos serviços, cria recursos/dados ausentes e publica quatro fluxos.
A primeira instalação depende de internet e espaço para as imagens Docker. `--local
--install-only` prepara tudo sem abrir a aplicação. `--local --run-only` evita reinstalar
pacotes; verifica/inicia os serviços e repõe apenas fixtures ausentes.

**Moto Server 5.2.3** emula AWS em `127.0.0.1:5000`. O SDK usa exclusivamente credenciais
fictícias e esse endpoint no modo `local`. O backend real continua separado no modo `aws`.
O runtime da Lambda é executado de verdade em outro container Docker; não usamos a opção
que apenas retorna sucesso fictício. Não existe consumidor automático das filas neste lab.

O PostgreSQL local em `127.0.0.1:55432` guarda drafts, versões, execuções e aprovações em um
volume persistente. `local_app.py` e o seed escolhem explicitamente esse banco, ignorando
um eventual DSN de outro ambiente. A conta emulada é `123456789012`, região `sa-east-1`.

## Catálogo reutilizável e fallback do navegador

Ao salvar ou publicar um runbook no modo local/AWS, o host sincroniza uma cópia de baixo volume
na tabela DynamoDB `flowops-runbook-catalog` (ou no nome definido por `FLOWOPS_CATALOG_TABLE`).
Se a tabela não existir, ela é criada sob demanda com `PAY_PER_REQUEST`; se estiver indisponível,
o editor grava automaticamente uma cópia limitada no `localStorage` do navegador. A cópia fica
isolada por origem, conta e usuário, pode ser restaurada como um novo draft e sobrevive a fechar
e reabrir o navegador. Limpar os dados do site, trocar de navegador/dispositivo ou uma política
do navegador pode removê-la.

Esse catálogo é um índice de definições, não o diário operacional: Repository/PostgreSQL mantém
drafts, versões, snapshots, checkpoints, aprovações e auditoria. Portanto um refresh ou o
fechamento do navegador não interrompe uma execução já submetida. Não são colocados no navegador
credenciais, receipt handles ou saídas brutas de AWS.

Para testar a recuperação, interrompa o endpoint Moto ou use um nome de tabela inválido apenas
no ambiente local, salve uma alteração, feche/reabra o navegador e restaure a cópia pelo painel
**Browser-local copies**. Corrija a causa, salve novamente e a cópia poderá ser sincronizada ao
DynamoDB; a restauração sempre cria outro draft para evitar sobrescrever uma versão histórica.

## Recursos

| Serviço | Recursos | Finalidade |
|---|---|---|
| DynamoDB | `flowops-payments`, índice `status-index` | Pagamentos e consulta por estado |
| DynamoDB | `flowops-customers` | Cliente ativo/inativo para enriquecimento e validação |
| DynamoDB | `flowops-receipts` | Recibo da recuperação, gravado em transação com a conclusão |
| DynamoDB | `flowops-lab-seed` | Controle da carga inicial de mensagens |
| SQS | `flowops-payment-events.fifo` | Eventos de pagamentos recuperados |
| SQS | `flowops-recovery-requests.fifo` | Pedidos de recuperação em lote e redrive |
| SQS | `flowops-payment-errors.fifo` | Duas mensagens de erro para reenvio |
| SNS + SQS | `flowops-payment-notifications` → `flowops-notification-audit` | Notificação com entrega verificável na fila |
| S3 | `flowops-evidence` | JSON de evidências por pagamento |
| Lambda | `flowops-prepare-payment` | Validação de negócio e formatação do evento |

Os nomes e os dados podem ser usados nas ações do editor. Valores DynamoDB preservam o
contrato do SDK: `Item.paymentId.S`, `Item.amount.N`, `Item.active.BOOL`. Uma expressão
completa como `{{ nodes.prepare_event.output.Payload.event }}` transporta um objeto;
`MessageBody`, `Message` e `Payload` aceitam esse objeto e o provider serializa JSON.

## Jornada XPTO

1. Em **Runbooks**, abra **XPTO - Recuperar pagamento parado** e explore o editor.
2. Em **Execute**, escolha a versão 1, `payment_id=PAY-1001`, mantenha
   `expected_status=PROCESSING` e preencha o motivo. Desative a simulação para produzir
   efeitos no emulador. Confirme que o banner mostra **LOCAL**.
3. O fluxo consulta pagamento/cliente e para em **Approvals**. Revise e aprove.
4. Em **Executions**, confira nós e saídas: reserva condicional → Lambda → SQS → SNS → S3
   → transação DynamoDB → leitura final `PROCESSED`.
5. Execute **Inventário - Conferir recursos e recibos** para ver pagamentos, recibos,
   filas, funções, tópicos e objetos S3 em leituras reunidas.
6. Use **Run again** no XPTO. Os mesmos parâmetros usam a mesma versão imutável; um
   pagamento `PROCESSED` termina em `already_done`, sem republicar os eventos.
7. Volte a **Execute**, altere para `PAY-1002` e execute. O mesmo fluxo recupera outro
   pagamento; a Lambda classifica o valor maior como prioridade `high`.
8. Clone/edite o runbook, renomeie, salve o draft e publique uma nova versão. Execuções
   antigas continuam mostrando sua definição original. Use import/export para transportar
   a definição para outra instalação e revise nomes/URLs/ARNs antes de executá-la.

| Entrada/caso | Resultado esperado |
|---|---|
| `PAY-1001`, `PAY-1002` | Recuperação completa, recibo, evidência e mensagens |
| `PAY-1003`, `PAY-1004` | Outros registros disponíveis para testes e modificações |
| `PAY-2001` ou reexecução de pagamento recuperado | Termina em `already_done`, sem novas publicações |
| `PAY-3001` | `unsupported_status`: não elegível, nenhuma correção |
| `PAY-4001` | Falha de validação do cliente inativo antes da aprovação |
| `PAY-5001` | Lambda realmente falha; compensação libera a reserva e execução termina `FAILED` |
| `MISSING` | Falha em `record_exists`, sem mutações |
| `PAY-1003`, `expected_status=WRONG` | Conflito condicional, sem reserva nem publicação |
| Rejeitar a aprovação | A execução não prossegue para a correção |
| Duas pessoas executando sobre o mesmo registro | A condição de reserva impede duas recuperações concorrentes |

A compensação da Lambda é específica dessa função pura do lab: ela não realiza efeitos
externos e só libera a reserva pertencente àquela execução. Falhas depois de SQS/SNS/S3
podem deixar efeitos parciais e exigem reconciliação; não há transação distribuída entre
os cinco serviços. FIFO possui uma janela limitada de deduplicação e SNS pode entregar
mais de uma vez. Não use esses exemplos como garantia de processamento exatamente uma vez.

## Lotes, filas e controle de fluxo

**Triagem - Consultar e enfileirar lote** consulta o GSI de status com limite, filtra pelo
cliente, transforma cada item, divide lotes e executa `SendMessageBatch` em `For Each`.
Execute antes das recuperações individuais para observar quatro pedidos do cliente
`CUS-001`. Use `batch_size` de 1 a 10, limite até 100 e `wait_seconds=30` para exercitar
cancelamento após a aprovação. Um limite excessivo falha antes de qualquer envio.
As mensagens são pedidos para um consumidor futuro; enfileirar não altera o pagamento.

**DLQ - Reenviar mensagens com revisão** recebe até três mensagens, reenvia à fila de
pedidos e só então apaga as originais. A fila vazia segue para End. Se uma publicação falhar,
as originais ficam disponíveis novamente após o prazo de visibilidade. A ação composta `sqs.redrive_messages` mantém ReceiptHandle apenas em memória, sem
transportá-lo pelo histórico ou por expressões do runbook. O reenvio pode
produzir duplicatas; o consumidor precisa ser idempotente.

**Inventário** exercita `Parallel`/`Merge` com leituras dos cinco serviços. O XPTO usa
`Switch`, `Validation`, aprovação, condição DynamoDB e `Compensation`. A triagem usa
`Retry` apenas na consulta idempotente. Retry de mutação sem garantia de idempotência
continua bloqueado pelas políticas da aplicação.

A simulação FlowOps nunca chama mutações. No emulador, ela não inventa o resultado de uma
Lambda ou de uma escrita: um nó posterior dependente desse resultado pode falhar por
campo ausente. Para validar o cenário completo use execução local efetiva; para exploração
sem efeitos, use Inventário e consultas. Isso é diferente de `DryRun` nativo da AWS.

## Fechar, reabrir e recomeçar

Ctrl+C fecha a aplicação; os containers continuam disponíveis. Para parar os serviços:

```bash
python scripts/setup.py --stop-local
```

O volume PostgreSQL preserva fluxos, versões e histórico ao fechar/reiniciar o computador.
Moto guarda os recursos AWS em memória: se o processo do emulador reiniciar, o próximo
setup recria as fixtures iniciais. Portanto o histórico pode registrar efeitos de um estado
anterior do emulador. O seed nunca sobrescreve um pagamento, função ou runbook já existente,
nem repõe mensagens consumidas enquanto o emulador permanece ativo.

Para recomeçar **apenas os recursos AWS fictícios**, com execuções locais encerradas:

```bash
docker compose -f compose.local.yml restart aws
python scripts/setup.py --local --run-only
```

Não apague o volume PostgreSQL se quiser manter seus fluxos. Portas ocupadas, Docker parado,
permissão no socket ou download de imagem falho interrompem o setup com erro. Resolva a
causa e execute novamente; a aplicação não inicia parcialmente configurada.

## Integração posterior no ECS

A integração empresarial continua usando `FlowOpsPage` com identidade autenticada do host,
`AWSContext(mode="aws", account_id=..., region=...)`, task role e rede da empresa. Não leve
`local_app.py`, credenciais fictícias, endpoints loopback ou Compose para produção. O acesso
às tabelas de negócio é por ações do provider, com IAM e verificação de conta/região.
Aurora não faz parte do catálogo curado atual; uma ação SQL exigiria contrato, credenciais,
limites e revisão próprios. O armazenamento durável do motor usa PostgreSQL, podendo
reutilizar uma instalação Aurora PostgreSQL compatível após validação da empresa.

O modo local permite um operador aprovar a própria execução para testar a tela. AWS real
mantém a política de aprovação por outra pessoa. Não há mudança de schema SQL nesta etapa;
o modo `local` é aditivo nos snapshots. Para rollback para uma versão antiga, encerre as
execuções locais e mantenha seu banco separado, pois binários antigos não reconhecem esse modo.

Moto é um emulador, não prova de equivalência de IAM, concorrência, quotas, latência ou todos
os detalhes dos serviços AWS. A CI testa chamadas HTTP e efeitos no emulador, inclusive o
container da Lambda; a homologação final na conta corporativa continua necessária.
