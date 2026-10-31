from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from common.contracts.machine_contracts import load_json, sha256
from projects.single_reflection_oa_tof_mass_analyzer.analysis.compile_candidate_design import EnvelopeReviewRequired, write_candidate
from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.prepare_candidate_consumers import prepare, verify_routing_coverage
from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_formal_promotion import prepare as prepare_promotion

from projects.single_reflection_oa_tof_mass_analyzer.tests.analysis.test_support.candidate_fixtures import (
    CandidateFixtures,
    PROJECT_ROOT,
    REPO_ROOT,
)


class CandidateDesignTests(CandidateFixtures, unittest.TestCase):
    def test_zero_change_reproduces_formal_baseline_and_resolved_physics(self):
        request = self.base_request()
        request["constraints"] = []
        candidate, report, _ = self.compile(request, [])
        self.assertEqual(candidate, load_json(PROJECT_ROOT / "config" / "baseline.json"))
        self.assertTrue(report["zero_change_reference_reproduction"])
        baseline_out, resolved_out, report_out = self.compile(request, [], write=True)
        formal_resolved = load_json(PROJECT_ROOT / "config" / "resolved_geometry.json")
        self.assertEqual(resolved_out["geometry_mm"], formal_resolved["geometry_mm"])
        self.assertEqual(resolved_out["electrodes_V"], formal_resolved["electrodes_V"])
        self.assertTrue(report_out["zero_change_reference_reproduction"])


    def test_candidate_resolved_publication_is_independent_of_scratch_path(self):
        request = self.base_request()
        request["constraints"] = []
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            request_path = root_path / "design_request.json"
            proposal_path = root_path / "candidate_proposal.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            proposal_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "role": "design_candidate_proposal",
                        "candidate_id": "stable_resolved_identity",
                        "project_id": "single_reflection_oa_tof_mass_analyzer",
                        "request": {
                            "path": str(request_path),
                            "sha256": sha256(request_path),
                        },
                        "values": [],
                    }
                ),
                encoding="utf-8",
            )
            first = write_candidate(proposal_path, root_path / "run_a" / "contracts")[1]
            second = write_candidate(proposal_path, root_path / "run_b" / "contracts")[1]
            self.assertEqual(first.read_bytes(), second.read_bytes())
            inputs = load_json(first)["inputs"]
            self.assertEqual(
                inputs["baseline"], "run_input:candidate_baseline.json"
            )
            self.assertEqual(
                inputs["solver_numerics"],
                "run_input:candidate_solver_numerics.json",
            )
            self.assertNotIn(str(root_path.resolve()), first.read_text(encoding="utf-8"))


    def test_flight_compaction_requires_internal_reoptimization(self):
        request = self.base_request()
        request["design_variables"] = ["flight_length"]
        with self.assertRaisesRegex(ValueError, "stage-2 ring gap"):
            self.compile(request, [{"variable": "flight_length", "value": 300.0, "unit": "mm"}])

        request["design_variables"] = ["flight_length", "reflectron_ring_thickness"]
        candidate, report, _ = self.compile(
            request,
            [
                {"variable": "flight_length", "value": 300.0, "unit": "mm"},
                {"variable": "reflectron_ring_thickness", "value": 2.5, "unit": "mm"},
            ],
        )
        self.assertEqual(candidate["geometry_mm"]["L_flight"], 300.0)
        self.assertLess(candidate["geometry_mm"]["shield_outer_z_max"], 871.8328)
        self.assertTrue(any(item["variable"] == "flight_length" for item in report["changed_variables"]))


    def test_accelerator_variable_can_grow_bidirectionally(self):
        request = self.base_request()
        request["constraints"] = []
        request["design_variables"] = ["accelerator_ring_width"]
        candidate, _, _ = self.compile(
            request, [{"variable": "accelerator_ring_width", "value": 6.0, "unit": "mm"}]
        )
        self.assertEqual(candidate["geometry_mm"]["accelerator_ring_width"], 6.0)


    def test_accelerator_length_and_voltage_rederive_focus_without_tof_envelope_block(self):
        request = self.base_request()
        request["constraints"] = []
        request["design_variables"] = ["accelerator_stage2_length", "accelerator_grid1_voltage"]
        with self.assertRaisesRegex(ValueError, "time focus"):
            self.compile(
                request,
                [
                    {"variable": "accelerator_stage2_length", "value": 20.0, "unit": "mm"},
                    {"variable": "accelerator_grid1_voltage", "value": 1700.0, "unit": "V"},
                ],
            )
        candidate, resolved, _ = self.compile(
            request,
            [
                {"variable": "accelerator_stage2_length", "value": 20.0, "unit": "mm"},
                {"variable": "accelerator_grid1_voltage", "value": 1900.0, "unit": "V"},
            ],
            write=True,
        )
        geometry = candidate["geometry_mm"]
        accelerator = candidate["geometry_derivation"]["accelerator"]
        self.assertEqual(geometry["L_accel"], 23.0)
        self.assertAlmostEqual(
            geometry["accelerator_grid2_z"] + accelerator["focus_drift_after_grid2_mm"],
            geometry["accelerator_focus_z"],
        )
        self.assertEqual(resolved["geometry_mm"], geometry)


    def test_noninteger_electrode_count_is_rejected(self):
        request = self.base_request()
        request["constraints"] = []
        request["design_variables"] = ["reflectron_stage1_electrode_count"]
        with self.assertRaisesRegex(ValueError, "integer"):
            self.compile(request, [{"variable": "reflectron_stage1_electrode_count", "value": 7.5, "unit": "count"}])


    def test_invalid_radial_order_is_rejected(self):
        request = self.base_request()
        request["constraints"] = []
        request["design_variables"] = ["reflectron_bore_radius"]
        with self.assertRaisesRegex(ValueError, "radial order"):
            self.compile(request, [{"variable": "reflectron_bore_radius", "value": 320.0, "unit": "mm"}])


    def test_shared_shield_radius_contains_offset_detector(self):
        request = self.base_request()
        request["constraints"] = []
        request["design_variables"] = [
            "reflectron_bore_radius",
            "reflectron_ring_outer_radius",
            "reflectron_shield_inner_radius",
        ]
        with self.assertRaisesRegex(
            ValueError, "shared flight-tube/reflectron shield inner radius"
        ):
            self.compile(
                request,
                [
                    {"variable": "reflectron_bore_radius", "value": 25.0, "unit": "mm"},
                    {"variable": "reflectron_ring_outer_radius", "value": 60.0, "unit": "mm"},
                    {"variable": "reflectron_shield_inner_radius", "value": 88.0, "unit": "mm"},
                ],
            )


    def test_shared_shield_radius_accepts_exact_transverse_envelope(self):
        request = self.base_request()
        request["constraints"] = []
        request["design_variables"] = [
            "reflectron_bore_radius",
            "reflectron_ring_outer_radius",
            "reflectron_shield_inner_radius",
        ]
        candidate, _, _ = self.compile(
            request,
            [
                {"variable": "reflectron_bore_radius", "value": 25.0, "unit": "mm"},
                {"variable": "reflectron_ring_outer_radius", "value": 60.0, "unit": "mm"},
                {"variable": "reflectron_shield_inner_radius", "value": 88.8, "unit": "mm"},
            ],
        )
        self.assertEqual(candidate["geometry_mm"]["flight_tube_r"], 88.8)


    def test_larger_tof_requests_envelope_review_instead_of_being_impossible(self):
        request = self.base_request()
        request["constraints"] = []
        request["design_variables"] = ["flight_length"]
        with self.assertRaisesRegex(EnvelopeReviewRequired, "NEEDS_ENVELOPE_REVIEW"):
            self.compile(request, [{"variable": "flight_length", "value": 700.0, "unit": "mm"}])


    def test_midgrid_voltage_outside_narrow_envelope_requires_review(self):
        request = self.base_request()
        request["constraints"] = []
        request["design_variables"] = ["reflectron_midgrid_voltage"]
        with self.assertRaisesRegex(EnvelopeReviewRequired, "NEEDS_ENVELOPE_REVIEW"):
            self.compile(
                request,
                [{"variable": "reflectron_midgrid_voltage", "value": 1599.0, "unit": "V"}],
            )


    def test_candidate_generates_nonformal_simion_text_from_frozen_contract(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "prepared"
            generated = prepare(
                PROJECT_ROOT / "config" / "resolved_geometry.json",
                output,
                particle_source_seed=20260713,
            )
            resolved = (output / "simion" / "oatof_resolved.lua").read_text(encoding="utf-8")
            fly2 = (output / "simion" / "oatof_ideal_grounded.fly2").read_text(encoding="utf-8")
            frozen = json.loads(
                (PROJECT_ROOT / "config" / "resolved_geometry.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIn(frozen["inputs"]["solver_numerics_sha256"], resolved)
            self.assertIn("seed(20260713)", fly2)
            self.assertFalse((output / "simion" / "oatof_ideal_grounded.iob").exists())
            self.assertEqual(set(generated), {"resolved_lua", "program", "fly2"})
            self.assertFalse((output / "candidate_consumption_plan.json").exists())


    def test_nonzero_candidate_routes_one_contract_to_all_consumers(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            candidate = load_json(PROJECT_ROOT / "config" / "resolved_geometry.json")
            candidate["geometry_mm"]["accelerator_ring_width"] = 6.0
            contract_path = root_path / "candidate_resolved_geometry.json"
            contract_path.write_text(json.dumps(candidate), encoding="utf-8")
            generated = prepare(
                contract_path,
                root_path / "prepared",
                particle_source_seed=20260713,
            )
            program = generated["program"]
            self.assertIn("adjustable accelerator_ring_width_mm=6.0", program.read_text(encoding="utf-8"))


    def test_comsol_contract_is_the_only_reflectron_voltage_source(self):
        source = (PROJECT_ROOT / "comsol" / "oatof_build_model_core.m").read_text(
            encoding="utf-8"
        )
        self.assertIn("requires a resolved contract path", source)
        self.assertIn("reflectron_midgrid_voltage_v = voltageV.midgrid", source)
        self.assertIn("reflectron_backplate_voltage_v = voltageV.backplate", source)
        self.assertIn("d2_mm = geometryMm.L_stage2", source)
        self.assertNotIn("if ~isempty(contract_path)", source)
        self.assertNotIn("Legacy positional", source)


    def test_solidworks_step_import_binds_clean_part_template_temporarily(self):
        source = (REPO_ROOT / "common" / "solidworks" / "import_step_to_solidworks.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("CLEAN_PART_TEMPLATE", source)
        self.assertIn("SW_DEFAULT_TEMPLATE_PART, str(CLEAN_PART_TEMPLATE)", source)
        self.assertIn("SW_ALWAYS_USE_DEFAULT_TEMPLATES, True", source)
        self.assertIn("SW_DEFAULT_TEMPLATE_PART, original_part_template", source)
        self.assertIn("original_always_use_default_templates", source)
        self.assertIn("step_paths = [path.resolve() for path in step_paths]", source)


    def test_solidworks_bridge_uses_module_context_for_frozen_code_root(self):
        bridge = REPO_ROOT / "common" / "solidworks" / "import_step_to_solidworks.m"
        source = bridge.read_text(encoding="utf-8")
        self.assertIn(
            "codeRoot = fileparts(fileparts(fileparts(mfilename('fullpath'))))",
            source,
        )
        self.assertIn("codeRoot = resolve_code_root()", source)
        self.assertIn("setenv('PYTHONPATH'", source)
        self.assertIn("setenv('PYTHONDONTWRITEBYTECODE', '1')", source)
        self.assertIn("-B -m common.solidworks.import_step_to_solidworks", source)
        self.assertIn("cleanupPythonPath", source)
        self.assertIn("cleanupBytecodePolicy", source)

        with tempfile.TemporaryDirectory() as root:
            code_root = Path(root) / "frozen_code"
            solidworks = code_root / "common" / "solidworks"
            solidworks.mkdir(parents=True)
            for name in ("import_step_to_solidworks.py", "installation.py"):
                shutil.copy2(REPO_ROOT / "common" / "solidworks" / name, solidworks / name)
            (code_root / "pythoncom.py").write_text("", encoding="utf-8")
            win32com = code_root / "win32com"
            win32com.mkdir()
            (win32com / "__init__.py").write_text("", encoding="utf-8")
            (win32com / "client.py").write_text("", encoding="utf-8")
            working_directory = Path(root) / "outside_frozen_code"
            working_directory.mkdir()
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(code_root)
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "common.solidworks.import_step_to_solidworks",
                    "--help",
                ],
                cwd=working_directory,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--manifest", result.stdout)
            self.assertFalse(any(code_root.rglob("__pycache__")))
            self.assertFalse(any(code_root.rglob("*.pyc")))


    def test_missing_consumer_route_is_rejected(self):
        consumer_contract = load_json(PROJECT_ROOT / "config" / "candidate_consumers.json")
        variable_catalog = load_json(PROJECT_ROOT / "config" / "design_variables.json")
        del consumer_contract["consumers"]["cad"]
        with self.assertRaisesRegex(ValueError, "candidate consumer routing is incomplete"):
            verify_routing_coverage(consumer_contract, variable_catalog)


    def test_formal_promotion_requires_passing_candidate_acceptance(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            candidate = root_path / "candidate.mph"
            candidate.write_bytes(b"candidate")
            acceptance = root_path / "acceptance.json"
            acceptance.write_text(json.dumps({
                "role": "oa_tof_candidate_acceptance",
                "status": "failed",
                "formal_modified": False,
                "promotion_authorized": False,
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "pre-promotion"):
                prepare_promotion(
                    candidate, acceptance, root_path / "transaction.json",
                    root_path / "formal",
                )


    def test_formal_promotion_authorizes_only_exact_destinations(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            candidate = root_path / "candidate.mph"
            candidate.write_bytes(b"candidate")
            acceptance = root_path / "acceptance.json"
            acceptance.write_text(json.dumps({
                "role": "oa_tof_candidate_acceptance",
                "status": "success",
                "formal_modified": False,
                "promotion_authorized": False,
            }), encoding="utf-8")
            output = root_path / "transaction.json"
            transaction = prepare_promotion(
                candidate, acceptance, output, root_path / "formal",
            )
            self.assertEqual(transaction["status"], "authorized")
            self.assertEqual(
                transaction["destinations"]["comsol_model"],
                str(
                    (
                        root_path
                        / "formal"
                        / "comsol"
                        / "single_reflection_oa_tof_mass_analyzer__model.mph"
                    ).resolve()
                ),
            )
            self.assertEqual(
                transaction["destinations"]["cad_root"],
                str((root_path / "formal" / "cad").resolve()),
            )


    def test_legacy_placeholder_layout_source_is_nonphysical_and_has_fixed_slot_order(self):
        gem = (PROJECT_ROOT / "simion" / "workbench" / "candidate_layout_placeholder.gem").read_text(encoding="utf-8")
        builder = (PROJECT_ROOT / "simion" / "workbench" / "build_candidate_layout_placeholders.ps1").read_text(encoding="utf-8")
        self.assertIn("Non-physical PA", gem)
        self.assertNotIn("2240", gem)
        self.assertNotIn("524", gem)
        self.assertIn("flight_tube_ground.pa0', 'reflectron.pa0', 'accelerator.pa0', 'detector_ground.pa0", builder)
        self.assertIn("physical_model = $false", builder)
        self.assertIn("build_candidate_layout_placeholders.lua", builder)


    def _explicit_numerics_proposal(self, root):
        request = self.base_request()
        request.update(constraints=[], design_variables=[])
        request_path = root / "design_request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        proposal = root / "candidate_proposal.json"
        proposal.write_text(json.dumps(dict(schema_version=1, role="design_candidate_proposal",
            candidate_id="explicit_numerics", project_id=PROJECT_ROOT.name,
            request=dict(path=str(request_path), sha256=sha256(request_path)), values=[])), encoding="utf-8")
        return proposal

    def test_explicit_solver_numerics_freezes_external_data_without_changing_physics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proposal = self._explicit_numerics_proposal(root)
            external = root / "external data/coarse.json"
            external.parent.mkdir()
            numerics = load_json(PROJECT_ROOT / "config/formal_solver_numerics.json")
            numerics["comsol"].update(routine_reflectron_hmax_mm=80., routine_accelerator_hmax_mm=8.,
                                      fine_output_step_ns=5., field_free_output_step_ns=100.)
            payload = json.dumps(numerics, indent=2).replace("\n", "\r\n").encode("utf-8")
            external.write_bytes(payload)
            baseline, resolved, report = write_candidate(proposal, root / "explicit", solver_numerics_contract=external)
            self.assertEqual(external.read_bytes(), payload)
            frozen = resolved.with_name("candidate_solver_numerics.json")
            self.assertEqual(frozen.read_bytes(), payload)
            document = load_json(resolved)
            self.assertEqual(document["comsol_runtime"], numerics["comsol"])
            self.assertEqual(document["inputs"]["solver_numerics_sha256"], sha256(frozen))
            self.assertEqual(load_json(report)["provenance"]["solver_numerics"], dict(path=str(external.resolve()), sha256=sha256(frozen)))
            self.assertFalse(load_json(report)["zero_change_reference_reproduction"])
            default_baseline, default_resolved, default_report = write_candidate(proposal, root / "default")
            self.assertTrue(load_json(default_report)["zero_change_reference_reproduction"])
            self.assertEqual(baseline.read_bytes(), default_baseline.read_bytes())
            default = load_json(default_resolved)
            for key in ("geometry_mm", "electrodes_V", "particle_source", "coordinate_convention", "validation_target", "particle_count_policy", "rings"):
                self.assertEqual(document[key], default[key])
            self.assertEqual(default_resolved.with_name("candidate_solver_numerics.json").read_bytes(),
                             (PROJECT_ROOT / "config/formal_solver_numerics.json").read_bytes())
            original = resolved.read_bytes()
            external.write_text("{}", encoding="utf-8")
            self.assertEqual(frozen.read_bytes(), payload)
            self.assertEqual(resolved.read_bytes(), original)

    def test_explicit_solver_numerics_keeps_existing_rejection_policies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proposal = self._explicit_numerics_proposal(root)
            original = load_json(PROJECT_ROOT / "config/formal_solver_numerics.json")
            import copy
            for case in ("role", "missing_layer", "solver_steps", "times_to_store"):
                with self.subTest(case=case):
                    document = copy.deepcopy(original)
                    if case == "role":
                        document["role"] = "unrelated_contract"
                    elif case == "missing_layer":
                        document.pop("comsol")
                    else:
                        document["comsol"][case] = "unsupported_policy"
                    path = root / (case + ".json")
                    path.write_text(json.dumps(document), encoding="utf-8")
                    before = path.read_bytes()
                    with self.assertRaises(ValueError):
                        write_candidate(proposal, root / case, solver_numerics_contract=path)
                    self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(FileNotFoundError):
                write_candidate(proposal, root / "missing", solver_numerics_contract=root / "absent.json")
            self.assertFalse((root / "missing").exists())

    def test_candidate_compile_cli_transports_explicit_solver_numerics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proposal = self._explicit_numerics_proposal(root)
            contract = root / "coarse.json"
            document = load_json(PROJECT_ROOT / "config/formal_solver_numerics.json")
            document["comsol"]["routine_accelerator_hmax_mm"] = 8.
            contract.write_text(json.dumps(document), encoding="utf-8")
            output = root / "compiled"
            result = subprocess.run([sys.executable, "-I", "-B", "-c",
                "import sys;sys.path.insert(0,sys.argv[1]);sys.argv=sys.argv[2:];"
                "from projects.single_reflection_oa_tof_mass_analyzer.analysis.compile_candidate_design import main;main()",
                str(REPO_ROOT), "compile_candidate_design", str(proposal), "--output-dir", str(output),
                "--solver-numerics-contract", str(contract)], cwd=root, capture_output=True,
                text=True, encoding="utf-8", timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("CANDIDATE_COMPILE=PASS", result.stdout)
            self.assertEqual(load_json(output / "candidate_resolved_geometry.json")["comsol_runtime"], document["comsol"])

    def test_explicit_solver_mesh_and_time_numbers_reject_before_native(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proposal = self._explicit_numerics_proposal(root)
            original = load_json(PROJECT_ROOT / "config/formal_solver_numerics.json")
            import copy
            for key in ("routine_reflectron_hmax_mm", "routine_accelerator_hmax_mm", "convergence_accelerator_hmax_mm",
                        "fine_output_step_ns", "field_free_output_step_ns"):
                for index, value in enumerate((True, False, 0, -1, float("nan"), float("inf"))):
                    with self.subTest(key=key, value=value):
                        document = copy.deepcopy(original)
                        document["comsol"][key] = value
                        source = root / (key + str(index) + ".json")
                        source.write_text(json.dumps(document), encoding="utf-8")
                        with self.assertRaisesRegex(ValueError, "finite positive number"):
                            write_candidate(proposal, root / (key + str(index)), solver_numerics_contract=source)





    def test_explicit_solver_numerics_rejects_unknown_or_noninteger_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proposal = self._explicit_numerics_proposal(root)
            for index, version in enumerate((0, 2, True, 1.0)):
                with self.subTest(version=version):
                    document = load_json(PROJECT_ROOT / "config/formal_solver_numerics.json")
                    document["schema_version"] = version
                    source = root / ("version" + str(index) + ".json")
                    source.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "schema_version"):
                        write_candidate(proposal, root / ("output" + str(index)), solver_numerics_contract=source)


if __name__ == "__main__":
    unittest.main()
