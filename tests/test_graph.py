import unittest

from flowops.core.expressions import compare, lookup, resolve
from flowops.core.graph import bind_parameters, validate_graph
from flowops.domain.errors import WorkflowValidationError
from flowops.domain.models import Edge, Node, Parameter, Runbook
from flowops.streamlit.canvas import apply_canvas


def minimal() -> Runbook:
    return Runbook(
        name="Test",
        nodes=[Node(id="start", action="core.start"), Node(id="end", action="core.end")],
        edges=[Edge(source="start", target="end")],
    )


class GraphTests(unittest.TestCase):
    def test_valid_and_invalid_graphs(self) -> None:
        book = minimal()
        self.assertEqual(validate_graph(book), ["start", "end"])
        invalids = [
            Runbook(name="Empty"),
            book.model_copy(deep=True),
            book.model_copy(deep=True),
            book.model_copy(deep=True),
            book.model_copy(deep=True),
        ]
        invalids[1].edges.append(Edge(source="end", target="start"))
        invalids[2].edges[0].target = "missing"
        invalids[3].nodes.append(Node(id="orphan", action="core.end"))
        invalids[4].nodes[1].config = {"x": "{{ nodes.end.output }}"}
        for invalid in invalids:
            with self.subTest(invalid=invalid):
                with self.assertRaises(WorkflowValidationError):
                    validate_graph(invalid)

    def test_safe_typed_mapping_and_missing_outputs(self) -> None:
        scope = {"nodes": {"get": {"output": {"items": [{"id": "123"}]}}}}
        self.assertEqual(resolve("{{ nodes.get.output.items }}", scope), [{"id": "123"}])
        self.assertEqual(resolve("ID: {{ nodes.get.output.items[0].id }}", scope), "ID: 123")
        for expression in [
            "{{ __import__('os') }}",
            "{{ nodes.get.__class__ }}",
            "{{nodes.missing.output}}",
            "{{ nodes.get.output.items }} x",
        ]:
            with self.subTest(expression=expression):
                with self.assertRaises(WorkflowValidationError):
                    resolve(expression, scope)
        with self.assertRaises(WorkflowValidationError):
            lookup("params.secret", {"params": {"secret": "[REDACTED]"}})

    def test_parameters_reject_bool_as_integer(self) -> None:
        book = minimal()
        book.parameters["count"] = Parameter(type="integer")
        self.assertEqual(bind_parameters(book, {"count": 2}), {"count": 2})
        for value in [{}, {"count": True}, {"count": 2, "unknown": 3}]:
            with self.assertRaises(WorkflowValidationError):
                bind_parameters(book, value)
        self.assertFalse(compare(True, "eq", 1))

    def test_canvas_does_not_trust_config_and_readonly(self) -> None:
        book = minimal()
        payload = {
            "nodes": [
                {"id": "start", "position": {"x": 30, "y": 60}, "config": {"evil": True}},
                {"id": "end"},
            ],
            "edges": [{"source": "start", "target": "end"}],
            "selected_id": "start",
        }
        result, selected = apply_canvas(book, payload)
        self.assertEqual(result.nodes[0].position, (30, 60))
        self.assertFalse(result.nodes[0].config)
        self.assertEqual(selected, "start")
        self.assertEqual(apply_canvas(book, payload, readonly=True)[0], book)
        payload["nodes"].append({"id": "invented"})
        with self.assertRaises(WorkflowValidationError):
            apply_canvas(book, payload)
