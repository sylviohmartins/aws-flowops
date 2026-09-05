import json
import unittest

from flowops.core.serialization import clone_runbook, export_runbook, import_runbook
from flowops.domain.errors import PolicyViolation
from flowops.templates import fix_stuck_payment


class SerializationTests(unittest.TestCase):
    def test_yaml_and_json_round_trip_as_new_drafts(self) -> None:
        source = fix_stuck_payment("owner", "payments")
        yaml_text = export_runbook(source, "yaml")
        self.assertEqual(yaml_text, export_runbook(source, "yaml"))
        imported = import_runbook(yaml_text, owner="new-owner")
        self.assertNotEqual(imported.id, source.id)
        self.assertEqual(imported.owner, "new-owner")
        self.assertEqual(imported.version, 0)
        json_text = export_runbook(source, "json")
        self.assertEqual(import_runbook(json_text, owner="owner").name, source.name)

    def test_clone_is_independent(self) -> None:
        source = fix_stuck_payment("owner", "payments")
        cloned = clone_runbook(source, owner="another")
        self.assertNotEqual(cloned.id, source.id)
        self.assertEqual(cloned.owner, "another")
        cloned.nodes[0].label = "Changed"
        self.assertNotEqual(cloned.nodes[0].label, source.nodes[0].label)

    def test_import_rejects_secret_shaped_content(self) -> None:
        source = fix_stuck_payment("owner", "payments")
        raw = json.loads(export_runbook(source, "json"))
        raw["nodes"][0]["config"]["authorization"] = "Bearer not-allowed"
        with self.assertRaises(PolicyViolation):
            import_runbook(json.dumps(raw), owner="owner")
