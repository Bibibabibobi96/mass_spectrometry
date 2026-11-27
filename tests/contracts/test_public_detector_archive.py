"""Freeze only the actual trajectory plan for final detector provenance."""
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from msplatform.io.manifest_records import file_record
from msplatform.workflows.native_tracing import _archive_comsol_detector_contract


class DetectorArchiveTests(unittest.TestCase):
    def test_actual_plan_bytes_and_explicit_null_are_preserved_and_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = root / "source_plan.json"
            payload = b'{"detector_active_face":null,"native":"inert fixture"}\n'
            plan.write_bytes(payload)
            facts = root / "source_facts.json"
            facts.write_bytes(b'{"fixture":"inert"}\n')
            reference = {"manifest": {"path": "inert"}, "product_id": "trajectory"}
            trajectory = SimpleNamespace(data_records={"plan": file_record(plan, "required_evidence"),
                                                        "native_facts": file_record(facts, "required_evidence")},
                data_path=lambda key: plan if key == "plan" else facts, reference=reference)
            target = root / "published"
            _archive_comsol_detector_contract(trajectory, target)
            self.assertEqual((target / "detector_plan.json").read_bytes(), payload)
            contract = json.loads((target / "detector_contract.json").read_text(encoding="utf-8"))
            self.assertEqual((target / "detector_native_facts.json").read_bytes(), facts.read_bytes())
            self.assertIsNone(contract["detector_active_face"])
            self.assertEqual(contract["source_reference"], reference)
            facts.write_bytes(b'{"fixture":"tampered"}')
            with self.assertRaisesRegex(ValueError, "facts differ"):
                _archive_comsol_detector_contract(trajectory, root / "tampered_facts")
            facts.write_bytes(b'{"fixture":"inert"}\n')
            plan.write_bytes(b'{"detector_active_face":{}}')
            with self.assertRaisesRegex(ValueError, "protected record"):
                _archive_comsol_detector_contract(trajectory, root / "tampered")
