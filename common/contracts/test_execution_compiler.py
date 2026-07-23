import json
import tempfile
import unittest
from pathlib import Path


from common.contracts.compile_execution_plan import compile_execution
from common.contracts.machine_contracts import REPO_ROOT, load_json
from common.contracts.plan_design_request import build_plan


HERE = Path(__file__).resolve().parent


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
        result = self.compile_request(
            self.approved_rf_request(),
            {
                "particle_source_path": "C:/data/source.csv",
                "evidence_contract_path": "C:/data/evidence.json",
            },
        )
        self.assertEqual(result["status"], "EXECUTION_READY")
        self.assertTrue(result["safe_to_execute"])
        self.assertEqual(len(result["commands"]), 5)
        self.assertIn("__sim__comsol__", result["commands"][1]["run_id"])

    def test_supported_but_unapproved_request_awaits_approval(self):
        request = self.approved_rf_request()
        request["status"] = "proposed"
        request["approval"] = None
        result = self.compile_request(
            request,
            {
                "particle_source_path": "C:/data/source.csv",
                "evidence_contract_path": "C:/data/evidence.json",
            },
        )
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
        self.assertTrue(any("objectives" in item for item in result["blockers"]))
        self.assertTrue(any("constraints" in item for item in result["blockers"]))
        self.assertTrue(any("outputs" in item for item in result["blockers"]))

    def test_oa_validated_structural_candidate_requires_matching_plan_binding(self):
        request = load_json(HERE / "examples" / "oa_tof_500da_r30000.example.json")
        request["status"] = "approved"
        request["approval"] = {"approved_by": "owner", "approved_on": "2026-07-20"}
        request["target"]["mode"] = "design_candidate"
        request["operating_points"] = [{"mass": {"value": 524, "unit": "Da"}, "charge_state": 1}]
        request["objectives"] = [
            {"metric": "transmission_fraction", "operator": "maximize", "value": None,
             "unit": "1", "tolerance": None}
        ]
        request["constraints"] = []
        request["design_variables"] = []
        result = self.compile_request(request)
        self.assertEqual(result["status"], "NEEDS_RUNTIME_INPUTS")
        ready = self.compile_request(request, {"candidate_workflow_plan": "C:/candidate/plan.json"})
        self.assertEqual(ready["status"], "EXECUTION_READY")
        self.assertEqual(ready["profile_id"], "validated_structural_candidate")
        self.assertEqual(ready["commands"][0]["argv"][1:3], ["-m", "projects.oa_tof.analysis.run_bound_candidate_workflow"])
        self.assertIn("C:/candidate/plan.json", ready["commands"][0]["argv"])

        request["design_variables"] = ["reflectron_midgrid_voltage"]
        variable_ready = self.compile_request(
            request, {"candidate_workflow_plan": "C:/candidate/midgrid-plan.json"}
        )
        self.assertEqual(variable_ready["status"], "EXECUTION_READY")
        self.assertEqual(variable_ready["profile_id"], "validated_structural_candidate")

        request["design_variables"] = ["flight_length"]
        unsupported = self.compile_request(
            request, {"candidate_workflow_plan": "C:/candidate/flight-plan.json"}
        )
        self.assertEqual(unsupported["status"], "NEEDS_IMPLEMENTATION")

    def test_interface_profile_requires_explicit_runtime_bindings(self):
        request = self.approved_rf_request()
        request["target"]["mode"] = "transport_interface_readiness"
        result = self.compile_request(request)
        self.assertEqual(result["status"], "NEEDS_RUNTIME_INPUTS")
        ready = self.compile_request(
            request,
            {
                "particle_source_path": "C:/data/source.csv",
                "evidence_contract_path": "C:/data/evidence.json",
            },
        )
        self.assertEqual(ready["status"], "EXECUTION_READY")
        self.assertIn("C:/data/source.csv", ready["commands"][1]["argv"])


if __name__ == "__main__":
    unittest.main()
