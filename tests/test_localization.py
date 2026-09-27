from __future__ import annotations

import copy
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from flowops.streamlit.component_locale import render_component_locale
from flowops.streamlit.localization import (
    ERRORS,
    LABELS,
    action_label,
    display,
    error_text,
    field_help,
    field_label,
    presentation_rows,
    render_error,
    render_summary_table,
    schema_view,
)
from flowops.templates import TEMPLATES


def test_display_preserves_identifiers_and_unknown_user_values() -> None:
    for original, translated in LABELS.items():
        assert display(original) == translated
    assert display(True) == "Sim"
    assert display(False) == "Não"
    assert display(None) == "—"
    for value in ("PRODUCTION", "PROCESSING", "TableName", "my-user-value", 12):
        assert display(value) == str(value)
    assert action_label("core.start") == "Início · core.start"
    assert action_label("core.custom") == "core.custom · core.custom"
    assert action_label("dynamodb.query") == "dynamodb.query"


def test_field_guidance_and_schema_keep_aws_contracts() -> None:
    assert field_label("TableName") == "Nome da tabela (TableName)"
    assert field_label("CustomKey") == "CustomKey"
    assert "tabela existente" in field_help("TableName", {"type": "string"})
    assert "número inteiro" in field_help("CustomKey", {"type": "integer"})
    assert "qualquer tipo" in field_help("CustomKey", {})
    schema = {
        "type": "object",
        "description": "Original SDK documentation",
        "required": ["Payload"],
        "properties": {
            "Payload": {"type": "object", "description": "Function input"},
            "Entries": {
                "type": "array",
                "items": {
                    "type": "string",
                    "description": "Raw enumeration",
                    "enum": ["RUNNING", "SUCCESS"],
                },
            },
        },
    }
    original = copy.deepcopy(schema)
    localized = schema_view(schema)
    assert schema == original
    assert localized["required"] == ["Payload"]
    assert localized["properties"].keys() == schema["properties"].keys()
    assert localized["properties"]["Payload"]["description"].startswith("Use um objeto JSON")
    assert localized["properties"]["Entries"]["items"]["enum"] == ["RUNNING", "SUCCESS"]
    assert schema_view({"type": "object"}) == {"type": "object"}


def test_summary_translation_does_not_translate_outputs_or_user_names() -> None:
    rows = [
        {
            "status": "SUCCESS",
            "required": False,
            "environment": "dev",
            "runbook": "Start",
            "output": {"status": "SUCCESS"},
            "other": "literal",
        }
    ]
    original = copy.deepcopy(rows)
    assert presentation_rows(rows) == [
        {
            "Estado": "Sucesso",
            "Obrigatório": "Não",
            "Ambiente": "Desenvolvimento",
            "Procedimento": "Start",
            "Saída": {"status": "SUCCESS"},
            "other": "literal",
        }
    ]
    assert rows == original
    assert presentation_rows([]) == []


@pytest.mark.parametrize(
    ("original", "translated"),
    [
        ("Permission required: runbook.edit.", "Permissão necessária: runbook.edit."),
        ("Required parameter: TableName.", "Parâmetro obrigatório: TableName."),
        ("Disconnected node: query.", "Etapa desconectada: query."),
        ("Unknown action: custom.foo", "Ação desconhecida: custom.foo"),
        (
            "query: required input TableName is missing.",
            "query: falta o campo obrigatório TableName.",
        ),
        (
            "query: FAIL_BRANCH requires a failure edge.",
            "query: o caminho de falha exige uma conexão de falha.",
        ),
        ("Informe uma opção.", "Informe uma opção."),
    ],
)
def test_known_dynamic_errors(original: str, translated: str) -> None:
    assert error_text(original) == translated


def test_known_errors_and_unknown_technical_details(monkeypatch: pytest.MonkeyPatch) -> None:
    for original, translated in ERRORS.items():
        assert error_text(original) == translated
    assert error_text("New provider failure").startswith("Não foi possível concluir")
    messages: list[str] = []
    originals: list[str] = []
    monkeypatch.setitem(
        sys.modules,
        "streamlit",
        SimpleNamespace(
            error=messages.append,
            expander=lambda *a, **kw: nullcontext(),
            code=lambda value, **kw: originals.append(value),
        ),
    )
    render_error("Provider rejected AKIA1234567890123456")
    assert messages[0].startswith("Não foi possível concluir")
    assert "AKIA1234567890123456" not in originals[0]
    assert "Provider rejected" in originals[0]


def test_template_descriptions_have_portuguese_presentation_without_mutation() -> None:
    for template in TEMPLATES.values():
        book = template.create("author", "default")
        original = book.model_dump_json()
        assert display(book.name) != book.name
        assert display(book.description) != book.description or book.description == (
            "Consulta um pagamento, transforma a saída e envia um evento aprovado para Lambda."
        )
        for parameter in book.parameters.values():
            if parameter.description in LABELS:
                assert display(parameter.description) != parameter.description
        assert book.model_dump_json() == original


def test_component_loads_packaged_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def register(name: str, *, js: str):
        calls.append({"name": name, "js": js})
        return lambda **kwargs: calls.append(kwargs)

    monkeypatch.setitem(
        sys.modules,
        "streamlit",
        SimpleNamespace(
            components=SimpleNamespace(v2=SimpleNamespace(component=register)),
        ),
    )
    render_component_locale()
    assert calls[0]["name"] == "flowops_pt_br"
    assert "export default function" in calls[0]["js"]
    assert "Excluir conexão" in calls[0]["js"]
    assert calls[1] == {"key": "flowops:pt-br"}


def test_summary_empty_state(monkeypatch: pytest.MonkeyPatch) -> None:
    frames, captions = [], []
    monkeypatch.setitem(
        sys.modules,
        "streamlit",
        SimpleNamespace(
            dataframe=lambda rows, **kw: frames.append(rows),
            caption=captions.append,
        ),
    )
    render_summary_table([])
    assert captions == ["Sem registros para exibir."] and not frames
    render_summary_table([{"Estado": "Sucesso"}], hide_index=True)
    assert frames == [[{"Estado": "Sucesso"}]]


def test_new_template_draft_is_localized_existing_snapshot_is_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from streamlit.testing.v1 import AppTest

    from flowops.application import FlowOpsRuntime
    from flowops.persistence.repository import Repository

    database = tmp_path / "templates.db"
    monkeypatch.setenv("FLOWOPS_DATABASE", str(database))
    monkeypatch.delenv("FLOWOPS_DATABASE_URL", raising=False)
    repo = Repository(database)
    original = TEMPLATES["fix-stuck-payment"].create("author", "default")
    revision = repo.save_draft(original, "author")
    published = repo.publish(original.id, "author", revision)
    saved_original = repo.get_draft(original.id)
    app = AppTest.from_file(Path(__file__).parents[1] / "standalone_app.py").run(timeout=30)
    try:
        assert not app.dataframe
        assert sum(item.value == "Sem registros para exibir." for item in app.caption) == 4
        app.sidebar.radio[0].set_value("Runbooks").run(timeout=30)
        next(w for w in app.selectbox if w.label == "Modelo").set_value("fix-stuck-payment").run(
            timeout=30
        )
        next(w for w in app.button if w.label == "Criar procedimento").click().run(timeout=30)
        assert not app.exception
        created = next(book for book in repo.list_runbooks() if book.id != original.id)
        assert created.name == "Recuperar pagamento parado"
        assert created.description.startswith("Recupere com segurança")
        assert created.parameters["payment_id"].description == "Identificador do pagamento"
        approval = next(node for node in created.nodes if node.action == "core.approval")
        assert approval.label == "Aprovação manual"
        assert approval.config["message"] == "Aprove a recuperação condicional do pagamento"
        assert repo.version(original.id, 1) == published
        assert repo.get_draft(original.id) == saved_original
    finally:
        for value in app.session_state.filtered_state.values():
            if isinstance(value, FlowOpsRuntime):
                value.close()
