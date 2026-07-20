import copy
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from machine_contracts import REPO_ROOT, load_json
from validate_design_request import validate_request


class DesignRequestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_json(REPO_ROOT / "config" / "project_registry.json")
        cls.request = load_json(HERE / "examples" / "oa_tof_500da_r30000.example.json")

    def status(self, request):
        return validate_request(request, self.registry)["status"]

    def test_examples_are_ready(self):
        self.assertEqual(self.status(self.request), "READY")
        rf = load_json(HERE / "examples" / "rf_quadrupole_transport.example.json")
        self.assertEqual(self.status(rf), "READY")

    def test_mass_without_unit_needs_clarification(self):
        request = copy.deepcopy(self.request)
        del request["operating_points"][0]["mass"]["unit"]
        self.assertEqual(self.status(request), "NEEDS_CLARIFICATION")

    def test_contradictory_bounds_need_clarification(self):
        request = copy.deepcopy(self.request)
        request["constraints"].append({"parameter": "flight_length", "operator": ">=", "value": 400, "unit": "mm"})
        self.assertEqual(self.status(request), "NEEDS_CLARIFICATION")

    def test_unapproved_formal_request_needs_clarification(self):
        request = copy.deepcopy(self.request)
        request["evidence_level"] = "formal"
        self.assertEqual(self.status(request), "NEEDS_CLARIFICATION")

    def test_threshold_objective_requires_value(self):
        request = copy.deepcopy(self.request)
        request["objectives"][0]["value"] = None
        self.assertEqual(self.status(request), "NEEDS_CLARIFICATION")

    def test_prototype_cannot_supply_formal_assets(self):
        request = copy.deepcopy(self.request)
        request["request_id"] = "ei_formal_request"
        request["status"] = "approved"
        request["approval"] = {"approved_by": "owner", "approved_on": "2026-07-20"}
        request["target"] = {
            "family_id": "ion_sources", "preferred_project_id": "electron_impact_ion_source",
            "function": "ionization_yield_feasibility", "mode": None
        }
        request["objectives"] = [{"metric": "ionization_yield", "operator": "maximize", "value": None, "unit": "1", "tolerance": None}]
        request["constraints"] = []
        request["design_variables"] = []
        request["required_outputs"] = ["comsol_model", "cad"]
        request["evidence_level"] = "formal"
        self.assertEqual(self.status(request), "NEEDS_PROJECT_COMPLETION")

    def test_new_multipole_function_needs_new_project(self):
        request = copy.deepcopy(self.request)
        request["target"] = {
            "family_id": "rf_multipole_ion_optics", "preferred_project_id": None,
            "function": "hexapole_ion_guiding", "mode": None
        }
        self.assertEqual(self.status(request), "NEEDS_NEW_PROJECT")

    def test_unknown_variable_needs_project_completion(self):
        request = copy.deepcopy(self.request)
        request["design_variables"].append("imaginary_knob")
        self.assertEqual(self.status(request), "NEEDS_PROJECT_COMPLETION")


if __name__ == "__main__":
    unittest.main()
