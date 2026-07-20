import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from compile_execution_plan import compile_execution
from machine_contracts import REPO_ROOT, load_json
from plan_design_request import build_plan


class ExecutionCompilerTests(unittest.TestCase):
    def setUp(self):
        self.registry = REPO_ROOT / "config" / "project_registry.json"
        self.run_id = "20260720_130000__analysis__repo__design-request"

    def compile_request(self, request, bindings=None):
        with tempfile.TemporaryDirectory() as root:
            request_path = Path(root) / "request.json"
            plan_path = Path(root) / "design_plan.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            plan, _ = build_plan(request_path, self.registry, self.run_id)
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            return compile_execution(plan_path, self.registry, bindings)

    def approved_rf_request(self):
        request = load_json(HERE / "examples" / "rf_quadrupole_transport.example.json")
        request["status"] = "approved"
        request["approval"] = {"approved_by": "owner", "approved_on": "2026-07-20"}
        request["operating_points"] = [{"mass": {"value": 100, "unit": "Da"}, "charge_state": 1}]
        request["design_variables"] = ["rf_amplitude", "rf_frequency"]
        return request

    def test_approved_supported_rf_request_is_execution_ready(self):
        result = self.compile_request(self.approved_rf_request())
        self.assertEqual(result["status"], "EXECUTION_READY")
        self.assertTrue(result["safe_to_execute"])
        self.assertEqual(len(result["commands"]), 5)
        self.assertIn("__sim__comsol__", result["commands"][1]["run_id"])

    def test_supported_but_unapproved_request_awaits_approval(self):
        request = self.approved_rf_request()
        request["status"] = "proposed"
        request["approval"] = None
        result = self.compile_request(request)
        self.assertEqual(result["status"], "AWAITING_APPROVAL")
        self.assertFalse(result["safe_to_execute"])

    def test_example_rf_request_exposes_implementation_gaps(self):
        request = load_json(HERE / "examples" / "rf_quadrupole_transport.example.json")
        result = self.compile_request(request)
        self.assertEqual(result["status"], "NEEDS_IMPLEMENTATION")
        self.assertTrue(any("operating points" in item for item in result["blockers"]))
        self.assertTrue(any("design variables" in item for item in result["blockers"]))

    def test_oa_design_request_does_not_masquerade_as_fixed_validation(self):
        request = load_json(HERE / "examples" / "oa_tof_500da_r30000.example.json")
        result = self.compile_request(request)
        self.assertEqual(result["status"], "NEEDS_IMPLEMENTATION")
        self.assertTrue(any("constraints" in item for item in result["blockers"]))
        self.assertTrue(any("outputs" in item for item in result["blockers"]))

    def test_interface_profile_requires_explicit_runtime_bindings(self):
        request = self.approved_rf_request()
        request["target"]["mode"] = "transport_interface_readiness"
        result = self.compile_request(request)
        self.assertEqual(result["status"], "NEEDS_RUNTIME_INPUTS")
        ready = self.compile_request(request, {"particle_table_path": "C:/data/source.ion", "rf_peak_v": "139.81792"})
        self.assertEqual(ready["status"], "EXECUTION_READY")
        self.assertIn("C:/data/source.ion", ready["commands"][1]["argv"])


if __name__ == "__main__":
    unittest.main()
