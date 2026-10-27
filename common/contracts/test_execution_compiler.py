import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


from common.contracts.compile_execution_plan import compile_execution, _validate_runtime_structure_binding
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

    def approved_functional_rf_request(self):
        request = self.approved_rf_request()
        request["evidence_level"] = "plan"
        return request

    def functional_bindings(self):
        return {
            "runtime_profile_id": "quadrupole_no_acceleration_full_length",
            "evidence_contract_path": "C:/data/evidence.json",
        }

    def ion_processor_request(self):
        request = self.approved_functional_rf_request()
        request["target"] = {
            "family_id": "rf_ion_accumulation_and_pulsed_extraction",
            "preferred_project_id": "dual_pressure_rectilinear_ion_processor",
            "function": "ion_capture_cooling_and_extraction", "mode": "native_electrode_functional",
        }
        request["operating_points"] = [{"mass": {"value": 524, "unit": "Da"}, "charge_state": 1}]
        request["objectives"] = [{"metric": "extraction_fraction", "operator": "maximize", "value": None, "unit": "1", "tolerance": None}]
        request["design_variables"] = []
        request["constraints"] = []
        request["required_outputs"] = ["simulation_results", "simion_model", "validation_report", "interface_state"]
        return request

    def test_ion_processor_existing_functional_runner_is_discoverable_without_budget_bindings(self):
        result = self.compile_request(self.ion_processor_request())
        self.assertEqual(result["status"], "EXECUTION_READY")
        self.assertEqual(result["profile_id"], "native_functional")
        self.assertEqual([item["step_id"] for item in result["commands"]], ["static_gate", "native_run"])
        command = result["commands"][1]
        self.assertTrue(command["argv"][4].replace("\\", "/").endswith("/simion/run_functional.ps1"))
        self.assertEqual(command["argv"][command["argv"].index("-RunId") + 1], command["run_id"])
        self.assertEqual(command["argv"][-2:], ["-SourceProfile", "functional"])
        self.assertTrue(any("Prototype" in message for message in result["limitations"]))

    def test_ion_processor_profile_rejects_unregistered_physics_and_higher_qualification(self):
        for mass, charge in ((500, 1), (524, -1)):
            request = self.ion_processor_request()
            request["operating_points"] = [{"mass": {"value": mass, "unit": "Da"}, "charge_state": charge}]
            result = self.compile_request(request)
            self.assertEqual(result["status"], "NEEDS_IMPLEMENTATION")
            self.assertFalse(result["safe_to_execute"])
        for level in ("static", "candidate", "formal"):
            request = self.ion_processor_request()
            request["evidence_level"] = level
            with self.assertRaisesRegex(ValueError, "NEEDS_PROJECT_COMPLETION"):
                self.compile_request(request)
        with self.assertRaisesRegex(ValueError, "Unexpected runtime bindings"):
            self.compile_request(self.ion_processor_request(), {"configuration_directory": "unregistered"})

    def test_approved_functional_rf_plan_is_execution_ready(self):
        result = self.compile_request(
            self.approved_functional_rf_request(), self.functional_bindings(),
        )
        self.assertEqual(result["status"], "EXECUTION_READY")
        self.assertTrue(result["safe_to_execute"])
        self.assertEqual(result["profile_id"], "quadrupole_transport_runtime_functional")
        self.assertEqual(len(result["commands"]), 3)
        self.assertEqual(
            [command["step_id"] for command in result["commands"]],
            ["static_gate", "comsol_run", "simion_run"],
        )
        self.assertFalse(
            any(command["step_id"] == "candidate_gate" for command in result["commands"])
        )
        self.assertIn("__sim__comsol__", result["commands"][1]["run_id"])
        for command in result["commands"][1:]:
            self.assertIn("-RuntimeProfileId", command["argv"])
            self.assertIn("quadrupole_no_acceleration_full_length", command["argv"])
            self.assertNotIn("-ParticleSourcePath", command["argv"])
        self.assertIn(result["commands"][1]["run_id"], result["commands"][2]["argv"])
        self.assertTrue(any("does not inherit" in limitation for limitation in result["limitations"]))
        powershell_commands = [
            command for command in result["commands"] if command["shell"] == "powershell"
        ]
        self.assertTrue(powershell_commands)
        for command in powershell_commands:
            self.assertEqual(
                command["argv"][:4],
                ["pwsh.exe", "-NoProfile", "-NonInteractive", "-File"],
            )

    def test_supported_but_unapproved_request_awaits_approval(self):
        request = self.approved_functional_rf_request()
        request["status"] = "proposed"
        request["approval"] = None
        result = self.compile_request(
            request,
            self.functional_bindings(),
        )
        self.assertEqual(result["status"], "AWAITING_APPROVAL")
        self.assertFalse(result["safe_to_execute"])

    def test_functional_profile_does_not_satisfy_candidate_scientific_request(self):
        request = self.approved_rf_request()
        self.assertEqual(request["evidence_level"], "candidate")
        result = self.compile_request(request, self.functional_bindings())
        self.assertEqual(result["status"], "NEEDS_IMPLEMENTATION")
        self.assertFalse(result["safe_to_execute"])
        self.assertIn("Evidence level is not supported: candidate", result["blockers"])

    def test_functional_plan_requires_bound_runtime_and_rejects_free_source_override(self):
        request = self.approved_functional_rf_request()
        result = self.compile_request(request)
        self.assertEqual(result["status"], "NEEDS_RUNTIME_INPUTS")
        self.assertTrue(any("runtime_profile_id" in blocker for blocker in result["blockers"]))
        with self.assertRaisesRegex(ValueError, "Unexpected runtime bindings"):
            self.compile_request(request, {**self.functional_bindings(), "particle_source_path": "C:/data/source.csv"})

    def test_runtime_structure_binding_resolves_all_three_actual_designs(self):
        project = next(p for p in load_json(self.registry)["projects"] if p["project_id"] == "rf_multipole_ion_optics")
        for variant in project["structural_variants"]:
            with self.subTest(variant=variant["variant_id"]):
                _validate_runtime_structure_binding(
                    project, {"capability_id": variant["capability_ids"][0], "required_bindings": ["runtime_profile_id"]},
                    {"runtime_profile_id": variant["variant_id"] + "_no_acceleration_full_length"},
                )

    def test_functional_plan_rejects_unknown_empty_and_cross_structure_runtime(self):
        request = self.approved_functional_rf_request()
        for runtime in ("hexapole_no_acceleration_full_length", "octupole_no_acceleration_full_length"):
            with self.subTest(runtime=runtime), self.assertRaisesRegex(ValueError, "Runtime structural variant"):
                self.compile_request(request, {**self.functional_bindings(), "runtime_profile_id": runtime})
        for runtime, message in (("unknown_profile", "unknown runtime profile"), ("", "must name a registered")):
            with self.subTest(runtime=runtime), self.assertRaisesRegex(ValueError, message):
                self.compile_request(request, {**self.functional_bindings(), "runtime_profile_id": runtime})

    def test_runtime_structure_is_read_from_resolution_not_selector_spelling(self):
        resolved = {"design_profile_resolution": {"profile": {"structural_variant_id": "octupole"}}}
        with patch("projects.rf_multipole_ion_optics.runtime.runtime_profile.resolve_runtime_profile", return_value=resolved):
            with self.assertRaisesRegex(ValueError, "Runtime structural variant"):
                self.compile_request(self.approved_functional_rf_request(), self.functional_bindings())

    def test_complete_bindings_cannot_leave_an_unexpanded_step_argument(self):
        def changed_load(path):
            document = load_json(path)
            if Path(path).name == "execution_profiles.json":
                document = copy.deepcopy(document)
                profile = next(p for p in document["profiles"] if p["profile_id"] == "quadrupole_transport_runtime_functional")
                profile["steps"][1]["arguments"].append("{unregistered_context}")
            return document
        with patch("common.contracts.compile_execution_plan.load_json", side_effect=changed_load):
            with self.assertRaisesRegex(ValueError, "Unresolved execution argument placeholder"):
                self.compile_request(self.approved_functional_rf_request(), self.functional_bindings())

    def mass_filter_request(self):
        request = self.approved_rf_request()
        request["target"]["function"] = "mass_filtering"
        request["target"]["mode"] = "quadrupole_mass_filter_reference"
        request["evidence_level"] = "static"
        request["objectives"] = request["objectives"][:1]
        request["design_variables"] = []
        request["required_outputs"] = ["simulation_results", "simion_model", "validation_report"]
        return request

    def test_mass_filter_uses_its_generated_run_identity_without_overriding_plan(self):
        request = self.mass_filter_request()
        bindings = {"mass_filter_base_source_ion11_path": "C:/data/source.ion",
                    "simion_solver_numerics_contract_path": "C:/data/numerics.json"}
        self.assertEqual(self.compile_request(request)["status"], "NEEDS_RUNTIME_INPUTS")
        result = self.compile_request(request, bindings)
        self.assertEqual(result["status"], "EXECUTION_READY")
        self.assertEqual(result["profile_id"], "quadrupole_mass_filter_simion_functional_reference")
        self.assertEqual([c["step_id"] for c in result["commands"]], ["static_gate", "simion_mass_response"])
        run = result["commands"][1]
        self.assertNotEqual(run["run_id"], self.run_id)
        self.assertEqual(run["argv"][run["argv"].index("-RunId") + 1], run["run_id"])
        with self.assertRaisesRegex(ValueError, "cannot override plan context"):
            self.compile_request(request, {**bindings, "run_id": "forged"})
        request["evidence_level"] = "candidate"
        with self.assertRaisesRegex(ValueError, "NEEDS_PROJECT_COMPLETION"):
            self.compile_request(request, bindings)

    def campaign_request(self, variant):
        request = self.approved_functional_rf_request()
        request["target"]["structural_variant_id"] = variant
        request["target"]["mode"] = variant + "_finite_3d_no_collision"
        request["objectives"] = request["objectives"][:1]
        request["design_variables"] = []
        return request

    def campaign_binding(self, short_variant):
        return {"campaign_path": str(REPO_ROOT / "projects/rf_multipole_ion_optics/config/campaigns/20260731__noacc_vs_segmented_h15_n100.json"),
                "experiment_id": short_variant + "_segmented_h15_n100"}

    def test_campaign_profiles_use_declared_run_identity_and_structure(self):
        for variant, short in (("hexapole", "hex"), ("octupole", "oct")):
            with self.subTest(variant=variant):
                request = self.campaign_request(variant)
                bindings = self.campaign_binding(short)
                document = load_json(Path(bindings["campaign_path"]))
                experiment = next(row for row in document["experiments"] if row["experiment_id"] == bindings["experiment_id"])
                result = self.compile_request(request, bindings)
                self.assertEqual(result["status"], "EXECUTION_READY")
                self.assertEqual(result["profile_id"], variant + "_simion_transport_campaign_engineering")
                self.assertEqual([c["step_id"] for c in result["commands"]], ["static_gate", "simion_campaign_run"])
                self.assertEqual(result["commands"][1]["run_id"], experiment["authorized_run_id"])
                gate = result["commands"][0]["argv"]
                self.assertEqual(gate[gate.index("-StructuralVariant") + 1], variant)
                for command in result["commands"]:
                    self.assertFalse(any("{" in argument for argument in command["argv"]))
                request["evidence_level"] = "candidate"
                with self.assertRaisesRegex(ValueError, "NEEDS_PROJECT_COMPLETION"):
                    self.compile_request(request, bindings)

    def test_current_campaign_previews_with_the_project_relative_runner(self):
        project_root = REPO_ROOT / "projects" / "rf_multipole_ion_optics"
        path = project_root / "config/campaigns/20260731__noacc_vs_segmented_h15_n100.json"
        campaign = load_json(path)
        self.assertEqual(campaign["schema_version"], 7)
        experiment = next(row for row in campaign["experiments"] if row["experiment_id"] == "hex_segmented_h15_n100")
        self.assertIs(experiment["resource_authorization"]["authorized"], False)
        profiles = load_json(project_root / "config/execution_profiles.json")["profiles"]
        profile_id = "hexapole_simion_transport_campaign_engineering"
        profile = next(item for item in profiles if item["profile_id"] == profile_id)
        step = next(item for item in profile["steps"] if item["kind"] == "run")
        self.assertEqual(step["entrypoint"], "runtime/run_simion_transport_campaign.ps1")

        result = self.compile_request(
            self.campaign_request("hexapole"),
            {"campaign_path": str(path), "experiment_id": experiment["experiment_id"]},
        )
        self.assertEqual(result["status"], "EXECUTION_READY")
        self.assertEqual(result["profile_id"], profile_id)
        run = next(command for command in result["commands"] if command["step_id"] == "simion_campaign_run")
        self.assertEqual(run["run_id"], experiment["authorized_run_id"])
        self.assertEqual(
            Path(run["argv"][run["argv"].index("-File") + 1]).resolve(),
            (project_root / "runtime/run_simion_transport_campaign.ps1").resolve(),
        )
        self.assertIn(experiment["experiment_id"], run["argv"])

    def test_campaign_missing_binding_is_a_preview_blocker_not_an_invalid_run_id(self):
        request = self.campaign_request("hexapole")
        bindings = self.campaign_binding("hex")
        for missing in ({}, {"campaign_path": bindings["campaign_path"]}, {"experiment_id": bindings["experiment_id"]}):
            with self.subTest(bindings=missing):
                result = self.compile_request(request, missing)
                self.assertEqual(result["status"], "NEEDS_RUNTIME_INPUTS")
                self.assertFalse(result["safe_to_execute"])
                self.assertIsNone(result["commands"][1]["run_id"])

    def test_campaign_rejects_unknown_cross_structure_and_authorized_id_override(self):
        request = self.campaign_request("hexapole")
        with self.assertRaisesRegex(ValueError, "unknown campaign experiment"):
            self.compile_request(request, {**self.campaign_binding("hex"), "experiment_id": "unknown_experiment"})
        with self.assertRaisesRegex(ValueError, "Runtime structural variant"):
            self.compile_request(request, self.campaign_binding("oct"))
        with self.assertRaisesRegex(ValueError, "cannot override plan context"):
            self.compile_request(request, {**self.campaign_binding("hex"), "authorized_run_id": "forged"})

    def test_example_rf_request_exposes_implementation_gaps(self):
        request = load_json(HERE / "examples" / "rf_quadrupole_transport.example.json")
        result = self.compile_request(request)
        self.assertEqual(result["status"], "NEEDS_IMPLEMENTATION")
        self.assertTrue(any("operating points" in item for item in result["blockers"]))
        self.assertTrue(any("design variables" in item for item in result["blockers"]))
        self.assertIn("Evidence level is not supported: candidate", result["blockers"])

    def test_oa_design_request_does_not_masquerade_as_fixed_validation(self):
        request = load_json(HERE / "examples" / "oa_tof_500da_r30000.example.json")
        result = self.compile_request(request)
        self.assertEqual(result["status"], "NEEDS_IMPLEMENTATION")
        self.assertTrue(any("objectives" in item for item in result["blockers"]))
        self.assertTrue(any("constraints" in item for item in result["blockers"]))
        self.assertTrue(any("outputs" in item for item in result["blockers"]))

    def test_oa_validated_structural_candidate_requires_explicit_seed(self):
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
        ready = self.compile_request(request, {"particle_source_seed": "20260720"})
        self.assertEqual(ready["status"], "EXECUTION_READY")
        self.assertEqual(ready["profile_id"], "validated_structural_candidate")
        self.assertEqual(
            ready["commands"][0]["argv"][1:3],
            ["-m", "projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate"],
        )
        argv = ready["commands"][0]["argv"]
        self.assertIn("--request", argv)
        self.assertIn("--run-id", argv)
        self.assertIn(self.run_id, argv)
        self.assertIn("--particle-source-seed", argv)
        self.assertIn("20260720", argv)

        request["design_variables"] = ["reflectron_midgrid_voltage"]
        variable_ready = self.compile_request(
            request, {"particle_source_seed": "20260720"}
        )
        self.assertEqual(variable_ready["status"], "EXECUTION_READY")
        self.assertEqual(variable_ready["profile_id"], "validated_structural_candidate")

        request["design_variables"] = ["flight_length"]
        unsupported = self.compile_request(
            request, {"particle_source_seed": "20260720"}
        )
        self.assertEqual(unsupported["status"], "NEEDS_IMPLEMENTATION")

    def test_runtime_bindings_reject_unknown_and_plan_owned_context(self):
        request = load_json(HERE / "examples" / "oa_tof_500da_r30000.example.json")
        request["status"] = "approved"
        request["approval"] = {"approved_by": "owner", "approved_on": "2026-07-20"}
        request["target"]["mode"] = "design_candidate"
        request["operating_points"] = [
            {"mass": {"value": 524, "unit": "Da"}, "charge_state": 1}
        ]
        request["objectives"] = [
            {
                "metric": "transmission_fraction",
                "operator": "maximize",
                "value": None,
                "unit": "1",
                "tolerance": None,
            }
        ]
        request["constraints"] = []
        request["design_variables"] = []
        with self.assertRaisesRegex(ValueError, "Unexpected runtime bindings"):
            self.compile_request(
                request,
                {
                    "particle_source_seed": "20260720",
                    "unused_binding": "forbidden",
                },
            )
        for protected in ("request_path", "run_id"):
            with self.subTest(protected=protected), self.assertRaisesRegex(
                ValueError, "cannot override plan context"
            ):
                self.compile_request(
                    request,
                    {
                        "particle_source_seed": "20260720",
                        protected: "C:/forged",
                    },
                )

    def test_interface_profile_requires_explicit_runtime_bindings(self):
        request = self.approved_rf_request()
        request["target"]["mode"] = "quadrupole_transport_interface_readiness"
        result = self.compile_request(request)
        self.assertEqual(result["status"], "NEEDS_RUNTIME_INPUTS")
        ready = self.compile_request(
            request,
            {
                "comsol_particle_source_path": "C:/data/source.csv",
                "simion_particle_source_path": "C:/data/source_canonical.csv",
                "particle_bundle_metadata_path": "C:/data/bundle.json",
                "particle_source_family_path": "C:/data/source_family.json",
                "particle_distribution_path": "C:/data/distribution.json",
                "simion_solver_numerics_contract_path": "C:/data/numerics.json",
                "operating_point_id": "official_100amu_2eV",
            },
        )
        self.assertEqual(ready["status"], "EXECUTION_READY")
        self.assertIn("C:/data/source.csv", ready["commands"][1]["argv"])
        self.assertEqual(len(ready["commands"]), 4)
        for command in ready["commands"]:
            self.assertFalse(any("{" in argument for argument in command["argv"]))


if __name__ == "__main__":
    unittest.main()
