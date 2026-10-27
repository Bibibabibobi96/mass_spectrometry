import copy
import unittest
from pathlib import Path


from common.contracts.machine_contracts import REPO_ROOT, load_json
from common.contracts.validate_design_request import validate_request


HERE = Path(__file__).resolve().parent


class DesignRequestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_json(REPO_ROOT / "config" / "project_registry.json")
        cls.request = load_json(HERE / "examples" / "oa_tof_500da_r30000.example.json")

    def status(self, request):
        return validate_request(request, self.registry)["status"]

    def multipole_request(self, variant=None):
        request = load_json(HERE / "examples" / "rf_quadrupole_transport.example.json")
        request["target"]["mode"] = None
        if variant is None:
            request["target"].pop("structural_variant_id")
        else:
            request["target"]["structural_variant_id"] = variant
        request["objectives"] = request["objectives"][:1]
        request["design_variables"] = []
        request["evidence_level"] = "static"
        return request

    def test_examples_are_ready(self):
        self.assertEqual(self.status(self.request), "READY")
        rf = load_json(HERE / "examples" / "rf_quadrupole_transport.example.json")
        self.assertEqual(self.status(rf), "READY")

    def accelerator_request(self, variant=None, metric="axial_flight_time"):
        request = copy.deepcopy(self.request)
        request["target"] = {
            "family_id": "orthogonal_pulsed_accelerators",
            "preferred_project_id": "orthogonal_accelerator",
            "function": "orthogonal_acceleration", "mode": None,
        }
        if variant is not None:
            request["target"]["structural_variant_id"] = variant
        request["objectives"] = [{"metric": metric, "operator": "minimize", "value": None, "unit": "us", "tolerance": None}]
        request["constraints"] = []
        request["design_variables"] = []
        request["evidence_level"] = "plan"
        return request

    def test_accelerator_requires_structure_even_when_metric_exists_only_in_three_zone(self):
        result = validate_request(self.accelerator_request(), self.registry)
        self.assertEqual(result["status"], "NEEDS_CLARIFICATION")
        self.assertIsNone(result["selected_capability_id"])
        self.assertIn("structural_variant_id", result["messages"][0])

    def test_accelerator_variants_own_their_metrics_and_do_not_inherit_qualification(self):
        for variant, metric in (("two_zone", "first_time_focus_distance"), ("three_zone", "axial_flight_time")):
            with self.subTest(variant=variant):
                request = self.accelerator_request(variant, metric)
                result = validate_request(request, self.registry)
                self.assertEqual(result["status"], "READY")
                self.assertEqual(result["selected_capability_id"], variant + "_orthogonal_acceleration")
                request["evidence_level"] = "static"
                self.assertEqual(self.status(request), "NEEDS_PROJECT_COMPLETION")
        result = validate_request(self.accelerator_request("two_zone"), self.registry)
        self.assertEqual(result["status"], "NEEDS_PROJECT_COMPLETION")
        self.assertIn("Unsupported metrics: axial_flight_time", result["messages"])
        self.assertEqual(self.status(self.accelerator_request("four_zone")), "UNSUPPORTED")

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
            "family_id": "ion_sources", "preferred_project_id": "apertured_tube_electron_impact_ion_source",
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

    def test_explicit_four_six_and_eight_poles_select_only_owned_capabilities(self):
        project = next(p for p in self.registry["projects"] if p["project_id"] == "rf_multipole_ion_optics")
        for variant in project["structural_variants"]:
            with self.subTest(variant=variant["variant_id"]):
                result = validate_request(self.multipole_request(variant["variant_id"]), self.registry)
                self.assertEqual(result["status"], "READY")
                self.assertEqual(result["selected_project_id"], project["project_id"])
                self.assertIn(result["selected_capability_id"], variant["capability_ids"])

    def test_missing_structure_requires_clarification_before_maturity_selection(self):
        for preferred in ("rf_multipole_ion_optics", None):
            for unset in ("omitted", "null"):
                with self.subTest(preferred=preferred, unset=unset):
                    request = self.multipole_request()
                    request["target"]["preferred_project_id"] = preferred
                    if unset == "null":
                        request["target"]["structural_variant_id"] = None
                    result = validate_request(request, self.registry)
                    self.assertEqual(result["status"], "NEEDS_CLARIFICATION")
                    self.assertIsNone(result["selected_capability_id"])
                    self.assertIn("structural_variant_id", result["messages"][0])

    def test_unknown_structure_does_not_fall_back_to_a_mature_pole(self):
        result = validate_request(self.multipole_request("decapole"), self.registry)
        self.assertEqual(result["status"], "UNSUPPORTED")
        self.assertIsNone(result["selected_project_id"])
        self.assertIsNone(result["selected_capability_id"])

    def test_structure_does_not_inherit_another_poles_maturity_or_metrics(self):
        for variant in ("hexapole", "octupole"):
            with self.subTest(variant=variant):
                request = self.multipole_request(variant)
                request["evidence_level"] = "candidate"
                result = validate_request(request, self.registry)
                self.assertEqual(result["status"], "NEEDS_PROJECT_COMPLETION")
                self.assertTrue(result["selected_capability_id"].startswith(variant + "_"))
                self.assertTrue(any("below requested candidate" in message for message in result["messages"]))
                request["evidence_level"] = "static"
                request["objectives"][0]["metric"] = "rms_beam_radius"
                result = validate_request(request, self.registry)
                self.assertEqual(result["status"], "NEEDS_PROJECT_COMPLETION")
                self.assertIn("Unsupported metrics: rms_beam_radius", result["messages"])

    def test_structure_does_not_inherit_another_poles_function(self):
        request = self.multipole_request("octupole")
        request["target"]["function"] = "collision_cooling"
        result = validate_request(request, self.registry)
        self.assertEqual(result["status"], "NEEDS_NEW_PROJECT")
        self.assertIsNone(result["selected_capability_id"])

    def test_unambiguous_structured_function_does_not_require_variant(self):
        request = self.multipole_request()
        request["target"]["function"] = "mass_filtering"
        result = validate_request(request, self.registry)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["selected_capability_id"], "quadrupole_mass_filter_reference")

    def test_explicit_mode_selects_its_capability_within_the_structure(self):
        for variant in ("hexapole", "octupole"):
            with self.subTest(variant=variant):
                request = self.multipole_request(variant)
                request["target"]["mode"] = variant + "_finite_3d_no_collision"
                result = validate_request(request, self.registry)
                self.assertEqual(result["status"], "READY")
                self.assertEqual(result["selected_capability_id"], variant + "_finite_3d_transport")
                request["target"]["mode"] = "quadrupole_transport_no_collision"
                rejected = validate_request(request, self.registry)
                self.assertEqual(rejected["status"], "NEEDS_PROJECT_COMPLETION")
                self.assertIsNone(rejected["selected_capability_id"])


if __name__ == "__main__":
    unittest.main()
