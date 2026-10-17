"""Pure voltage compilation and existing sealed-source provider contract tests."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.corridor_field_provider import (
    TASK_SOURCE, candidate_authority, derive_candidate_authority, compile_request, prepare, finalize, resolve_completed_provider,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import load_binding
from common.contracts.write_run_manifest import build_run_manifest, publish_terminal_state


class CandidateAuthorityTest(unittest.TestCase):
    def test_frozen_provider_imports_from_public_root_context(self) -> None:
        repo = Path(__file__).resolve().parents[4]
        with tempfile.TemporaryDirectory(prefix="mrtof-provider-import-") as directory:
            inputs = Path(directory)
            frozen = inputs / "corridor_field_provider.py"
            shutil.copyfile(repo / "projects/parallel_mirror_dual_stripe_mr_tof/analysis/corridor_field_provider.py", frozen)
            (inputs / "plan.json").write_text(json.dumps({"repo_root": str(repo)}), encoding="utf-8")
            environment = dict(os.environ)
            environment.pop("PYTHONPATH", None)
            command = (
                ". '" + str(repo / "common/contracts/run_artifact_support.ps1").replace("'", "''") + "'; "
                "Invoke-RunToolRootContext -RepoRoot '" + str(repo).replace("'", "''") + "' -Operation { "
                "& '" + sys.executable.replace("'", "''") + "' '" + str(frozen).replace("'", "''") + "' --help; "
                "if ($LASTEXITCODE -ne 0) { throw 'Frozen provider import failed' } }"
            )
            result = subprocess.run(["pwsh", "-NoProfile", "-Command", command],
                                    cwd=inputs, env=environment, timeout=30,
                                    capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("--finalize", result.stdout)

    def setUp(self) -> None:
        self.authority = {"analyzer_electrode_voltages_v": list(range(20)),
                          "component_voltages_v": [{"voltage_v": 1}], "assembly": {"pose": [0,1,2]}}
        self.candidate = dict(s1=-27.1,s2=54.7,p1=191.2,p2=-190.6)

    def test_only_four_physical_groups_change(self) -> None:
        result = candidate_authority(self.authority,self.candidate)
        self.assertEqual(result["analyzer_electrode_voltages_v"][10:14],[-27.1,-27.1,54.7,54.7])
        self.assertEqual(result["analyzer_electrode_voltages_v"][15:17],[191.2,-190.6])
        self.assertEqual(result["analyzer_electrode_voltages_v"][:10],list(range(10)))
        self.assertEqual(result["analyzer_electrode_voltages_v"][17:],list(range(17,20)))
        self.assertEqual(result["component_voltages_v"],self.authority["component_voltages_v"])
        self.assertEqual(result["assembly"],self.authority["assembly"])
        self.assertEqual(self.authority["analyzer_electrode_voltages_v"],list(range(20)))

    def test_missing_or_extra_voltage_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError,"exactly"):
            candidate_authority(self.authority,dict(s1=0,s2=0,p1=0))
        with self.assertRaisesRegex(ValueError,"exactly"):
            candidate_authority(self.authority,dict(self.candidate,mirror=0))

    def test_nonfinite_candidate_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError,"finite"):
            candidate_authority(self.authority,dict(self.candidate,p2=float("nan")))

    def test_absolute_mirror_target_is_repeated_not_accumulated(self) -> None:
        target = [0,100,200,300,5000]
        first = candidate_authority(self.authority,self.candidate,mirror_voltages_v=target)
        second = candidate_authority(first,dict(self.candidate,p1=192),mirror_voltages_v=target)
        self.assertEqual(first["analyzer_electrode_voltages_v"][:10],target*2)
        self.assertEqual(second["analyzer_electrode_voltages_v"][:10],target*2)
        self.assertEqual(second["component_voltages_v"],self.authority["component_voltages_v"])
        for bad in ([0,1], [0,1,2,3,float("nan")]):
            with self.assertRaisesRegex(ValueError,"five finite"):
                candidate_authority(self.authority,self.candidate,mirror_voltages_v=bad)

    def test_incomplete_authority_rejected(self) -> None:
        bad = copy.deepcopy(self.authority)
        bad["analyzer_electrode_voltages_v"].pop()
        with self.assertRaisesRegex(ValueError,"twenty"):
            candidate_authority(bad,self.candidate)

    def test_authority_derivation_does_not_read_field_solve_metadata(self) -> None:
        request = dict(schema_version=1, role="mrtof_same_mesh_field_provider_request",
                       candidate_voltages_v=self.candidate)
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.corridor_field_provider"
        with patch(module+".read", side_effect=AssertionError("No unconsumed model metadata")):
            actual, references = derive_candidate_authority(request, self.authority)
        self.assertEqual(actual, candidate_authority(self.authority, self.candidate))
        self.assertEqual(references, {})

    def test_authority_derivation_rejects_missing_mirror_reference(self) -> None:
        request = dict(schema_version=1, role="mrtof_same_mesh_field_provider_request",
                       candidate_voltages_v=self.candidate, mirror_voltage_variation_path="variation.json")
        with self.assertRaises((KeyError, ValueError)):
            derive_candidate_authority(request, self.authority)

    def test_saved_solver_and_selected_mesh_are_consumed(self) -> None:
        self.assertIn("stats.selection().geom('geom1',3).set",TASK_SOURCE)
        self.assertIn("model.sol(char(p.export_grid.solution_tag)).runAll",TASK_SOURCE)
        self.assertNotIn("createAutoSequence",TASK_SOURCE)
        self.assertNotIn("mesh.run",TASK_SOURCE)
        self.assertNotIn("geom.run",TASK_SOURCE)

    def test_only_reviewed_cg_and_manual_fgmres_paths_are_generated(self) -> None:
        # Source contract only; this does not execute or qualify a COMSOL field.
        readback = TASK_SOURCE.split("function out = solverReadback(model)", 1)[1]
        self.assertIn('if method=="cg"\n    mg = i.feature(\'mg1\');', readback)
        self.assertIn('elseif method=="fgmres"\n    mg = i.feature(\'gmg1\');', readback)
        self.assertIn("error('MRTOF:SolverPath'", readback)
        self.assertIn('out.mg_prefun=="amg"', readback)
        self.assertIn('out.mg_prefun=="gmg" && out.mg_casegen=="manual"', readback)
        self.assertIn("isequal(out.iterative_active_children,{'gmg1'})", readback)
        for forbidden in (".set(", ".create(", ".active("):
            self.assertNotIn(forbidden, readback)

    def test_updated_voltage_clears_only_selected_solution_data_before_run(self) -> None:
        # COMSOL 6.4 clearSolutionData preserves solver and result features.
        clear = "model.sol(char(p.export_grid.solution_tag)).clearSolutionData;"
        run = "model.sol(char(p.export_grid.solution_tag)).runAll;"
        self.assertEqual(TASK_SOURCE.count(clear), 1)
        self.assertLess(TASK_SOURCE.index("update_corridor_workpoint_voltages(model,source,target)"),
                        TASK_SOURCE.index(clear))
        self.assertLess(TASK_SOURCE.index("saveJson(fullfile(task,'voltage_readback.json')"),
                        TASK_SOURCE.index(clear))
        self.assertLess(TASK_SOURCE.index(clear), TASK_SOURCE.index(run))
        self.assertNotIn(".clearSolution;", TASK_SOURCE)
        self.assertNotIn("model.sol().clear", TASK_SOURCE)

    def test_manual_hierarchy_and_smoothers_are_read_back_before_and_after(self) -> None:
        # Match actual stored fine/coarse bindings, not the mere existence of a node.
        for guard in (
            'out.fine_order=="2" && out.fine_discretization=="physics"',
            "isequal(out.manual_levels,{'mgl1'})",
            'out.coarse_mesh=="mesh1"',
            'out.coarse_discretization=="disc1" && out.coarse_order=="1"',
            "isequal(out.mg_caseuse,{'mgl1'}) && isequal(out.mg_caseassem,{'mgl1'})",
            'out.mg_levels==1 && out.mg_prefermatfree && out.mg_assemble=="on"',
            'out.mg_keep=="on" && out.matrix_format=="matrixfree"',
            "isequal(record.active_children,{'kr1'})",
            'record.solver=="gmres"',
            'record.termination=="iter" && record.iterations==2 && isempty(record.preconditioners)',
            "isequal(out.coarse_active_children,{'amg1'})",
            'out.coarse_solver=="amg"',
        ):
            with self.subTest(guard=guard):
                self.assertIn(guard, TASK_SOURCE)
        self.assertIn("cell(step.mglevel().tags())", TASK_SOURCE)
        self.assertIn("level.mesh('geom1')", TASK_SOURCE)
        self.assertIn("level.discretization('es')", TASK_SOURCE)
        self.assertEqual(TASK_SOURCE.count("solverReadback(model);"), 2)
        self.assertIn("assert(isequaln(before,after)", TASK_SOURCE)
        self.assertLess(TASK_SOURCE.index("before = solverReadback"),
                        TASK_SOURCE.index("update_corridor_workpoint_voltages"))
        self.assertLess(TASK_SOURCE.index("model.sol(char(p.export_grid.solution_tag)).runAll"),
                        TASK_SOURCE.index("after = solverReadback"))
        self.assertLess(TASK_SOURCE.index("assert(isequaln(before,after)"),
                        TASK_SOURCE.index("export_corridor_scalar_field"))


class SourceMeshAndExportPlanTest(unittest.TestCase):
    """Small sealed-receipt fixtures; never load COMSOL or read large assets."""

    def compile_fixture(self, *, mesh="mesh2", plan_name="diagnostic_plan.json",
                        legacy=False, mismatch=None, pitch=(.25,.25,.25), launcher_options=None):
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.corridor_field_provider"
        root = Path("/provider-fixture")
        field, export = root / "field", root / "export"
        model = field / "source.mph"
        authority = dict(analyzer_electrode_voltages_v=list(range(20)),
                         component_voltages_v=[], assembly={})
        geometry = {"frozen_geometry": True}
        dimensions = [21, int(610 / pitch[1]) + 1, 2321]
        grid = dict(origin_mm=[-2.5,-147,-290], maximum_mm=[2.5,463,290],
                    pitch_mm=list(pitch), dimensions=dimensions,
                    point_count=21 * dimensions[1] * 2321, block_points=65536)
        dataset = dict(dataset_tag="dset1", solution_tag="sol1", dataset_type="Solution")
        export_plan = dict(grid, source_mph=str(model), dataset_tag="dset1", solution_tag="sol1")
        result = dict(field_solved=True, tetrahedra=20840828 if mesh=="mesh2" else 15903593,
                      vacuum_domain_count=31)
        if not legacy:
            result["active_mesh_tag"] = mesh
            export_plan["active_mesh_tag"] = mesh
        if mismatch == "mesh":
            export_plan["active_mesh_tag"] = "mesh1"
        elif mismatch == "model":
            export_plan["source_mph"] = str(field / "other.mph")
        elif mismatch == "grid":
            export_plan["pitch_mm"] = [.25,.125,.25]
        elif mismatch == "dataset":
            export_plan["dataset_tag"] = "dset2"
        plan_path = export / "inputs" / plan_name
        solver_path = field / "results/solver_configured.json"
        source_manifest = dict(outputs=[dict(path=str(solver_path))])
        export_manifest = dict(inputs={plan_name: dict(path=str(plan_path))})
        if mismatch == "ambiguous":
            export_manifest["inputs"]["other"] = dict(path=str(export / "inputs/plan.json"))
        properties = [] if mismatch == "missing_study" else [
            dict(name="mesh", value=["geom1",mesh], read_error="")]
        documents = {
            field / "summary.json": dict(status="success", result=result, model_path=str(model)),
            field / "run_manifest.json": source_manifest,
            field / "results/dataset_readback.json": dataset,
            field / "inputs/frozen_input.json": authority,
            field / "inputs/resolved_geometry.json": geometry,
            solver_path: dict(study_step=dict(properties=properties)),
            export / "run_manifest.json": export_manifest,
            plan_path: export_plan,
        }
        binding = dict(export_manifest=str(export / "run_manifest.json"), authority=authority,
                       geometry=geometry, grid=grid, assembly_manifest="assembly", collision_manifest="collision")
        request = dict(schema_version=1, role="mrtof_same_mesh_field_provider_request",
                       source_binding_path=str(root / "binding.json"),
                       source_field_manifest=str(field / "run_manifest.json"),
                       candidate_voltages_v=dict(s1=-27,s2=54,p1=191,p2=-190),
                       resource_threshold_action="warn", solve_memory_bytes=1,
                       solve_seconds=1, artifact_budget_bytes=1,
                       artifact_retention=dict(policy_version=1, **{"class":"solver_review"},
                                               reason="Pure mesh binding fixture"))
        request.update(launcher_options or {})
        with patch(module+".read", side_effect=lambda path: copy.deepcopy(documents[path])), \
             patch(module+".load_binding", return_value=binding), \
             patch(module+"._record", return_value={"bytes":1,"sha256":"fixture"}):
            return compile_request(request)

    def test_old_mesh1_uses_sealed_study_readback_and_named_plan(self):
        plan = self.compile_fixture(mesh="mesh1", plan_name="plan.json", legacy=True)
        self.assertEqual(plan["active_mesh_tag"], "mesh1")
        self.assertEqual(plan["expected_tetrahedra"],15903593)
        self.assertTrue(plan["source_study_mesh_readback"].endswith("solver_configured.json"))
        self.assertEqual(Path(plan["source_export_plan"]).name,"plan.json")

    def test_allocator_override_is_frozen_without_changing_common_default(self):
        self.assertNotIn("comsol_allocator", self.compile_fixture())
        for allocator in ("auto", "scalable", "native"):
            self.assertEqual(self.compile_fixture(launcher_options={"comsol_allocator": allocator})[
                "comsol_allocator"], allocator)
        with self.assertRaisesRegex(ValueError, "comsol_allocator"):
            self.compile_fixture(launcher_options={"comsol_allocator": "unknown"})
        repo = Path(__file__).resolve().parents[4]
        runner = (repo / "projects/parallel_mirror_dual_stripe_mr_tof/comsol/run_corridor_field_provider.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("$launcherOptions.Allocator=[string]$plan.comsol_allocator", runner)
        self.assertIn("@launcherOptions", runner)

    def test_two_mesh_source_uses_mesh2_and_diagnostic_plan(self):
        plan = self.compile_fixture()
        self.assertEqual(plan["active_mesh_tag"], "mesh2")
        self.assertEqual(plan["expected_tetrahedra"],20840828)
        self.assertIsNone(plan["source_study_mesh_readback"])
        self.assertEqual(Path(plan["source_export_plan"]).name,"diagnostic_plan.json")
        self.assertEqual(plan["export_grid"]["dimensions"],[21,2441,2321])

    def test_mismatched_export_or_missing_study_is_rejected(self):
        for mismatch in ("mesh","model","grid","dataset","ambiguous","missing_study"):
            with self.subTest(mismatch=mismatch), self.assertRaises(ValueError):
                self.compile_fixture(legacy=mismatch=="missing_study", mismatch=mismatch)

    def test_per_axis_spacing_and_dimensions_are_preserved(self):
        plan = self.compile_fixture(pitch=(.25,.125,.25))
        self.assertEqual(plan["export_grid"]["pitch_mm"], [.25,.125,.25])
        self.assertEqual(plan["export_grid"]["dimensions"], [21,4881,2321])
        self.assertEqual(plan["export_grid"]["point_count"], 237904821)

    def test_task_reads_actual_study_mesh_without_switch_or_rebuild(self):
        self.assertIn("'active_mesh_tag',string(step.mesh('geom1'))",TASK_SOURCE)
        self.assertIn("mesh(char(before.active_mesh_tag))",TASK_SOURCE)
        self.assertIn("before.active_mesh_tag==string(p.active_mesh_tag)",TASK_SOURCE)
        self.assertIn("assert(mesh.isLocked() && stats.isComplete()",TASK_SOURCE)
        self.assertIn("result.active_mesh_tag = char(after.active_mesh_tag)",TASK_SOURCE)
        self.assertIn("assert(isequaln(before,after)",TASK_SOURCE)
        self.assertNotIn("mesh('mesh1').stat()",TASK_SOURCE)
        self.assertNotIn("step.mesh('geom1',",TASK_SOURCE)
        self.assertNotIn("mesh.run",TASK_SOURCE)
        self.assertNotIn("geom.run",TASK_SOURCE)
        self.assertLess(TASK_SOURCE.index("before.active_mesh_tag=="),
                        TASK_SOURCE.index("update_corridor_workpoint_voltages"))

    def test_warning_memory_is_not_solver_admission_override(self):
        repo = Path(__file__).resolve().parents[4]
        runner = (repo / "projects/parallel_mirror_dual_stripe_mr_tof/comsol/run_corridor_field_provider.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("Get-HostResourceBudget -Role COMSOL -Stage solver",runner)
        self.assertNotIn("$budget.memory_bytes=",runner)
        self.assertIn("$peak -gt $plan.solve_memory_bytes",runner)


class SealedSourceCompileTest(unittest.TestCase):
    def setUp(self) -> None:
        # Reuse the public tiny-asset fixture; historical mirror metadata does
        # not make retired PA payloads a static test dependency.
        self.fixture = RefinementWindowProviderTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        root = Path(__file__).resolve().parents[5] / "artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs"
        self.reference = root / "20261006_014633__sim__simion__mrtof-comsol-static-center-entry__r02"
        source = root / "20261005_212938__analysis__comsol__mrtof-c0-p1-intermediate-field"
        self.external_authority_path = source / "inputs/frozen_input.json"

    def mirror_request(self) -> dict:
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.fixed_mirror_stripe_operating_point import _named_record
        manifest = self.reference / "run_manifest.json"
        variation = self.reference / "simion/terminal_time_mirror_voltage_variation.json"
        contract = self.reference / "simion/trajectory_contract.json"
        required = [manifest, variation, contract, self.external_authority_path]
        if any(not path.is_file() for path in required):
            self.skipTest("External sealed mirror metadata is not installed; tiny source compile/publication tests remain active")
        reference = json.loads(manifest.read_text(encoding="utf-8"))
        for name in ("fixed_mirror_stripe_downstream_authority.json", "mirror_exact_k_summary.json",
                     "dual_stripe_exact_k_summary.json", "trajectory_contract.json",
                     "two_prism_trial_materialization.json"):
            # Present-but-invalid manifests still fail; only missing payload
            # files are a clean-checkout skip, never retired PA assets.
            path = Path(_named_record(reference["inputs"], name, name)["path"])
            if not path.is_file():
                self.skipTest("External sealed mirror metadata file is not installed: " + name)
        actual = json.loads(self.external_authority_path.read_text(encoding="utf-8"))
        self.fixture.authority["analyzer_electrode_voltages_v"] = actual["analyzer_electrode_voltages_v"]
        field = self.fixture.model.parent.parent
        summary = json.loads((field / "summary.json").read_text())
        self.fixture.seal(field, {
            "inputs/frozen_input.json":self.fixture.authority,
            "inputs/resolved_geometry.json":self.fixture.geometry,
            "results/dataset_readback.json":self.fixture.dataset},
            {"comsol/source.mph":b"fake"}, summary=summary)
        binding = json.loads(self.fixture.binding.read_text())
        for owner in [binding["export_manifest"], *[w["export_manifest"] for w in self.fixture.windows]]:
            export = Path(owner).parent
            grid = json.loads((export / "inputs/plan.json").read_text())
            self.fixture.export(export, grid, self.fixture.authority)
        request = self.source_request()
        request.update(mirror_reference_trial_manifest=str(manifest),
                       mirror_voltage_variation_path=str(variation),
                       mirror_contract_path=str(contract))
        return request

    def test_frozen_original_mirror_reference_and_absolute_target(self) -> None:
        request = self.mirror_request()
        variation = json.loads(Path(request["mirror_voltage_variation_path"]).read_text(encoding="utf-8"))
        plan = compile_request(request)
        expected = variation["target_mirror_voltages_v"]*2
        self.assertEqual(plan["candidate_authority"]["analyzer_electrode_voltages_v"][:10],expected)
        self.assertEqual(len(plan["mirror_reference_paths"]),7)
        request["candidate_voltages_v"]["p1"] += 1
        repeated = compile_request(request)
        self.assertEqual(repeated["candidate_authority"]["analyzer_electrode_voltages_v"][:10],expected)
        scalar_source = load_binding(Path(request["source_binding_path"]))
        authority, paths = derive_candidate_authority(request, scalar_source["authority"])
        self.assertEqual(authority, repeated["candidate_authority"])
        self.assertEqual(paths, repeated["mirror_reference_paths"])

    def test_existing_variation_validator_rejects_wrong_base_delta_and_range(self) -> None:
        request = self.mirror_request()
        original = json.loads(Path(request["mirror_voltage_variation_path"]).read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="mrtof-mirror-variation-") as directory:
            path = Path(directory) / "variation.json"
            request["mirror_voltage_variation_path"] = str(path)
            cases = []
            bad = copy.deepcopy(original);bad["base_mirror_voltages_v"][1] += 1;cases.append(bad)
            bad = copy.deepcopy(original);bad["voltage_delta_v"][0] += 1;cases.append(bad)
            bad = copy.deepcopy(original);bad["target_mirror_voltages_v"][1] = 1e9
            bad["voltage_delta_v"][0] = bad["target_mirror_voltages_v"][1]-bad["base_mirror_voltages_v"][1];cases.append(bad)
            for variation in cases:
                path.write_text(json.dumps(variation),encoding="utf-8")
                with self.assertRaises(ValueError):
                    compile_request(request)

    def test_nonunit_scale_applies_once_only_to_absolute_mirror_target(self) -> None:
        # Existing P/S request values are physical V0; source MPH values are already scaled.
        import projects.parallel_mirror_dual_stripe_mr_tof.analysis.corridor_field_provider as provider
        request = self.mirror_request()
        real_read, real_load = provider.read, provider.load_contract
        binding = load_binding(Path(request["source_binding_path"]))
        binding["authority"]["analyzer_electrode_voltages_v"][:10] = [v*2 for v in binding["authority"]["analyzer_electrode_voltages_v"][:10]]
        def read_scaled(path):
            value = real_read(path)
            if path.name in ("frozen_input.json","two_prism_trial_materialization.json"):
                value["analyzer_electrode_voltages_v"][:10] = [v*2 for v in value["analyzer_electrode_voltages_v"][:10]]
            return value
        def contract_scaled(path,**kwargs):
            value = real_load(path,**kwargs)
            value["simion"]["nonaccelerator_scale"] = 2
            return value
        with patch.object(provider,"read",side_effect=read_scaled), \
             patch.object(provider,"load_binding",return_value=binding), \
             patch.object(provider,"load_contract",side_effect=contract_scaled):
            plan = compile_request(request)
        variation = real_read(Path(request["mirror_voltage_variation_path"]))
        self.assertEqual(plan["candidate_authority"]["analyzer_electrode_voltages_v"][:10],
                         [v*2 for v in variation["target_mirror_voltages_v"]]*2)
        self.assertEqual(plan["candidate_authority"]["analyzer_electrode_voltages_v"][15],request["candidate_voltages_v"]["p1"])

    def test_source_mirror_mismatch_rejected_before_field_solve(self) -> None:
        import projects.parallel_mirror_dual_stripe_mr_tof.analysis.corridor_field_provider as provider
        request = self.mirror_request()
        real_read = provider.read
        binding = load_binding(Path(request["source_binding_path"]))
        binding["authority"]["analyzer_electrode_voltages_v"][1] += 1
        def mismatch(path):
            value = real_read(path)
            if path.name == "frozen_input.json":
                value["analyzer_electrode_voltages_v"][1] += 1
            return value
        with patch.object(provider,"read",side_effect=mismatch),patch.object(provider,"load_binding",return_value=binding):
            with self.assertRaisesRegex(ValueError,"source MPH mirror voltages"):
                compile_request(request)

    def source_request(self) -> dict:
        request = copy.deepcopy(self.fixture.request)
        request["candidate_voltages_v"] = dict(s1=-27.07,s2=54.62,p1=191.12,p2=-190.52)
        return request
    def test_real_manifest_compile_without_model_load_or_hash(self) -> None:
        plan = compile_request(self.source_request())
        self.assertEqual(plan["expected_tetrahedra"],123)
        self.assertEqual(plan["expected_vacuum_domain_count"],1)
        self.assertEqual(plan["source_dataset"]["dataset_tag"],"dset1")
        self.assertTrue(plan["source_model_not_copied_or_rehashed"])
        self.assertEqual(plan["candidate_authority"]["assembly"],plan["source_authority"]["assembly"])

    def test_public_manifest_finalize_to_consumer_binding(self) -> None:
        # Lifecycle/consumer integration only: tiny byte fixtures, never a claimed solved field.
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.corridor_field_provider"
        with tempfile.TemporaryDirectory(prefix="mrtof-provider-test-") as temporary:
            base = Path(temporary)
            run = base / "artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261006_000000__test__python__provider-binding-fixture"
            run.parent.mkdir(parents=True)
            request = base / "request.json"
            request.write_text(json.dumps(self.source_request()),encoding="utf-8")
            with patch(module+".register_writing_range"), patch(module+".register_writing"):
                prepared = prepare(request,run)
            self.assertEqual(prepared["status"],"prepared_not_executed")
            inputs = run / "inputs"
            (inputs / "provider_usage.json").write_text(json.dumps({"outcome":"success","test_fixture":True}),encoding="utf-8")
            frozen_grid = json.loads((inputs / "plan.json").read_text(encoding="utf-8"))["export_grid"]
            (inputs / "result.json").write_text(json.dumps(dict(frozen_grid,status="success",field_units="V",test_fixture=True)),encoding="utf-8")
            (inputs / "field_v.pa").write_bytes(b"test-only-scalar-bytes")
            (inputs / "field_valid.pa").write_bytes(b"test-only-valid-bytes")
            plan = json.loads((inputs / "plan.json").read_text(encoding="utf-8"))
            for window in plan["refinement_windows"]:
                local = Path(window["output_directory"])
                self.fixture.write(local / "result.json", dict(window["export_grid"],
                    status="success", field_units="V", active_mesh_tag=plan["active_mesh_tag"]))
                for name in ("field_v.pa", "field_valid.pa"):
                    (local / name).write_bytes(b"fake")
            with patch(module+".record_capacity_object"):
                summary = finalize(run)
            binding = load_binding(inputs / "field_binding.json")
            self.assertEqual(summary["status"],"success")
            self.assertEqual(binding["authority"]["analyzer_electrode_voltages_v"][10],-27.07)
            self.assertEqual(binding["instances"][1]["origin_mm"],[0,0,0])
            self.assertEqual(Path(binding["sources"]["scalar_pa"]),inputs / "field_v.pa")
            for name in ("field_v.pa","field_valid.pa"):
                (inputs / name).chmod(0o666)
            for window in plan["refinement_windows"]:
                for name in ("field_v.pa", "field_valid.pa"):
                    (Path(window["output_directory"]) / name).chmod(0o666)


class RefinementWindowProviderTest(unittest.TestCase):
    """Real public manifest/consumer integration with tiny, explicitly fake PA/MPH bytes."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mrtof-window-provider-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runs = self.root / "artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs"
        self.runs.mkdir(parents=True)
        self.retention = dict(policy_version=1, **{"class":"solver_review"}, reason="Tiny contract fixture")
        self.authority = dict(analyzer_electrode_voltages_v=list(range(20)), component_voltages_v=[],
            assembly=dict(accelerator_iob_origin_mm=[0,0,0], detector=dict(box={}),
                accelerator_resolved_electrodes=dict(local_to_pa_translation_mm=[0,0,0],
                    grounded_enclosure=dict(outer_box_mm=dict(z_min_mm=-1)),
                    repeller=dict(solid_box_mm=dict(z_min_mm=0)), grid_supports=[], rings=[])))
        self.geometry = dict(detector=dict(box={}))
        assembly = self.runs / "20261007_000001__test__python__assembly-fixture"
        pa = assembly / "inputs/collision.pa0"
        gui = dict(pa_dependencies=[dict(role=role, path=str(pa), bytes=4,
                    source=dict(sha256="fixture")) for role in ("global_fallback","accelerator","detector")])
        self.seal(assembly, {"results/resolved_iob_pose.json":dict(origins_mm={
            role:[0,0,0] for role in ("analyzer","accelerator","detector")}),
            "results/gui_workbench_receipt.json":gui}, {"inputs/collision.pa0":b"fake"})
        collision = self.runs / "20261007_000002__test__python__collision-fixture"
        self.seal(collision, {"inputs/plan.json":dict(collision_mask=dict(origin_mm=[0,0,0])),
            "inputs/candidate_resolved_geometry.json":self.geometry}, {"inputs/new_p1_collision.pa0":b"fake"})
        field = self.runs / "20261007_000003__test__python__field-fixture"
        self.model = field / "comsol/source.mph"
        self.dataset = dict(dataset_tag="dset1", solution_tag="sol1", dataset_type="Solution")
        self.seal(field, {"inputs/frozen_input.json":self.authority,
            "inputs/resolved_geometry.json":self.geometry, "results/dataset_readback.json":self.dataset},
            {"comsol/source.mph":b"fake"}, summary=dict(status="success", model_path=str(self.model),
                result=dict(field_solved=True, active_mesh_tag="mesh3", tetrahedra=123, vacuum_domain_count=1)))
        base = self.runs / "20261007_000004__test__python__base-fixture"
        self.export(base, self.grid(5,.5), self.authority)
        self.windows = []
        for number, (name, count, pitch, box) in enumerate((
                ("second-name-first",7,.25,.25), ("first-name-second",9,.125,.125)), start=5):
            local = self.runs / f"20261007_00000{number}__test__python__local-fixture"
            self.export(local, self.grid(count,pitch), self.authority)
            self.windows.append(dict(name=name, export_manifest=str(local / "run_manifest.json"),
                                     active_box_mm=[[-box,box]]*3))
        self.binding = self.root / "binding.json"
        self.write(self.binding, dict(schema_version=1, role="mrtof_static_comsol_field_binding",
            export_manifest=str(base / "run_manifest.json"), assembly_manifest=str(assembly / "run_manifest.json"),
            collision_manifest=str(collision / "run_manifest.json"), refinement_windows=self.windows))
        self.request = dict(schema_version=1, role="mrtof_same_mesh_field_provider_request",
            source_binding_path=str(self.binding), source_field_manifest=str(field / "run_manifest.json"),
            candidate_voltages_v=dict(s1=-27,s2=54,p1=191,p2=-190), resource_threshold_action="warn",
            solve_memory_bytes=1, solve_seconds=1, artifact_budget_bytes=1000000,
            artifact_retention=self.retention)
        self.addCleanup(self.unlock)

    def unlock(self):
        for path in self.root.rglob("*.pa"):
            path.chmod(0o666)

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def grid(self, count, pitch):
        edge = (count-1)*pitch/2
        return dict(origin_mm=[-edge]*3, maximum_mm=[edge]*3, pitch_mm=[pitch]*3,
                    dimensions=[count]*3, point_count=count**3, block_points=8,
                    dataset_tag="dset1", solution_tag="sol1")

    def seal(self, run, documents, binaries=None, summary=None):
        for name, value in documents.items():
            self.write(run / name, value)
        for name, value in (binaries or {}).items():
            path = run / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
        inputs = {p.name:str(p) for p in (run / "inputs").iterdir() if p.is_file()} if (run / "inputs").exists() else {}
        self.write(run / "run_config.json", dict(schema_version=2, run_id=run.name,
            project="parallel_mirror_dual_stripe_mr_tof", mode="tiny_contract_fixture",
            artifact_retention=self.retention, inputs=inputs))
        summary = summary or dict(status="success", test_fixture=True)
        manifest = build_run_manifest(run / "run_config.json", "success",
            output_paths=[run / "summary.json", *[p for p in run.rglob("*") if p.is_file()]],
            virtual_documents={run / "summary.json":summary})
        publish_terminal_state(run, summary, manifest)

    def export(self, run, grid, authority):
        self.seal(run, {"inputs/plan.json":dict(grid, source_mph=str(self.model), active_mesh_tag="mesh3"),
            "inputs/frozen_input.json":authority, "inputs/resolved_geometry.json":self.geometry,
            "inputs/result.json":dict(grid, status="success", field_units="V", active_mesh_tag="mesh3")},
            {"inputs/field_v.pa":b"fake", "inputs/field_valid.pa":b"fake", "inputs/simion_pa_save.m":b"% fixture"})

    def candidate(self, number=10):
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.corridor_field_provider"
        request_path = self.root / f"request{number}.json"
        self.write(request_path, self.request)
        run = self.runs / f"20261007_0000{number}__test__python__provider-fixture"
        with patch(module+".register_writing_range"), patch(module+".register_writing"):
            prepare(request_path, run)
        plan = json.loads((run / "inputs/plan.json").read_text())
        self.write(run / "inputs/provider_usage.json", dict(outcome="success", test_fixture=True))
        for local, grid in [(run / "inputs", plan["export_grid"]), *[
                (Path(w["output_directory"]), w["export_grid"]) for w in plan["refinement_windows"]]]:
            self.write(local / "result.json", dict(grid, status="success", field_units="V", active_mesh_tag="mesh3"))
            for name in ("field_v.pa", "field_valid.pa"):
                (local / name).write_bytes(b"fake")
        return run, plan

    def publish(self, run):
        module = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.corridor_field_provider"
        with patch(module+".record_capacity_object"):
            return finalize(run)

    def verify(self, manifest, status="success"):
        repo = Path(__file__).resolve().parents[4]
        result = subprocess.run([sys.executable, str(repo / "common/contracts/verify_run_manifest.py"),
            str(manifest), "--require-status", status, "--require-local-run-config"],
            cwd=repo, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_ordered_grids_and_two_absolute_candidates_publish_consumable_windows(self):
        for number in (10,11):
            self.request["candidate_voltages_v"]["p1"] += 1
            compiled = compile_request(self.request)
            self.assertEqual([w["name"] for w in compiled["refinement_windows"]],
                             [w["name"] for w in self.windows])
            self.assertEqual([w["export_grid"]["pitch_mm"] for w in compiled["refinement_windows"]],
                             [[.25]*3,[.125]*3])
            run, plan = self.candidate(number)
            self.assertEqual(self.publish(run)["status"], "success")
            binding = load_binding(run / "inputs/field_binding.json")
            self.assertEqual([w["name"] for w in binding["refinement_windows"]],
                             [w["name"] for w in self.windows])
            self.verify(run / "run_manifest.json")
            for window in plan["refinement_windows"]:
                receipt = run / window["receipt_directory"]
                self.verify(receipt / "run_manifest.json")
                local_plan = json.loads((receipt / "inputs/plan.json").read_text())
                for key in ("source_mph","active_mesh_tag"):
                    self.assertEqual(local_plan[key], plan[key])
                for key, value in window["export_grid"].items():
                    self.assertEqual(local_plan[key], value)
                authority = json.loads((receipt / "inputs/frozen_input.json").read_text())
                self.assertEqual(authority, binding["authority"])
                self.assertEqual(authority["analyzer_electrode_voltages_v"][15],
                                 self.request["candidate_voltages_v"]["p1"])
            self.unlock()

    def test_local_failure_does_not_publish_binding(self):
        run, plan = self.candidate()
        local = Path(plan["refinement_windows"][1]["output_directory"])
        self.write(local / "result.json", dict(status="failed"))
        self.assertEqual(self.publish(run)["status"], "failed")
        self.assertFalse((run / "inputs/field_binding.json").exists())
        self.verify(run / "run_manifest.json", "failed")
        for window in plan["refinement_windows"]:
            self.verify(run / window["receipt_directory"] / "run_manifest.json", "failed")

    def test_old_voltage_local_is_rejected_before_success_binding(self):
        run, plan = self.candidate()
        self.write(Path(plan["refinement_windows"][0]["output_directory"]) / "frozen_input.json", self.authority)
        self.assertEqual(self.publish(run)["status"], "failed")
        self.assertFalse((run / "inputs/field_binding.json").exists())

    def test_old_voltage_sealed_source_window_and_wrong_mesh_are_rejected(self):
        local = Path(self.windows[0]["export_manifest"]).parent
        authority = copy.deepcopy(self.authority)
        authority["analyzer_electrode_voltages_v"][10] += 1
        self.write(local / "inputs/frozen_input.json", authority)
        with self.assertRaisesRegex(ValueError, "voltage authority or geometry differs"):
            compile_request(self.request)
        self.write(local / "inputs/frozen_input.json", self.authority)
        plan = json.loads((local / "inputs/plan.json").read_text())
        plan["active_mesh_tag"] = "mesh2"
        self.write(local / "inputs/plan.json", plan)
        with self.assertRaisesRegex(ValueError, "solved active mesh differ"):
            compile_request(self.request)

    def test_one_solve_exports_all_windows_without_pa_hash_in_compile(self):
        with patch("common.contracts.file_identity.file_sha256", side_effect=AssertionError("No source hash")):
            self.assertEqual(len(compile_request(self.request)["refinement_windows"]), 2)
        self.assertEqual(TASK_SOURCE.count(".runAll;"), 1)
        self.assertIn("for k = 1:numel(p.refinement_windows)", TASK_SOURCE)
        self.assertIn("window.export_grid,string(window.output_directory)", TASK_SOURCE)

    def test_local_pa_is_hashed_once_and_parent_retention_scans_nested_payload(self):
        from common.contracts.file_identity import file_sha256
        run, plan = self.candidate()
        with patch("common.contracts.write_run_manifest.file_sha256", wraps=file_sha256) as hashing:
            self.assertEqual(self.publish(run)["status"], "success")
        paths = [Path(call.args[0]) for call in hashing.call_args_list]
        for window in plan["refinement_windows"]:
            for name in ("field_v.pa", "field_valid.pa"):
                self.assertEqual(paths.count(Path(window["output_directory"]) / name), 1)
        config = json.loads((run / "run_config.json").read_text())
        config["artifact_retention"] = dict(policy_version=1, **{"class":"compact"})
        self.write(run / "run_config.json", config)
        with self.assertRaises(ValueError):
            build_run_manifest(run / "run_config.json", "success", output_paths=[])

    def test_local_missing_pa_and_wrong_dataset_are_failed_not_bindings(self):
        for number, fault in ((10,"missing"),(11,"dataset")):
            run, plan = self.candidate(number)
            local = Path(plan["refinement_windows"][0]["output_directory"])
            if fault == "missing":
                (local / "field_valid.pa").unlink()
            else:
                result = json.loads((local / "result.json").read_text())
                result["dataset_tag"] = "dset2"
                self.write(local / "result.json", result)
            self.assertEqual(self.publish(run)["status"], "failed")
            self.assertFalse((run / "inputs/field_binding.json").exists())

    def test_warning_artifact_observation_includes_nested_window_payload(self):
        repo = Path(__file__).resolve().parents[4]
        runner = (repo / "projects/parallel_mirror_dual_stripe_mr_tof/comsol/run_corridor_field_provider.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("Get-ChildItem -LiteralPath $RunDirectory -File -Recurse", runner)

    def test_explicit_completed_provider_match_and_voltage_nonmatch_without_hash(self):
        run, _ = self.candidate()
        self.assertEqual(self.publish(run)["status"], "success")
        manifest = run / "run_manifest.json"
        with patch("common.contracts.file_identity.file_sha256", side_effect=AssertionError("No PA/MPH hash")):
            self.assertEqual(resolve_completed_provider(self.request, manifest),
                             str((run / "inputs/field_binding.json").resolve()))
            changed = copy.deepcopy(self.request)
            changed["candidate_voltages_v"]["s1"] += .1
            self.assertIsNone(resolve_completed_provider(changed, manifest))

    def test_explicit_completed_provider_rejects_failed_or_other_mode(self):
        run, _ = self.candidate()
        self.publish(run)
        manifest = run / "run_manifest.json"
        sealed = json.loads(manifest.read_text())
        for key, value in (("status","failed"),("mode","tiny_contract_fixture")):
            self.write(manifest, dict(sealed, **{key:value}))
            with self.assertRaisesRegex(ValueError, "successful same_mesh"):
                resolve_completed_provider(self.request, manifest)

    def test_explicit_completed_provider_rejects_source_grid_and_ordered_window_changes(self):
        for number, change in enumerate(("source_mph", "active_mesh_tag", "dataset", "grid",
                                         "order", "box", "window_grid", "geometry", "missing_binding"), start=10):
            run, _ = self.candidate(number)
            self.publish(run)
            path = run / "inputs/plan.json"
            plan = json.loads(path.read_text())
            if change == "source_mph":
                plan["source_mph"] = str(self.root / "other.mph")
            elif change == "active_mesh_tag":
                plan["active_mesh_tag"] = "mesh2"
            elif change == "dataset":
                plan["source_dataset"]["dataset_tag"] = "dset2"
            elif change == "grid":
                plan["export_grid"]["pitch_mm"][0] *= 2
            elif change == "order":
                plan["refinement_windows"].reverse()
            elif change == "window_grid":
                plan["refinement_windows"][0]["export_grid"]["pitch_mm"][0] *= 2
            elif change == "geometry":
                self.write(run / "inputs/resolved_geometry.json", dict(changed_geometry=True))
            elif change == "missing_binding":
                summary = json.loads((run / "summary.json").read_text())
                summary["field_binding"] = None
                self.write(run / "summary.json", summary)
            else:
                plan["refinement_windows"][0]["active_box_mm"][0][0] += .01
            self.write(path, plan)
            # Public writer seals this malformed small plan, so identity checks
            # (not accidental size drift) must reject the supplied provider.
            config = run / "run_config.json"
            summary = json.loads((run / "summary.json").read_text())
            manifest = build_run_manifest(config, "success",
                output_paths=[p for p in run.rglob("*") if p.is_file() and p.name != "run_manifest.json"],
                virtual_documents={run / "summary.json":summary})
            self.write(run / "run_manifest.json", manifest)
            with self.subTest(change=change), self.assertRaises(ValueError):
                resolve_completed_provider(self.request, run / "run_manifest.json")
            self.unlock()

    def test_completed_resolution_cli_and_legacy_no_window_provider(self):
        binding = json.loads(self.binding.read_text())
        binding.pop("refinement_windows")
        self.write(self.binding, binding)
        run, _ = self.candidate()
        self.publish(run)
        repo = Path(__file__).resolve().parents[4]
        request_path = self.root / "request10.json"
        command = [sys.executable, "-m", "projects.parallel_mirror_dual_stripe_mr_tof.analysis.corridor_field_provider",
                   "--resolve-completed-request", str(request_path),
                   "--completed-provider-manifest", str(run / "run_manifest.json")]
        result = subprocess.run(command, cwd=repo, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout),
                         {"binding":str((run / "inputs/field_binding.json").resolve())})
        self.request["candidate_voltages_v"]["s1"] += .1
        self.write(request_path, self.request)
        result = subprocess.run(command, cwd=repo, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"binding":None})
        sealed = json.loads((run / "run_manifest.json").read_text())
        self.write(run / "run_manifest.json", dict(sealed, status="failed"))
        result = subprocess.run(command, cwd=repo, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
