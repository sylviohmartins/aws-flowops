"""Small, explicit presentation profiles for common registered operations."""

import copy
from typing import Any

PROFILES: dict[str, tuple[str, dict[str, Any]]] = {
    "lambda.invoke": (
        "Enviar um evento para uma função. RequestResponse aguarda a resposta; Event confirma somente o recebimento.",
        {"FunctionName": "", "InvocationType": "RequestResponse", "Payload": {}},
    ),
    "sqs.send_message": (
        "Enviar uma mensagem para uma fila. O consumidor processará depois; em filas FIFO configure grupo e deduplicação conforme a política da fila.",
        {"QueueUrl": "", "MessageBody": {}},
    ),
    "sns.publish": (
        "Publicar em um tópico para seus assinantes. Revise o ARN e o conteúdo antes de executar.",
        {"TopicArn": "", "Message": {}},
    ),
    "s3.put_object": (
        "Gravar um objeto no bucket. Uma chave existente pode ser substituída; confira bucket, chave e conteúdo.",
        {"Bucket": "", "Key": "", "Body": "", "ContentType": "text/plain"},
    ),
    "s3.get_object": (
        "Ler um objeto por bucket e chave. O resultado pode ser limitado; confira truncamento antes de alimentar outra etapa.",
        {"Bucket": "", "Key": ""},
    ),
    "dynamodb.get_item": (
        "Ler um item pela chave primária completa; não aceita índice. Use a busca de estrutura ou informe as chaves visualmente.",
        {"TableName": "", "Key": {}},
    ),
    "dynamodb.query": (
        "Ler itens de uma partição. Use o construtor de consulta para gerar condições sem escrever expressões; a leitura pode ter custo.",
        {"TableName": "", "Limit": 30},
    ),
}


def recommended_config(action: str, current: dict[str, Any]) -> dict[str, Any]:
    defaults = PROFILES.get(action, ("", {}))[1]
    return copy.deepcopy(defaults | current)


def render_action_help(action: str) -> None:
    import streamlit as st

    if action in PROFILES:
        st.info(PROFILES[action][0])
