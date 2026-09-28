import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

from streamlit.testing.v1 import AppTest

from flowops.application import FlowOpsRuntime
from flowops.domain.models import AWSContext, Edge, Identity, Node, Status
from flowops.persistence.repository import Repository
from flowops.templates import blank
from tests.app_test_support import close_app_runtime


def element(elements: Any, label: str) -> Any:
    return next(item for item in elements if item.label == label)


class ReleaseUITests(unittest.TestCase):
    def test_demo_schema_mapper_lambda_review_and_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "ui.db")
            previous = os.environ.get("FLOWOPS_DATABASE")
            os.environ["FLOWOPS_DATABASE"] = database
            app = None
            try:
                repository = Repository(database)
                book = blank("author", "default")
                book.nodes.insert(
                    1,
                    Node(
                        id="lambda_change",
                        action="lambda.update_function_configuration",
                        config={"FunctionName": "payment-processor", "Timeout": 10},
                    ),
                )
                book.edges = [
                    Edge(source="start", target="lambda_change"),
                    Edge(source="lambda_change", target="end"),
                ]
                repository.save_draft(book, "author")
                app = AppTest.from_file(
                    Path(__file__).resolve().parents[1] / "standalone_app.py"
                ).run(timeout=25)
                app.sidebar.radio[0].set_value("Editor")
                app.run(timeout=25)
                element(app.selectbox, "Propriedades da etapa").set_value("lambda_change")
                app.run(timeout=25)
                self.assertFalse(app.exception)
                self.assertTrue(
                    any(
                        "Estrutura dos campos de entrada" == expander.label
                        for expander in app.expander
                    )
                )
                element(app.button, "Carregar estado ATUAL e comparar com o PROPOSTO").click()
                app.run(timeout=25)
                self.assertFalse(app.exception)
                self.assertTrue(
                    any("CURRENT" in code.value and "Timeout" in code.value for code in app.code)
                )
                element(app.button, "Aplicar RevisionId revisado").click()
                app.run(timeout=25)
                element(app.button, "Salvar rascunho").click()
                app.run(timeout=25)
                saved, _ = repository.get_draft(book.id)
                self.assertEqual(saved.nodes[1].config["RevisionId"], "demo-revision")
                element(app.button, "Duplicar etapa selecionada").click()
                app.run(timeout=25)
                self.assertFalse(app.exception)
                copy_id = element(app.selectbox, "Propriedades da etapa").value
                self.assertNotEqual(copy_id, "lambda_change")
                element(app.button, "Validar").click()
                app.run(timeout=25)
                self.assertTrue(any("Etapa desconectada" in error.value for error in app.error))
                element(app.button, "Remover etapa selecionada").click()
                app.run(timeout=25)
                self.assertFalse(app.exception)
            finally:
                if app is not None:
                    close_app_runtime(app, repository)
                if previous is None:
                    os.environ.pop("FLOWOPS_DATABASE", None)
                else:
                    os.environ["FLOWOPS_DATABASE"] = previous

    def test_history_requires_new_production_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "history.db")
            repository = Repository(database)
            book = blank("author", "default")
            book.environments = ["production"]
            revision = repository.save_draft(book, "author")
            published = repository.publish(book.id, "author", revision)
            runtime = FlowOpsRuntime.demo(repository)
            user = Identity(id="admin", roles=["ADMIN"])
            context = AWSContext(environment="production", account_id="123456789012")
            execution = runtime.engine.submit(
                published, user, context, {}, token="first", dry_run=False, reason="CHG-9"
            )
            self.assertEqual(runtime.engine.execute(execution.id).status, Status.SUCCESS)
            runtime.close()
            script = f"""from flowops.streamlit import FlowOpsPage
from flowops.domain.models import Identity, AWSContext
from flowops.persistence.repository import Repository
FlowOpsPage(Identity(id="admin", roles=["ADMIN"]), AWSContext(environment="production", account_id="123456789012"), repository=Repository({database!r})).render()
"""
            app = AppTest.from_string(script).run(timeout=25)
            app.sidebar.radio[0].set_value("Executions")
            app.run(timeout=25)
            element(app.button, "Executar novamente").click()
            app.run(timeout=25)
            self.assertTrue(any("ID exato da conta" in error.value for error in app.error))
            self.assertEqual(len(runtime.engine.store.history()), 1)
            element(app.text_input, "Digite PRODUCTION para executar novamente").set_value(
                "PRODUCTION"
            )
            element(
                app.text_input, "Digite a conta AWS de destino para executar novamente"
            ).set_value("123456789012")
            element(app.button, "Executar novamente").click()
            app.run(timeout=25)
            self.assertFalse(app.exception)
            self.assertEqual(len(runtime.engine.store.history()), 2)
            close_app_runtime(app, repository, context)
