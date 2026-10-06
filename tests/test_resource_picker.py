from __future__ import annotations

import sys
from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any

import pytest

from flowops.domain.errors import WorkflowValidationError
from flowops.domain.models import AWSContext, Identity, Runbook
from flowops.providers.aws.resources import DiscoveryRule, InspectionRule
from flowops.streamlit import resource_picker

TABLE = {
    "TableName": "flowops-payments",
    "AttributeDefinitions": [
        {"AttributeName": "status", "AttributeType": "S"},
        {"AttributeName": "updatedAt", "AttributeType": "N"},
    ],
    "KeySchema": [{"AttributeName": "status", "KeyType": "HASH"}],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "status-index",
            "KeySchema": [
                {"AttributeName": "status", "KeyType": "HASH"},
                {"AttributeName": "updatedAt", "KeyType": "RANGE"},
            ],
        }
    ],
}


class FakeStreamlit:
    def __init__(self, *, buttons: set[str] | None = None) -> None:
        self.buttons = buttons or set()
        self.session_state: dict[str, Any] = {}
        self.errors: list[str] = []
        self.captions: list[str] = []
        self.codes: list[str] = []
        self.json_values: list[Any] = []
        self.reruns = 0

    def button(self, label: str, **kwargs: Any) -> bool:
        return label in self.buttons

    def dataframe(self, rows: Any, **kwargs: Any) -> None:
        pass

    def expander(self, *args: Any, **kwargs: Any):
        return nullcontext()

    def json(self, value: Any, **kwargs: Any) -> None:
        self.json_values.append(value)

    def multiselect(self, label: str, options: list[Any], **kwargs: Any) -> list[Any]:
        return list(kwargs.get("default", []))

    def selectbox(self, label: str, options: list[Any], **kwargs: Any) -> Any:
        if label == "Leitura do DynamoDB":
            return "query"
        if label == "Índice (opcional)":
            return "status-index"
        if label == "Condição da chave de ordenação":
            return "between"
        if label == "Recurso encontrado":
            return options[0]
        return options[0]

    def text_input(self, label: str, **kwargs: Any) -> str:
        if "Limite superior" in label:
            return "200"
        if "updatedAt" in label:
            return "100"
        return "PROCESSING"

    def number_input(self, label: str, **kwargs: Any) -> int:
        return 10

    def caption(self, value: str) -> None:
        self.captions.append(value)

    def code(self, value: str, **kwargs: Any) -> None:
        self.codes.append(value)

    def subheader(self, value: str) -> None:
        pass

    def info(self, value: str) -> None:
        pass

    def error(self, value: str) -> None:
        self.errors.append(value)

    def rerun(self) -> None:
        self.reruns += 1


class FakeUI:
    aws = AWSContext(mode="local")
    user = Identity(id="operator", permissions=["aws.read", "runbook.edit"])
    runtime = SimpleNamespace(registry=object())

    def __init__(self) -> None:
        self.stored: list[tuple[Any, int]] = []

    def _store_working(self, book: Any, revision: int) -> None:
        self.stored.append((book, revision))

    def _granted(self, permission: str, book: Any) -> bool:
        return permission == "runbook.edit"


def install_streamlit(monkeypatch: pytest.MonkeyPatch, fake: FakeStreamlit) -> None:
    monkeypatch.setitem(sys.modules, "streamlit", fake)


def test_dynamodb_query_builder_ui_loads_schema_and_applies_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeStreamlit(
        buttons={"Carregar estrutura da tabela", "Aplicar requisição DynamoDB gerada"}
    )
    install_streamlit(monkeypatch, fake)
    monkeypatch.setattr(resource_picker, "read_action", lambda *args, **kwargs: {"Table": TABLE})
    ui = FakeUI()
    node = SimpleNamespace(config={}, action="dynamodb.get_item")
    book = Runbook(id="book", name="Builder regression")
    resource_picker._render_dynamodb_query(ui, book, node, 3, "flowops-payments", key="picker")
    assert node.config["IndexName"] == "status-index"
    assert node.action == "dynamodb.query"
    assert node.config["Limit"] == 10
    assert node.config["ExpressionAttributeValues"][":end"] == {"N": "200"}
    assert ui.stored == [(book, 3)]
    assert fake.reruns == 1


def test_resource_picker_applies_discovered_queue_and_handles_empty_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeStreamlit(buttons={"Buscar recursos para esta etapa", "Aplicar recurso selecionado"})
    install_streamlit(monkeypatch, fake)
    monkeypatch.setattr(
        resource_picker,
        "discover_field",
        lambda *args, **kwargs: ["http://127.0.0.1:5000/queue"],
    )
    ui = FakeUI()
    ui.runtime = SimpleNamespace(
        registry=SimpleNamespace(
            get=lambda action_id: SimpleNamespace(
                metadata=SimpleNamespace(
                    input_schema={"type": "object", "properties": {"QueueUrl": {"type": "string"}}}
                )
            )
        )
    )
    node = SimpleNamespace(id="node", action="sqs.send_message", config={})
    book = Runbook(id="book", name="Resource fixture")
    resource_picker.render_resource_picker(ui, book, node, 1)
    assert node.config["QueueUrl"].endswith("/queue")
    assert ui.stored == [(book, 1)]

    empty = FakeStreamlit()
    install_streamlit(monkeypatch, empty)
    no_resource = SimpleNamespace(id="node", action="s3.put_object", config={})
    resource_picker.render_resource_picker(ui, book, no_resource, 1)
    assert no_resource.config == {}


def test_resource_picker_inspects_selected_resource_without_applying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeStreamlit(
        buttons={
            "Buscar recursos para esta etapa",
            "Carregar detalhes de URL da fila (QueueUrl)",
        }
    )
    install_streamlit(monkeypatch, fake)
    monkeypatch.setattr(
        resource_picker,
        "discover_field",
        lambda *args, **kwargs: ["https://sqs.local/queue"],
    )
    monkeypatch.setattr(
        resource_picker,
        "inspect_resource",
        lambda *args, **kwargs: {"Attributes": {"QueueArn": "arn:aws:sqs:::queue"}},
    )
    ui = FakeUI()
    ui.runtime = SimpleNamespace(
        registry=SimpleNamespace(
            get=lambda action_id: SimpleNamespace(
                metadata=SimpleNamespace(
                    input_schema={"type": "object", "properties": {"QueueUrl": {"type": "string"}}}
                )
            )
        )
    )
    node = SimpleNamespace(id="node", action="sqs.send_message", config={})
    book = Runbook(id="book", name="Inspection fixture")
    resource_picker.render_resource_picker(ui, book, node, 1)

    assert node.config == {}
    assert ui.stored == []
    assert fake.json_values == [{"Attributes": {"QueueArn": "arn:aws:sqs:::queue"}}]


def test_resource_picker_invalidates_dependent_choices_when_parent_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeStreamlit(buttons={"Aplicar Chave (Key)"})
    install_streamlit(monkeypatch, fake)
    ui = FakeUI()
    ui.runtime = SimpleNamespace(
        registry=SimpleNamespace(
            get=lambda action_id: SimpleNamespace(
                metadata=SimpleNamespace(
                    input_schema={
                        "type": "object",
                        "properties": {
                            "Bucket": {"type": "string"},
                            "Key": {"type": "string"},
                        },
                    }
                )
            )
        )
    )
    node = SimpleNamespace(
        id="node",
        action="s3.delete_object",
        config={"Bucket": "new-bucket"},
    )
    book = Runbook(id="book", name="Stale dependency fixture")
    rules = resource_picker.discovery_rules(
        node.action, ui.runtime.registry.get(node.action).metadata.input_schema
    )
    key_rule = next(rule for rule in rules if rule.field == "Key")
    picker_key = f"flowops:resource-picker:{resource_picker._fingerprint(ui, node.action, node.id)}"
    fake.session_state[f"{picker_key}:results"] = {"Key": ["old-object.json"]}
    fake.session_state[f"{picker_key}:result-signatures"] = {
        "Key": resource_picker._discovery_signature(ui, key_rule, {"Bucket": "old-bucket"})
    }

    resource_picker.render_resource_picker(ui, book, node, 1)

    assert "Key" not in node.config
    assert ui.stored == []
    assert any("dependências mudaram" in caption for caption in fake.captions)


def test_resource_picker_uses_session_only_context_for_chained_execution_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeStreamlit(buttons={"Buscar recursos para esta etapa"})
    install_streamlit(monkeypatch, fake)
    ui = FakeUI()
    ui.runtime = SimpleNamespace(
        registry=SimpleNamespace(
            get=lambda action_id: SimpleNamespace(
                metadata=SimpleNamespace(
                    input_schema={
                        "type": "object",
                        "properties": {"executionArn": {"type": "string"}},
                    }
                )
            )
        )
    )
    monkeypatch.setattr(
        resource_picker,
        "discover_field",
        lambda registry, user, aws, rule, config: (
            ["arn:aws:states:sa-east-1:000000000000:stateMachine:payments"]
            if rule.field == "stateMachineArn"
            else ["arn:aws:states:sa-east-1:000000000000:execution:payments:run-1"]
        ),
    )
    node = SimpleNamespace(id="stop", action="stepfunctions.stop_execution", config={})
    book = Runbook(id="book", name="Step Functions chain")

    resource_picker.render_resource_picker(ui, book, node, 1)
    picker_key = f"flowops:resource-picker:{resource_picker._fingerprint(ui, node.action, node.id)}"
    assert fake.session_state[f"{picker_key}:auxiliary"]["stateMachineArn"].endswith(
        ":stateMachine:payments"
    )
    assert node.config == {}
    assert ui.stored == []

    fake.buttons = {"Buscar recursos para esta etapa", "Aplicar recurso selecionado"}
    resource_picker.render_resource_picker(ui, book, node, 1)

    assert node.config["executionArn"].endswith(":execution:payments:run-1")
    assert "stateMachineArn" not in node.config
    assert ui.stored == [(book, 1)]


def test_resource_picker_supports_two_level_sqs_task_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeStreamlit(buttons={"Buscar recursos para esta etapa"})
    install_streamlit(monkeypatch, fake)
    ui = FakeUI()
    ui.runtime = SimpleNamespace(
        registry=SimpleNamespace(
            get=lambda action_id: SimpleNamespace(
                metadata=SimpleNamespace(
                    input_schema={
                        "type": "object",
                        "properties": {"TaskHandle": {"type": "string"}},
                    }
                )
            )
        )
    )

    def discover(
        registry: Any, user: Any, aws: Any, rule: Any, config: dict[str, Any]
    ) -> list[str]:
        if rule.field == "SourceQueueUrl":
            return ["https://sqs.local/source"]
        if rule.field == "SourceQueueArn":
            assert config["SourceQueueUrl"] == "https://sqs.local/source"
            return ["arn:aws:sqs:sa-east-1:000000000000:source"]
        assert rule.field == "TaskHandle"
        assert config["SourceQueueArn"].endswith(":source")
        return ["task-handle-1"]

    monkeypatch.setattr(resource_picker, "discover_field", discover)
    node = SimpleNamespace(id="cancel", action="sqs.cancel_message_move_task", config={})
    book = Runbook(id="book", name="SQS move task chain")

    resource_picker.render_resource_picker(ui, book, node, 1)
    picker_key = f"flowops:resource-picker:{resource_picker._fingerprint(ui, node.action, node.id)}"
    auxiliary_key = f"{picker_key}:auxiliary"
    assert fake.session_state[auxiliary_key] == {"SourceQueueUrl": "https://sqs.local/source"}
    assert node.config == {}

    resource_picker.render_resource_picker(ui, book, node, 1)
    assert fake.session_state[auxiliary_key]["SourceQueueArn"].endswith(":source")
    assert node.config == {}

    fake.buttons = {"Buscar recursos para esta etapa", "Aplicar recurso selecionado"}
    resource_picker.render_resource_picker(ui, book, node, 1)

    assert node.config == {"TaskHandle": "task-handle-1"}
    assert "SourceQueueUrl" not in node.config
    assert "SourceQueueArn" not in node.config
    assert ui.stored == [(book, 1)]


def test_resource_picker_surfaces_dependencies_empty_and_multiple_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeStreamlit(buttons={"Buscar recursos para esta etapa"})
    install_streamlit(monkeypatch, fake)
    dependent = DiscoveryRule(
        "s3",
        "Key",
        "s3.list_objects_v2",
        ("Contents", "*", "Key"),
        request_from=(("Bucket", "Bucket"),),
    )
    multiple = DiscoveryRule(
        "ec2",
        "InstanceIds",
        "ec2.describe_instances",
        ("Reservations", "*", "Instances", "*", "InstanceId"),
        multiple=True,
    )
    empty = DiscoveryRule(
        "ec2", "VpcIds", "ec2.describe_vpcs", ("Vpcs", "*", "VpcId"), multiple=True
    )
    monkeypatch.setattr(
        resource_picker, "discovery_rules", lambda *args: [dependent, multiple, empty]
    )
    monkeypatch.setattr(resource_picker, "inspection_rules", lambda *args: [])

    monkeypatch.setattr(
        resource_picker,
        "discover_field",
        lambda registry, user, aws, rule, config: {
            "InstanceIds": ["i-1", "i-2"],
            "VpcIds": [],
        }[rule.field],
    )
    ui = FakeUI()
    ui.runtime = SimpleNamespace(
        registry=SimpleNamespace(
            get=lambda action_id: SimpleNamespace(metadata=SimpleNamespace(input_schema={}))
        )
    )
    node = SimpleNamespace(
        id="node",
        action="ec2.stop_instances",
        config={"InstanceIds": ["i-2", "stale"]},
    )
    book = Runbook(id="book", name="Dependency fixture")
    resource_picker.render_resource_picker(ui, book, node, 1)
    assert node.config["InstanceIds"] == ["i-2", "stale"]
    assert any("aplique primeiro" in caption for caption in fake.captions)
    assert any("nenhuma opção carregada" in caption for caption in fake.captions)


def test_resource_picker_handles_invalid_cache_and_inspection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeStreamlit(
        buttons={
            "Buscar recursos para esta etapa",
            "Carregar detalhes de URL da fila (QueueUrl)",
        }
    )
    install_streamlit(monkeypatch, fake)
    rule = DiscoveryRule("sqs", "QueueUrl", "sqs.list_queues", ("QueueUrls", "*"))
    inspector = InspectionRule(
        "sqs",
        "QueueUrl",
        "sqs.get_queue_attributes",
        request_from=(("QueueUrl", "QueueUrl", False),),
    )
    monkeypatch.setattr(resource_picker, "discovery_rules", lambda *args: [rule])
    monkeypatch.setattr(resource_picker, "inspection_rules", lambda *args: [inspector])
    monkeypatch.setattr(resource_picker, "_fingerprint", lambda *args: "fixed")
    fake.session_state["flowops:resource-picker:fixed:results"] = "invalid"

    monkeypatch.setattr(
        resource_picker,
        "discover_field",
        lambda *args, **kwargs: ["https://sqs.local/queue"],
    )
    monkeypatch.setattr(
        resource_picker,
        "inspect_resource",
        lambda *args, **kwargs: (_ for _ in ()).throw(WorkflowValidationError("falha de inspeção")),
    )
    ui = FakeUI()
    ui.runtime = SimpleNamespace(
        registry=SimpleNamespace(
            get=lambda action_id: SimpleNamespace(metadata=SimpleNamespace(input_schema={}))
        )
    )
    node = SimpleNamespace(id="node", action="sqs.send_message", config={})
    book = Runbook(id="book", name="Inspection error fixture")
    resource_picker.render_resource_picker(ui, book, node, 1)
    assert fake.errors
    assert fake.codes == ["falha de inspeção"]


def test_resource_picker_handles_discovery_error_and_invalid_cached_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule = DiscoveryRule("sqs", "QueueUrl", "sqs.list_queues", ("QueueUrls", "*"))
    ui = FakeUI()
    ui.runtime = SimpleNamespace(
        registry=SimpleNamespace(
            get=lambda action_id: SimpleNamespace(metadata=SimpleNamespace(input_schema={}))
        )
    )
    node = SimpleNamespace(id="node", action="sqs.send_message", config={})
    book = Runbook(id="book", name="Discovery error fixture")
    monkeypatch.setattr(resource_picker, "discovery_rules", lambda *args: [rule])
    monkeypatch.setattr(resource_picker, "inspection_rules", lambda *args: [])
    monkeypatch.setattr(resource_picker, "_fingerprint", lambda *args: "fixed")

    cached = FakeStreamlit()
    cached.session_state["flowops:resource-picker:fixed:results"] = "invalid"
    install_streamlit(monkeypatch, cached)
    resource_picker.render_resource_picker(ui, book, node, 1)
    assert any("nenhuma opção carregada" in caption for caption in cached.captions)

    failing = FakeStreamlit(buttons={"Buscar recursos para esta etapa"})
    install_streamlit(monkeypatch, failing)
    monkeypatch.setattr(
        resource_picker,
        "discover_field",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            WorkflowValidationError("falha de descoberta")
        ),
    )
    resource_picker.render_resource_picker(ui, book, node, 1)
    assert failing.errors
    assert failing.codes == ["falha de descoberta"]


def test_dynamodb_builder_preserves_config_when_operation_would_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeStreamlit(buttons={"Carregar estrutura da tabela"})
    install_streamlit(monkeypatch, fake)
    monkeypatch.setattr(resource_picker, "read_action", lambda *args, **kwargs: {"Table": TABLE})
    ui = FakeUI()
    node = SimpleNamespace(
        config={"TableName": "flowops-payments"},
        action="dynamodb.get_item",
    )
    book = Runbook(id="book", name="Preserve operation fixture")
    with pytest.raises(WorkflowValidationError, match="Trocar Query por GetItem"):
        resource_picker._render_dynamodb_query(
            ui,
            book,
            node,
            1,
            "flowops-payments",
            key="preserve",
        )
    assert node.action == "dynamodb.get_item"
    assert node.config == {"TableName": "flowops-payments"}
