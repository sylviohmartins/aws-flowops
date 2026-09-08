"""Ordinary, editable runbooks for the seeded local payments business scenario."""

from typing import Any

from flowops.domain.models import Edge, Node, Parameter, Runbook

ACCOUNT = "123456789012"
REGION = "sa-east-1"
QUEUE_ROOT = f"http://127.0.0.1:5000/{ACCOUNT}"
TOPIC = f"arn:aws:sns:{REGION}:{ACCOUNT}:flowops-payment-notifications"


def _book(
    identifier: str, name: str, description: str, parameters: dict[str, Parameter]
) -> Runbook:
    return Runbook(
        id=identifier,
        name=name,
        description=description,
        owner="local-operator",
        team="default",
        tags=["lab", "payments"],
        environments=["dev"],
        parameters=parameters,
    )


def _node(
    identifier: str, action: str, config: dict[str, Any] | None = None, **kwargs: Any
) -> Node:
    return Node(
        id=identifier,
        action=action,
        label=identifier.replace("_", " "),
        config=config or {},
        **kwargs,
    )


def _layout(book: Runbook) -> Runbook:
    # A vertical canvas remains usable for long operational flows.
    for index, node in enumerate(book.nodes):
        node.position = (80 + (index % 2) * 300, index * 155)
    return book


def _chain(book: Runbook, nodes: list[Node]) -> Runbook:
    book.nodes = nodes
    book.edges = [Edge(source=a.id, target=b.id) for a, b in zip(nodes, nodes[1:], strict=False)]
    return _layout(book)


def payment_key() -> dict[str, Any]:
    return {"paymentId": {"S": "{{ params.payment_id }}"}}


def recovery() -> Runbook:
    book = _book(
        "lab-recover-payment",
        "XPTO - Recuperar pagamento parado",
        "Consulta pagamento e cliente; aprova, reserva com condição, executa Lambda, "
        "envia SQS/SNS, salva evidência S3 e conclui pagamento + recibo em transação. "
        "PROCESSED não republica; falha da Lambda libera a reserva e falha a execução.",
        {
            "payment_id": Parameter(
                default="PAY-1001",
                description="PAY-1001/1002 sucesso; 2001 processado; 3001 cancelado; 4001 cliente inativo; 5001 falha Lambda",
            ),
            "expected_status": Parameter(
                default="PROCESSING",
                description="Condição de concorrência; use outro valor para provocar conflito",
            ),
            "reason": Parameter(
                default="Recuperação operacional local",
                description="Motivo incluído no evento e na evidência",
            ),
        },
    )
    claim = {
        "TableName": "flowops-payments",
        "Key": payment_key(),
        "ConditionExpression": "#s = :expected",
        "UpdateExpression": "SET #s = :next, recoveryId = :owner",
        "ExpressionAttributeNames": {"#s": "status"},
        "ExpressionAttributeValues": {
            ":expected": {"S": "{{ params.expected_status }}"},
            ":next": {"S": "RETRY_REQUESTED"},
            ":owner": {"S": "{{ context.execution_id }}"},
        },
        "ReturnValues": "ALL_NEW",
    }
    owned = {"#s": "status"}
    values = {":reserved": {"S": "RETRY_REQUESTED"}, ":owner": {"S": "{{ context.execution_id }}"}}
    condition = "#s = :reserved AND recoveryId = :owner"
    book.nodes = [
        _node("start", "core.start"),
        _node(
            "payment",
            "dynamodb.get_item",
            {"TableName": "flowops-payments", "Key": payment_key(), "ConsistentRead": True},
        ),
        _node(
            "record_exists",
            "core.validation",
            {"left": "{{ nodes.payment.output }}", "operator": "contains", "right": "Item"},
        ),
        _node(
            "route_status",
            "core.switch",
            {
                "value": "{{ nodes.payment.output.Item.status.S }}",
                "cases": {"recover": "PROCESSING", "done": "PROCESSED"},
            },
        ),
        _node(
            "already_done",
            "core.end",
            {"value": {"reason": "Pagamento já processado; nenhum evento foi republicado."}},
        ),
        _node(
            "unsupported_status",
            "core.stop",
            {"reason": "Estado não elegível; verifique o registro antes de corrigir."},
        ),
        _node(
            "customer",
            "dynamodb.get_item",
            {
                "TableName": "flowops-customers",
                "Key": {"customerId": {"S": "{{ nodes.payment.output.Item.customerId.S }}"}},
            },
        ),
        _node(
            "active_customer",
            "core.validation",
            {"left": "{{ nodes.customer.output.Item.active.BOOL }}", "right": True},
        ),
        _node(
            "approve",
            "core.approval",
            {"message": "Revisar pagamento, cliente e motivo antes da recuperação."},
        ),
        _node("claim", "dynamodb.update_item", claim),
        _node(
            "prepare_event",
            "lambda.invoke",
            {
                "FunctionName": "flowops-prepare-payment",
                "InvocationType": "RequestResponse",
                "Payload": {
                    "payment": "{{ nodes.payment.output.Item }}",
                    "customer": "{{ nodes.customer.output.Item }}",
                    "reason": "{{ params.reason }}",
                    "execution_id": "{{ context.execution_id }}",
                },
            },
            failure_policy="FAIL_BRANCH",
        ),
        _node(
            "send_event",
            "sqs.send_message",
            {
                "QueueUrl": f"{QUEUE_ROOT}/flowops-payment-events.fifo",
                "MessageBody": "{{ nodes.prepare_event.output.Payload.event }}",
                "MessageGroupId": "payments",
                "MessageDeduplicationId": "recovered-{{ params.payment_id }}",
            },
        ),
        _node(
            "notify",
            "sns.publish",
            {"TopicArn": TOPIC, "Message": "{{ nodes.prepare_event.output.Payload.event }}"},
        ),
        _node(
            "evidence",
            "s3.put_object",
            {
                "Bucket": "flowops-evidence",
                "Key": "recoveries/{{ params.payment_id }}.json",
                "Body": "{{ nodes.prepare_event.output.Payload.evidence_json }}",
                "ContentType": "application/json",
            },
        ),
        _node(
            "complete",
            "dynamodb.transact_write_items",
            {
                "TransactItems": [
                    {
                        "Update": {
                            "TableName": "flowops-payments",
                            "Key": payment_key(),
                            "ConditionExpression": condition,
                            "UpdateExpression": "SET #s = :done",
                            "ExpressionAttributeNames": owned,
                            "ExpressionAttributeValues": values | {":done": {"S": "PROCESSED"}},
                        }
                    },
                    {
                        "Put": {
                            "TableName": "flowops-receipts",
                            "Item": {
                                "paymentId": {"S": "{{ params.payment_id }}"},
                                "executionId": {"S": "{{ context.execution_id }}"},
                                "evidenceKey": {"S": "recoveries/{{ params.payment_id }}.json"},
                            },
                            "ConditionExpression": "attribute_not_exists(paymentId)",
                        }
                    },
                ]
            },
        ),
        _node(
            "verify",
            "dynamodb.get_item",
            {"TableName": "flowops-payments", "Key": payment_key(), "ConsistentRead": True},
        ),
        _node(
            "validate_done",
            "core.validation",
            {"left": "{{ nodes.verify.output.Item.status.S }}", "right": "PROCESSED"},
        ),
        _node("end", "core.end"),
        _node(
            "release_claim",
            "core.compensation",
            {
                "action": "dynamodb.update_item",
                "config": {
                    "TableName": "flowops-payments",
                    "Key": payment_key(),
                    "ConditionExpression": condition,
                    "UpdateExpression": "SET #s = :original REMOVE recoveryId",
                    "ExpressionAttributeNames": owned,
                    "ExpressionAttributeValues": values | {":original": {"S": "PROCESSING"}},
                    "ReturnValues": "ALL_NEW",
                },
            },
        ),
        _node("report_failure", "core.validation", {"left": False, "right": True}),
        _node("failed_end", "core.stop", {"reason": "Lambda falhou; reserva liberada."}),
    ]
    chains = [
        ["start", "payment", "record_exists", "route_status"],
        [
            "customer",
            "active_customer",
            "approve",
            "claim",
            "prepare_event",
            "send_event",
            "notify",
            "evidence",
            "complete",
            "verify",
            "validate_done",
            "end",
        ],
        ["release_claim", "report_failure", "failed_end"],
    ]
    book.edges = [
        Edge(source=a, target=b) for chain in chains for a, b in zip(chain, chain[1:], strict=False)
    ] + [
        Edge(source="route_status", target="customer", branch="recover"),
        Edge(source="route_status", target="already_done", branch="done"),
        Edge(source="route_status", target="unsupported_status", branch="default"),
        Edge(source="prepare_event", target="release_claim", branch="failure"),
    ]
    return _layout(book)


def triage() -> Runbook:
    book = _book(
        "lab-triage-batch",
        "Triagem - Consultar e enfileirar lote",
        "Consulta índice de status, filtra cliente, transforma JSON, divide lotes e enfileira pedidos. Não processa pagamentos automaticamente.",
        {
            "status": Parameter(default="PROCESSING"),
            "customer_id": Parameter(default="CUS-001"),
            "limit": Parameter(type="integer", default=20),
            "batch_size": Parameter(type="integer", default=2),
            "wait_seconds": Parameter(
                type="integer",
                default=0,
                description="Use 30 para exercitar cancelamento antes dos envios",
            ),
        },
    )
    return _chain(
        book,
        [
            _node("start", "core.start"),
            _node(
                "query",
                "core.retry",
                {
                    "action": "dynamodb.query",
                    "config": {
                        "TableName": "flowops-payments",
                        "IndexName": "status-index",
                        "KeyConditionExpression": "#s = :status",
                        "ExpressionAttributeNames": {"#s": "status"},
                        "ExpressionAttributeValues": {":status": {"S": "{{ params.status }}"}},
                        "Limit": "{{ params.limit }}",
                    },
                    "retry": {"max_attempts": 2},
                },
            ),
            _node(
                "filter_customer",
                "core.filter",
                {
                    "items": "{{ nodes.query.output.Items }}",
                    "path": "customerId.S",
                    "value": "{{ params.customer_id }}",
                },
            ),
            _node(
                "format_requests",
                "core.map",
                {
                    "items": "{{ nodes.filter_customer.output.items }}",
                    "template": {
                        "Id": "{{ item.paymentId.S }}",
                        "MessageBody": {
                            "payment_id": "{{ item.paymentId.S }}",
                            "operation": "recover",
                        },
                        "MessageGroupId": "recoveries",
                        "MessageDeduplicationId": "request-{{ item.paymentId.S }}",
                    },
                },
            ),
            _node(
                "batch",
                "core.batch",
                {
                    "items": "{{ nodes.format_requests.output.items }}",
                    "size": "{{ params.batch_size }}",
                },
            ),
            _node(
                "approve",
                "core.approval",
                {"message": "Revisar os pedidos e os lotes antes de enviar."},
            ),
            _node("wait", "core.wait", {"seconds": "{{ params.wait_seconds }}"}),
            _node(
                "send_batches",
                "core.for_each",
                {
                    "items": "{{ nodes.batch.output.batches }}",
                    "action": "sqs.send_message_batch",
                    "interval_seconds": 0.1,
                    "template": {
                        "QueueUrl": f"{QUEUE_ROOT}/flowops-recovery-requests.fifo",
                        "Entries": "{{ item }}",
                    },
                },
            ),
            _node("end", "core.end"),
        ],
    )


def redrive() -> Runbook:
    book = _book(
        "lab-redrive-dlq",
        "DLQ - Reenviar mensagens com revisão",
        "Lê até três mensagens, reenvia e só depois apaga as originais. Sem consumidor automático. Repetições são possíveis fora da janela FIFO.",
        {
            "max_messages": Parameter(type="integer", default=3),
        },
    )
    return _chain(
        book,
        [
            _node("start", "core.start"),
            _node(
                "approve",
                "core.approval",
                {"message": "Autorizar recebimento, reenvio e confirmação das mensagens da DLQ."},
            ),
            _node(
                "redrive",
                "sqs.redrive_messages",
                {
                    "SourceQueueUrl": f"{QUEUE_ROOT}/flowops-payment-errors.fifo",
                    "DestinationQueueUrl": f"{QUEUE_ROOT}/flowops-recovery-requests.fifo",
                    "MaxMessages": "{{ params.max_messages }}",
                },
            ),
            _node("end", "core.end"),
        ],
    )


def inventory() -> Runbook:
    book = _book(
        "lab-inventory",
        "Inventário - Conferir recursos e recibos",
        "Ramos de leitura dos cinco serviços, reunidos em uma saída. Nenhuma mutação.",
        {},
    )
    book.nodes = [
        _node("start", "core.start"),
        _node("parallel", "core.parallel"),
        _node("payments", "dynamodb.scan", {"TableName": "flowops-payments", "Limit": 30}),
        _node("receipts", "dynamodb.scan", {"TableName": "flowops-receipts", "Limit": 30}),
        _node("queues", "sqs.list_queues"),
        _node("functions", "lambda.list_functions"),
        _node("topics", "sns.list_topics"),
        _node("objects", "s3.list_objects_v2", {"Bucket": "flowops-evidence", "MaxKeys": 30}),
        _node(
            "merge",
            "core.merge",
            {
                "inputs": {
                    name: f"{{{{ nodes.{name}.output }}}}"
                    for name in ["payments", "receipts", "queues", "functions", "topics", "objects"]
                }
            },
        ),
        _node("end", "core.end"),
    ]
    book.edges = [Edge(source="start", target="parallel"), Edge(source="merge", target="end")]
    for name in ["payments", "receipts", "queues", "functions", "topics", "objects"]:
        book.edges += [Edge(source="parallel", target=name), Edge(source=name, target="merge")]
    return _layout(book)


def lab_runbooks() -> list[Runbook]:
    return [recovery(), triage(), redrive(), inventory()]
