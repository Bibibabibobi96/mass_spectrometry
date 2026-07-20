import json
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from machine_contracts import REPO_ROOT, sha256
from plan_design_request import build_plan, write_plan


class DesignPlannerTests(unittest.TestCase):
    def setUp(self):
        self.request = HERE / "examples" / "oa_tof_500da_r30000.example.json"
        self.registry = REPO_ROOT / "config" / "project_registry.json"
        self.run_id = "20260720_120000__analysis__repo__design-request"

    def test_build_plan_preserves_selection_and_hashes(self):
        plan, run_config = build_plan(self.request, self.registry, self.run_id)
        self.assertEqual(plan["project_id"], "oa_tof")
        self.assertEqual(plan["capability_id"], "single_reflection_mass_analysis")
        self.assertEqual(plan["provenance"]["request"]["sha256"], sha256(self.request))
        self.assertFalse(run_config["formal_gate_passed"])

    def test_write_plan_creates_standard_role_files(self):
        with tempfile.TemporaryDirectory() as root:
            destination = Path(root) / self.run_id
            plan_path, config_path = write_plan(self.request, self.registry, self.run_id, destination)
            self.assertTrue(plan_path.is_file())
            self.assertTrue(config_path.is_file())
            self.assertEqual(json.loads(config_path.read_text())["run_id"], self.run_id)

    def test_invalid_run_id_is_rejected(self):
        with self.assertRaises(ValueError):
            build_plan(self.request, self.registry, "design_request")


if __name__ == "__main__":
    unittest.main()
