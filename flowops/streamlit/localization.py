"""Brazilian Portuguese presentation only; persisted values and SDK contracts stay intact."""

from __future__ import annotations

import re
from typing import Any

LABELS = {
    "ALL": "Todos",
    "All": "Todos",
    "core": "Lógica do fluxo",
    "PENDING": "Pendente",
    "RUNNING": "Em execução",
    "SUCCESS": "Sucesso",
    "FAILED": "Falha",
    "WAITING_APPROVAL": "Aguardando aprovação",
    "CANCELLED": "Cancelada",
    "SKIPPED": "Não executada",
    "READ_ONLY": "Somente leitura",
    "LOW": "Baixo",
    "MEDIUM": "Médio",
    "HIGH": "Alto",
    "CRITICAL": "Crítico",
    "STOP": "Interromper",
    "CONTINUE": "Continuar",
    "RETRY": "Tentar novamente",
    "FAIL_BRANCH": "Seguir caminho de falha",
    "MANUAL_INTERVENTION": "Intervenção manual",
    "dev": "Desenvolvimento",
    "staging": "Homologação",
    "production": "Produção",
    "demo": "Demonstração",
    "local": "Laboratório local",
    "aws": "AWS real",
    "fallback": "Cópia local de segurança",
    "dynamodb": "DynamoDB",
    "ADMIN": "Administrador",
    "AUTHOR": "Autor",
    "VIEWER": "Leitor",
    "OPERATOR": "Operador",
    "APPROVER": "Aprovador",
    "string": "texto",
    "integer": "número inteiro",
    "number": "número",
    "boolean": "verdadeiro ou falso",
    "object": "objeto",
    "array": "lista",
    "any": "qualquer tipo",
    "get_item": "Obter item (GetItem)",
    "query": "Consultar itens (Query)",
    "begins_with": "Começa com (begins_with)",
    "between": "Entre limites (between)",
    "HASH": "Chave de partição",
    "RANGE": "Chave de ordenação",
    "Start": "Início",
    "End": "Fim",
    "Wait": "Esperar",
    "Manual Approval": "Aprovação manual",
    "Validate Environment": "Validar ambiente",
    "Verify DynamoDB": "Verificar DynamoDB",
    "Validate PROCESSED": "Validar estado PROCESSED",
    "Inspect DLQ": "Inspecionar fila de erros",
    "Approve DLQ Redrive": "Aprovar reenvio da fila de erros",
    "Blank Runbook": "Procedimento em branco",
    "New Runbook": "Novo procedimento",
    "Fix Stuck Payment": "Recuperar pagamento parado",
    "Lambda Invoke": "Invocar Lambda",
    "DynamoDB Query to Lambda": "Consulta DynamoDB para Lambda",
    "Replay Event": "Reenviar evento",
    "DLQ Redrive": "Reenviar mensagens da fila de erros",
    "DynamoDB Record Correction": "Corrigir registro no DynamoDB",
    "Payment identifier": "Identificador do pagamento",
    "Must match the execution environment": "Deve corresponder ao ambiente da execução",
    "Partition key paymentId (String)": "Chave de partição paymentId (texto)",
    "Blank visual runbook": "Procedimento visual em branco",
    "Safely recover one payment stuck in PROCESSING, emit an event and verify completion.": "Recupere com segurança um pagamento parado em PROCESSING, envie um evento e verifique a conclusão.",
    "Invoke a Lambda with an explicit payload.": "Invoque uma função Lambda com dados definidos explicitamente.",
    "Publish a controlled message to an SQS queue.": "Envie uma mensagem controlada para uma fila SQS.",
    "Require approval, then start an AWS SQS managed message move task from a DLQ.": "Exija aprovação antes de iniciar o reenvio gerenciado de mensagens de uma fila de erros SQS.",
    "Read a record, require approval, then perform a parameterized UpdateItem request.": "Leia um registro, exija aprovação e faça uma requisição UpdateItem com parâmetros.",
    "Source dead-letter queue URL used for read-only inspection": "URL da fila de erros de origem, usada na inspeção somente leitura",
    "Source dead-letter queue ARN": "ARN da fila de erros de origem",
    "Explicit destination queue ARN for the managed redrive task": "ARN da fila de destino para o reenvio gerenciado",
    "AWS managed redrive rate limit": "Limite de mensagens por segundo no reenvio gerenciado pela AWS",
    "Approve conditional payment recovery": "Aprove a recuperação condicional do pagamento",
    "Approve starting the managed SQS redrive task": "Aprove o início do reenvio gerenciado de mensagens SQS",
}

CORE_LABELS = {
    "start": "Início",
    "end": "Fim",
    "stop": "Interromper",
    "condition": "Condição",
    "switch": "Escolher caminho",
    "filter": "Filtrar itens",
    "map": "Transformar dados",
    "for_each": "Para cada item",
    "batch": "Dividir em lotes",
    "parallel": "Executar em paralelo",
    "merge": "Reunir resultados",
    "wait": "Esperar",
    "retry": "Tentar novamente",
    "validation": "Validar dados",
    "approval": "Aprovação manual",
    "compensation": "Compensar ação",
}

FIELD_LABELS = {
    "type": "Tipo",
    "required": "Obrigatório",
    "default": "Valor padrão",
    "description": "Descrição",
    "TableName": "Nome da tabela",
    "FunctionName": "Nome da função",
    "S3Bucket": "Bucket S3 do código",
    "S3Key": "Objeto S3 do código",
    "EndpointId": "Identificador do endpoint",
    "QueueUrl": "URL da fila",
    "SourceQueueUrl": "URL da fila de origem",
    "DestinationQueueUrl": "URL da fila de destino",
    "SourceQueueArn": "ARN da fila de origem",
    "SourceArn": "ARN de origem",
    "DestinationArn": "ARN de destino",
    "TaskHandle": "Identificador da tarefa",
    "stateMachineArn": "ARN da máquina de estados",
    "executionArn": "ARN da execução",
    "LoadBalancerArn": "ARN do balanceador",
    "ListenerArn": "ARN do listener",
    "TopicArn": "ARN do tópico",
    "Bucket": "Nome do bucket",
    "Key": "Chave",
    "Limit": "Limite",
    "Payload": "Dados enviados à função",
    "InvocationType": "Tipo de invocação",
    "KeyConditionExpression": "Condição das chaves",
    "ExpressionAttributeNames": "Aliases dos atributos",
    "ExpressionAttributeValues": "Valores dos atributos",
    "FilterExpression": "Expressão de filtro",
    "UpdateExpression": "Expressão de atualização",
    "ConditionExpression": "Condição da alteração",
    "IndexName": "Nome do índice",
    "MessageBody": "Corpo da mensagem",
    "Message": "Mensagem",
    "ReturnValues": "Valores retornados",
    "ConsistentRead": "Leitura consistente",
    "payment_id": "Identificador do pagamento",
    "environment": "Ambiente",
    "table_name": "Nome da tabela",
    "function_name": "Nome da função",
    "payload": "Dados enviados",
    "queue_url": "URL da fila",
    "expected_status": "Estado esperado",
    "reason": "Motivo",
    "customer_id": "Identificador do cliente",
    "message": "Mensagem",
    "seconds": "Tempo de espera",
    "left": "Valor à esquerda",
    "right": "Valor à direita",
    "operator": "Operador",
    "value": "Valor",
    "cases": "Caminhos possíveis",
    "items": "Itens de entrada",
    "path": "Caminho do campo",
    "template": "Modelo de transformação",
    "size": "Tamanho do lote",
    "inputs": "Entradas",
    "action": "Ação",
    "config": "Configuração",
    "key": "Chave",
    "source_queue_url": "URL da fila de erros",
    "source_arn": "ARN de origem",
    "destination_arn": "ARN de destino",
    "max_messages_per_second": "Máximo de mensagens por segundo",
    "batch_size": "Tamanho do lote",
    "wait_seconds": "Espera em segundos",
    "limit": "Limite",
    "update_expression": "Expressão de atualização",
    "expression_names": "Aliases dos atributos",
    "expression_values": "Valores dos atributos",
}

FIELD_HELP = {
    "type": "Escolha o tipo de dado esperado. O valor padrão precisa respeitar esse tipo.",
    "required": "Marque para exigir este parâmetro ao executar o procedimento.",
    "default": "Valor sugerido na execução. Remova o campo para não definir uma sugestão; nulo segue o contrato atual do parâmetro.",
    "description": "Explique o que preencher e por que esse valor é necessário para executar o procedimento.",
    "TableName": "Informe uma tabela existente no ambiente selecionado. Ela define onde a operação será realizada.",
    "FunctionName": "Informe o nome ou ARN de uma função autorizada no contexto atual. Confira o destino antes de enviar dados.",
    "Payload": "Use um objeto JSON ou uma expressão que retorne os dados esperados pela função. O provedor faz a serialização.",
    "KeyConditionExpression": "Defina igualdade na chave de partição e, se necessário, uma condição na chave de ordenação. Exemplo: #pk = :pk.",
    "ExpressionAttributeNames": 'Associe aliases aos nomes reais dos atributos. Exemplo: {"#pk": "paymentId"}.',
    "ExpressionAttributeValues": 'Defina valores tipados do DynamoDB. Exemplo: {":pk": {"S": "12345"}}. N representa um número armazenado como texto.',
    "Limit": "Limite a quantidade de itens avaliados por chamada. Use uma consulta restrita; o limite não garante a leitura de todos os resultados.",
    "QueueUrl": "Informe a URL da fila autorizada de destino, no ambiente selecionado.",
    "MessageBody": "Informe o conteúdo da mensagem como texto, objeto JSON ou expressão. Confira o formato esperado pelo consumidor.",
}

COLUMNS = {
    "id": "ID",
    "runbook": "Procedimento",
    "version": "Versão",
    "environment": "Ambiente",
    "status": "Estado",
    "started": "Início",
    "user": "Usuário",
    "account": "Conta",
    "duration_s": "Duração (s)",
    "node": "Etapa",
    "action": "Ação",
    "attempts": "Tentativas",
    "input": "Entrada",
    "output": "Saída",
    "error": "Erro",
    "executions": "Execuções",
    "failures": "Falhas",
    "field": "Campo",
    "type": "Tipo",
    "required": "Obrigatório",
    "documentation": "Orientação",
    "role": "Função",
    "when": "Quando",
    "who": "Responsável",
    "what": "Evento",
    "execution": "Execução",
    "where": "Contexto",
    "why": "Motivo",
    "result": "Resultado",
    "default": "Valor padrão",
    "enum": "Valores aceitos",
    "finished": "Término",
}

ERRORS = {
    "Runbook belongs to a different team.": "O procedimento pertence a outra equipe.",
    "Runbook is not allowed in this environment.": "O procedimento não é permitido neste ambiente.",
    "Production execution requires a change reason.": "A execução em produção exige um motivo para a mudança.",
    "Requester cannot approve their own execution.": "O solicitante não pode aprovar a própria execução.",
    "An approval/rejection reason is required.": "Informe o motivo da aprovação ou rejeição.",
    "Execution approval was rejected.": "A aprovação da execução foi rejeitada.",
    "Automatic retries require an idempotent action.": "Novas tentativas automáticas exigem uma ação idempotente.",
    "Node IDs must be unique.": "Os IDs das etapas devem ser únicos.",
    "Use exactly one Start and at least one End or Stop.": "Use exatamente um Início e pelo menos um Fim ou Interromper.",
    "A workflow needs 1–200 nodes and at most 1000 edges.": "O fluxo deve ter de 1 a 200 etapas e no máximo 1000 conexões.",
    "An edge refers to an unknown node.": "Uma conexão aponta para uma etapa desconhecida.",
    "Duplicate edge.": "Há uma conexão duplicada.",
    "Cycles are forbidden; use bounded For Each.": "Ciclos não são permitidos; use Para cada item com um limite definido.",
    "Start has no input; End/Stop has no output.": "Início não recebe conexões; Fim e Interromper não possuem saídas.",
    "Unknown expression root.": "A raiz da expressão é desconhecida.",
    "Unknown runbook parameter.": "Há um parâmetro desconhecido no procedimento.",
    "Draft changed in another session.": "O rascunho foi alterado em outra sessão. Recarregue e revise as alterações.",
    "Execution requires the unchanged published version.": "A execução exige a versão publicada sem alterações.",
    "Archived runbooks cannot start new executions.": "Procedimentos arquivados não podem iniciar novas execuções.",
    "No runnable nodes remain.": "Não há etapas disponíveis para executar.",
    "Wait must be between 0 and 3600 seconds.": "A espera deve ficar entre 0 e 3600 segundos.",
    "DynamoDB reads require a bounded Limit.": "As leituras do DynamoDB exigem um Limit dentro dos limites permitidos.",
}


def display(value: Any) -> str:
    if isinstance(value, bool):
        return "Sim" if value else "Não"
    return LABELS.get(str(value), str(value)) if value is not None else "—"


def action_label(action_id: str) -> str:
    if action_id.startswith("core."):
        return f"{CORE_LABELS.get(action_id[5:], action_id)} · {action_id}"
    return action_id


def field_label(name: str) -> str:
    return f"{FIELD_LABELS[name]} ({name})" if name in FIELD_LABELS else name


def field_help(name: str, schema: dict[str, Any]) -> str:
    kind = display(schema.get("type", "any"))
    return FIELD_HELP.get(
        name,
        f"Informe um valor do tipo {kind} para {name}. O nome técnico do campo é preservado na configuração.",
    )


def schema_view(schema: dict[str, Any], name: str = "entrada") -> dict[str, Any]:
    """Copy SDK schemas for display, translating prose but never contract keys/enums."""
    result = dict(schema)
    if "description" in result:
        result["description"] = field_help(name, schema)
    if isinstance(schema.get("properties"), dict):
        result["properties"] = {
            key: schema_view(value, key) for key, value in schema["properties"].items()
        }
    if isinstance(schema.get("items"), dict):
        result["items"] = schema_view(schema["items"], name)
    return result


def presentation_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Only app-owned summary tables, never user/provider result envelopes."""
    return [
        {
            COLUMNS.get(key, key): display(value)
            if key in {"status", "environment", "result", "type", "role", "required"}
            else value
            for key, value in row.items()
        }
        for row in rows
    ]


def render_summary_table(
    rows: list[dict[str, Any]], *, container: Any = None, **options: Any
) -> None:
    import streamlit as st

    target = st if container is None else container
    if rows:
        target.dataframe(rows, **options)
    else:
        target.caption("Sem registros para exibir.")


def error_text(error: Any) -> str:
    message = str(error)
    if message in ERRORS:
        return ERRORS[message]
    patterns = (
        (r"Permission required: (.+)\.", "Permissão necessária: {}."),
        (r"Required parameter: (.+)\.", "Parâmetro obrigatório: {}."),
        (r"Disconnected node: (.+)\.", "Etapa desconectada: {}."),
        (r"Unknown action: (.+)", "Ação desconhecida: {}"),
        (r"(.+): required input (.+) is missing\.", "{}: falta o campo obrigatório {}."),
        (
            r"(.+): FAIL_BRANCH requires a failure edge\.",
            "{}: o caminho de falha exige uma conexão de falha.",
        ),
    )
    for pattern, translation in patterns:
        match = re.fullmatch(pattern, message)
        if match:
            return translation.format(*match.groups())
    # UI-authored Portuguese errors stay readable; unknown upstream details remain
    # available separately, without guessing their meaning or changing stored errors.
    if re.search(r"[ãõçáéíóúêâ]|\b(?:Use|Selecione|Informe|Adicione|Posição)\b", message):
        return message
    return "Não foi possível concluir a operação. Consulte os detalhes técnicos para identificar a causa."


def render_error(error: Any) -> None:
    import streamlit as st

    from flowops.core.security import redact

    safe_message = str(redact(str(error)))
    st.error(error_text(safe_message))
    with st.expander("Detalhes técnicos do erro (mensagem original)", expanded=False):
        st.code(safe_message, language=None)
