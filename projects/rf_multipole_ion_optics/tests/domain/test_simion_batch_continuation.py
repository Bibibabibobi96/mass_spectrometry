"""Exercise RF predecessor identity and whole-batch replay without SIMION."""

import json
import hashlib
import shutil
import tempfile
import unittest
import os
import subprocess
import sys
from pathlib import Path

from common.contracts.machine_contracts import ContractError
from common.contracts.write_run_manifest import build_run_manifest
from common.contracts.capacity_ledger import initialize_capacity_ledger, load_capacity_ledger
from common.contracts.run_capacity_lifecycle import register_writing
from projects.rf_multipole_ion_optics.runtime.simion_batch_continuation import prepare


class RfContinuationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_prepared_cli_analysis_failure_retains_complete_units_for_new_run(self):
        repo = Path(__file__).resolve().parents[4]
        for workflow, mode in (("interface_readiness", "transport_interface_readiness"),
                               ("mass_filter_reference", "mass_filter_reference")):
            with self.subTest(workflow=workflow), tempfile.TemporaryDirectory() as directory:
                artifact_root = Path(directory) / "artifacts"
                project_root = artifact_root / "projects/rf_multipole_ion_optics"
                root = project_root / "runs"
                artifact_root.mkdir()
                initialize_capacity_ledger(artifact_root, objects=[])
                parent, child = (root / f"20261029_12000{i}__sim__simion__fixture" for i in (0, 1))
                names = ["resolved_design", "particle_table"]
                for run in (parent, child):
                    for name in ("inputs", "results", "logs", "simion"):
                        (run / name).mkdir(parents=True)
                    inputs = {}
                    for name in names:
                        path = run / "inputs" / f"{name}.json"
                        path.write_text(name, encoding="utf-8")
                        inputs[name] = str(path)
                    physics = run / "inputs/simion_fly_physics.json"
                    physics.write_text(json.dumps({"role": "multipole_simion_fly_physics", "cases": {workflow: {"rf": 7}}}), encoding="utf-8")
                    inputs["simion_fly_physics"] = str(physics)
                    partition = run / "inputs/simion_execution_batch_plan.json"
                    partition.write_text(json.dumps({"particle_count": 1, "batch_count": 1,
                        "batches": [{"index": 1, "particle_id_min": 1, "particle_id_max": 1, "simion_particle_id_offset": 0}]}), encoding="utf-8")
                    inputs["simion_execution_batch_plan"] = str(partition)
                    (run / "run_config.json").write_text(json.dumps({"schema_version": 2, "run_id": run.name,
                        "project": "rf_multipole_ion_optics", "mode": mode, "inputs": inputs,
                        "formal_gate_passed": False,
                        "artifact_retention": {"policy_version": 1, "class": "solver_review", "reason": "fixture producer-owned field"},
                        "capacity_ledger_lifecycle": {"schema_version": 1, "enabled": True,
                            "artifact_root": str(artifact_root), "light_evidence_budget_bytes": 1048576}}), encoding="utf-8")
                register_writing(artifact_root, parent / "run_config.json")
                field = parent / "simion/quad_monolithic.pa0"
                field.write_bytes(b"fixture-native-field-payload")
                outputs = [Path("results/particle_state.csv"), Path("results/solver_summary.json"), Path("logs/simion_stdout.txt")]
                (parent / outputs[0]).write_text("particle_id,event\n1,terminal\n", encoding="utf-8")
                (parent / outputs[1]).write_text('{"solver":"SIMION","particles":1}', encoding="utf-8")
                (parent / outputs[2]).write_text("status,Fly completed. 1 splats, 0.1 seconds\n", encoding="utf-8")
                receipt = parent / f"results/simion_batch_completion__{workflow}__batch_01.json"
                receipt.write_text(json.dumps({"role": "multipole_simion_completed_batch", "case": workflow,
                    "batch_index": 1, "particle_id_min": 1, "particle_id_max": 1, "particle_count": 1,
                    "outputs": [str(path) for path in outputs]}), encoding="utf-8")
                (parent / "summary.json").write_text(json.dumps({"schema_version": 1,
                    "run_id": parent.name, "status": "checkpoint"}), encoding="utf-8")
                (parent / "run_manifest.json").write_text(json.dumps(build_run_manifest(
                    parent / "run_config.json", "checkpoint")), encoding="utf-8")
                script = r"""
$ErrorActionPreference='Stop'
. (Join-Path $PWD 'common/contracts/run_artifact_support.ps1')
. (Join-Path $PWD 'projects/rf_multipole_ion_optics/runtime/simion_execution.ps1')
. (Join-Path $PWD 'common/contracts/run_artifact_workflow.ps1')
function Remove-RunPackageExecutionAlias {}
function Invoke-ArtifactCapacityGate {return @{satisfied=$true;fixture_admission=$true}}
function Invoke-ResourceBudgetedProcess {throw 'NATIVE_MUST_NOT_START'}
function Initialize-RfSimionPaBasis {throw 'REFINE_MUST_NOT_START'}
function Invoke-RfSimionAdaptiveBatchWave {throw 'FLY_MUST_NOT_START'}
$ast=[Management.Automation.Language.Parser]::ParseFile($env:RF_TEST_RUNNER,[ref]$null,[ref]$null)
$owner=@($ast.EndBlock.Statements|Where-Object{$_-is[Management.Automation.Language.TryStatementAst]-and$_.CatchClauses.Count})[-1]
$tail=$owner.CatchClauses[0].Extent.Text+'finally'+$owner.Finally.Extent.Text
$repoRoot=$PWD;$python=$env:RF_TEST_PYTHON;$runConfigPath=Join-Path $env:RF_TEST_PARENT 'run_config.json';$artifactRoot=$env:RF_TEST_PROJECT_ROOT
$runSummary=Join-Path $env:RF_TEST_PARENT 'summary.json';$RunId=Split-Path -Leaf $env:RF_TEST_PARENT
$package=@{artifact_run_dir=$env:RF_TEST_PARENT;run_dir=$env:RF_TEST_PARENT;run_config=$runConfigPath}
$continuation=$null;$fieldContext=$null;$hostExecutionLease=$null;$hostExecutionOutcome='failed';$writerCompletionUnknown=$false
$hostReleaseState=@{released=$false;completion=$null};$nativePreparation=[Collections.Generic.List[object]]::new();$deferFinalization=$false
$resultDir=Join-Path $env:RF_TEST_PARENT 'results';$logDir=Join-Path $env:RF_TEST_PARENT 'logs';$candidateDir=Join-Path $env:RF_TEST_PARENT 'simion'
$ownerCapacity=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
 -ArtifactRoot (Split-Path (Split-Path $artifactRoot -Parent) -Parent) -RunDirectory $env:RF_TEST_PARENT `
 -CommittedNewBytes 0 -Owner ("run-artifact-workflow:rf_multipole_ion_optics:{0}"-f$RunId)
$entry=Copy-VerifiedRunInput -Source $env:RF_TEST_RUNNER -Destination (Join-Path $env:RF_TEST_PARENT 'inputs/owner.ps1')
$budget=Join-Path $env:RF_TEST_PARENT 'inputs/numerics.json';'{"fixture":true}'|Set-Content $budget
$ownerContext=Initialize-RunArtifactPowerShellOwner -Python $python -RepoRoot $repoRoot -Package $package `
 -CapacitySession $ownerCapacity -EntrypointPath $entry -CommitmentInputPaths @($budget)
$ResultPath=$ownerContext.result_path
$execution=@{clock=[Diagnostics.Stopwatch]::StartNew();phase='analysis';phase_started=0.0;phase_seconds=[ordered]@{};elapsed_seconds=0.0}
$executionStatus='failed';$dataValidity='valid_raw_outputs';$scienceStatus='not_evaluated'
try{. ([scriptblock]::Create("try{throw 'injected-analysis-failure'}"+$tail))}
catch{
 if($_.Exception.Message-cne'injected-analysis-failure'){throw}
 if($_.Exception.Data['failure_closure_error']){throw ("Public failure closure failed: "+$_.Exception.Data['failure_closure_error'])}
}
exit 0
"""
                runner = repo / f"projects/rf_multipole_ion_optics/workflows/{workflow}/run_simion.ps1"
                result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script], cwd=repo,
                    env={**os.environ, "RF_TEST_RUNNER": str(runner), "RF_TEST_PARENT": str(parent), "RF_TEST_PYTHON": sys.executable,
                         "RF_TEST_PROJECT_ROOT": str(project_root)},
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=35)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                manifest_path = parent / "run_manifest.json"
                self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8-sig"))["status"], "failed")
                summary = json.loads((parent / "summary.json").read_text(encoding="utf-8-sig"))
                self.assertEqual((summary["failure_stage"], summary["data_validity"], summary["scientific_result"]),
                                 ("analysis", "valid_raw_outputs", "not_evaluated"))
                self.assertIn("ContinuationPredecessorManifestPath", summary["recovery_action"])
                self.assertGreaterEqual(summary["elapsed_before_finalization_seconds"], 0)
                self.assertTrue((parent / "retention_actions.json").is_file())
                self.assertTrue(all((parent / path).is_file() for path in outputs))
                self.assertTrue(field.is_file(), "completed field was deleted by failure retention")
                entry = next(row for row in load_capacity_ledger(artifact_root)["objects"]
                             if row["path"] == parent.relative_to(artifact_root).as_posix())
                self.assertEqual((entry["class"], entry["status"]), ("rebuildable_payload", "ready"))
                original = manifest_path.read_bytes()
                replay = prepare(child, parent, [workflow], "compact", False, names, "prepared")
                self.assertEqual(replay["replay"]["replay_unit_count"], 0)
                self.assertEqual(manifest_path.read_bytes(), original)

    def test_prepared_workflows_reuse_complete_units_and_ignore_analysis_changes(self):
        for mode, case in (("transport_interface_readiness", "interface_readiness"),
                           ("mass_filter_reference", "mass_filter_reference")):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                parent, child = (root / f"20261029_12000{i}__sim__simion__fixture" for i in (0, 1))
                names = ["resolved_design", "particle_table", "simion_program_source", "numerical_contract", "simion_layout_template_iob", "simion_layout_template_con"]
                for run in (parent, child):
                    (run / "inputs").mkdir(parents=True)
                    (run / "results").mkdir()
                    (run / "logs").mkdir()
                    inputs = {}
                    for name in names:
                        path = run / "inputs" / f"{name}.json"
                        path.write_text(name, encoding="utf-8")
                        inputs[name] = str(path)
                    physics = run / "inputs/simion_fly_physics.json"
                    physics.write_text(json.dumps({"role": "multipole_simion_fly_physics", "cases": {case: {"rf": 7}},
                                                   "source_modules": {"slicer.py": "unchanged"}}), encoding="utf-8")
                    inputs["simion_fly_physics"] = str(physics)
                    partition = run / "inputs/simion_execution_batch_plan.json"
                    partition.write_text(json.dumps({"particle_count": 2, "batch_count": 2,
                        "batches": [{"index": i, "particle_id_min": i, "particle_id_max": i,
                                     "simion_particle_id_offset": i - 1} for i in (1, 2)]}), encoding="utf-8")
                    inputs["simion_execution_batch_plan"] = str(partition)
                    analyzer = run / "inputs/analyzer.py"
                    analyzer.write_text(run.name, encoding="utf-8")
                    inputs["analyzer"] = str(analyzer)
                    (run / "run_config.json").write_text(json.dumps({"schema_version": 1, "run_id": run.name,
                        "project": "rf_multipole_ion_optics", "mode": mode, "inputs": inputs}), encoding="utf-8")
                outputs = []
                def complete(index):
                    log = Path(f"logs/batch_{index:02d}/simion_stdout.txt")
                    state = Path(f"results/particle_state__batch_{index:02d}.csv")
                    summary = Path(f"results/solver_summary__batch_{index:02d}.json")
                    for path in (log, state, summary):
                        (parent / path).parent.mkdir(parents=True, exist_ok=True)
                        (parent / path).write_text(path.name, encoding="utf-8")
                    receipt = Path(f"results/simion_batch_completion__{case}__batch_{index:02d}.json")
                    (parent / receipt).write_text(json.dumps({"role": "multipole_simion_completed_batch", "case": case,
                        "batch_index": index, "particle_id_min": index, "particle_id_max": index, "particle_count": 1,
                        "outputs": [str(path) for path in (log, state, summary)]}), encoding="utf-8")
                    outputs.extend(parent / path for path in (log, state, summary, receipt))
                def publish():
                    value = build_run_manifest(parent / "run_config.json", "failed", output_paths=outputs)
                    (parent / "run_manifest.json").write_text(json.dumps(value), encoding="utf-8")
                complete(2)
                publish()
                partial = prepare(child, parent, [case], "compact", False, names, "prepared")
                self.assertEqual([unit["action"] for unit in partial["replay"]["units"]], ["replay", "reuse"])
                complete(1)
                publish()
                original = (parent / "run_manifest.json").read_bytes()
                full = prepare(child, parent, [case], "compact", False, names, "prepared")
                self.assertEqual(full["replay"]["replay_unit_count"], 0)
                (child / "inputs/analyzer.py").write_text("changed postprocessing", encoding="utf-8")
                self.assertEqual(prepare(child, parent, [case], "compact", False, names, "prepared")["replay"]["reusable_unit_count"], 2)
                if os.name == "nt" and shutil.which("pwsh"):
                    repo = Path(__file__).resolve().parents[4]
                    script = r"""
$ErrorActionPreference='Stop'
. (Join-Path $PWD 'common/contracts/run_artifact_support.ps1')
. (Join-Path $PWD 'projects/rf_multipole_ion_optics/runtime/simion_execution.ps1')
function Enter-ArtifactWorkflowCapacitySession {param($ProtectedPaths) if(@($ProtectedPaths).Count-ne1){throw 'Missing source protection'};@{lease_id='fixture'}}
function Exit-ArtifactWorkflowCapacitySession {}
$child=$env:RF_TEST_CHILD;$parent=$env:RF_TEST_PARENT
$config=Get-Content (Join-Path $child 'run_config.json') -Raw|ConvertFrom-Json -AsHashtable
$context=Initialize-RfSimionPreparedContinuation -ManifestPath (Join-Path $parent 'run_manifest.json') `
 -RunDir $child -ArtifactRoot (Split-Path -Parent $child) -PythonExe $env:RF_TEST_PYTHON -RepositoryRoot $PWD `
 -RunConfig $config -RunConfigPath (Join-Path $child 'run_config.json') -CaseName $env:RF_TEST_CASE `
 -InputNames @('resolved_design','particle_table','simion_program_source','numerical_contract','simion_layout_template_iob','simion_layout_template_con') `
 -BatchPlanPath (Join-Path $child 'inputs/simion_execution_batch_plan.json') -DispatchPlanPath 'unused'
try{
 if(-not$context.all_reused-or$context.units.Count-ne2){throw 'Real initialization lost completed units'}
 $blocked=$false
 try{$handle=[IO.File]::Open((Join-Path $parent 'run_manifest.json'),[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::ReadWrite);$handle.Dispose()}
 catch{$blocked=$true}
 if(-not$blocked){throw 'Source manifest is not protected during consumption'}
}finally{foreach($guard in $context.guards){$guard.Dispose()};Exit-ArtifactWorkflowCapacitySession}
'INITIALIZATION=PASS'
"""
                    result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script], cwd=repo,
                        env={**os.environ, "RF_TEST_CHILD": str(child), "RF_TEST_PARENT": str(parent),
                             "RF_TEST_PYTHON": sys.executable, "RF_TEST_CASE": case},
                        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("INITIALIZATION=PASS", result.stdout)
                for changed in ("simion_layout_template_iob", "simion_layout_template_con"):
                    path = child / "inputs" / f"{changed}.json"
                    path.write_text("changed native layout", encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, changed):
                        prepare(child, parent, [case], "compact", False, names, "prepared")
                    path.write_text(changed, encoding="utf-8")
                (parent / ".run_terminal_publication.json").write_text("{}", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "publication"):
                    prepare(child, parent, [case], "compact", False, names, "prepared")
                (parent / ".run_terminal_publication.json").unlink()
                (child / "inputs/particle_table.json").write_text("new source", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "particle_table"):
                    prepare(child, parent, [case], "compact", False, names, "prepared")
                self.assertEqual((parent / "run_manifest.json").read_bytes(), original)

    def test_partial_and_full_reuse_require_bound_scientific_inputs(self):
        names = ("multipole_resolved_design", "particle_source", "solver_numerics", "simion_grid_audit",
                 "simion_fly_physics", "simion_gem", "simion_fly2", "simion_source_states", "simion_rf_drive_kernel",
                 "clock_authority", "instrument_epoch", "simion_layout_template_iob", "simion_layout_template_con")
        physical_keys = ("trajectory_quality", "rf_steps_per_period", "waveform", "rf_peak_v", "dc_amplitude_v",
            "frequency_hz", "phase_rad", "rod_lua", "static_lua", "maximum_time_us", "trajectory_plane_step_mm",
            "rod_z_min_mm", "rod_z_max_mm", "handoff_plane_mm", "census_plane_mm", "census_radius_mm",
            "radial_escape_radius_mm", "origin_x_mm", "origin_y_mm", "origin_z_mm", "backward_escape_plane_mm",
            "mechanical_exit_enabled", "mechanical_exit_plane_mm", "mechanical_exit_guard_mm",
            "mechanical_exit_aperture_radius_lua", "axial_axis", "gem2pa_args", "refine_args", "iob_args", "fly_args", "cases")
        physics_document = {"schema_version": 1, "role": "multipole_simion_fly_physics",
                            **{key: f"fixture-{key}" for key in physical_keys}}
        physics_document["cases"] = {"rf_on": {"rf": 1, "axial": 0}, "zero_rf_control": {"rf": 0, "axial": 0},
                                     "unused_case": {"rf": 1, "axial": 1}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / "20261029_120000__sim__simion__parent"
            child = root / "20261029_120001__sim__simion__child"
            for run in (parent, child):
                (run / "inputs").mkdir(parents=True)
                inputs = {}
                for name in names:
                    path = run / "inputs" / (name + ".json")
                    path.write_text(json.dumps(physics_document) if name == "simion_fly_physics" else name, encoding="utf-8")
                    inputs[name] = str(path)
                inventory = run / "inputs/code_inventory.json"
                source_code = ["projects/rf_multipole_ion_optics/runtime/simion_particle_source.py",
                    "projects/rf_multipole_ion_optics/runtime/particle_source_preflight.py",
                    "projects/rf_multipole_ion_optics/core/interface_geometry.py",
                    "common/simion/particle_source.py", "common/contracts/particle_physics.py"]
                inventory.write_text(json.dumps({"files": [
                    {"path": "projects/rf_multipole_ion_optics/simion/simion_transport.lua", "sha256": "ABC"},
                    {"path": "projects/rf_multipole_ion_optics/analysis/fixture.py", "sha256": run.name},
                ] + [{"path": name, "sha256": "same"} for name in source_code]}), encoding="utf-8")
                inputs["code_inventory"] = str(inventory)
                basis = run / "inputs/simion_pa_basis_identity.json"
                basis.write_text(json.dumps({"geometry": {"fixture": 1}, "builder_identity": {"runner_sha256": run.name}}), encoding="utf-8")
                inputs["simion_pa_basis_identity"] = str(basis)
                plan = run / "inputs/simion_execution_batch_plan.json"
                plan.write_text(json.dumps({"dispatch": "single_wave_parallel", "particle_count": 2, "batch_count": 2,
                    "batches": [{"index": i, "particle_id_min": i, "particle_id_max": i, "simion_particle_id_offset": i - 1} for i in (1, 2)]}), encoding="utf-8")
                inputs["simion_execution_batch_plan"] = str(plan)
                (run / "run_config.json").write_text(json.dumps({"schema_version": 1, "run_id": run.name,
                    "project": "rf_multipole_ion_optics", "mode": "resolved_design_transport", "inputs": inputs,
                    "parameters": {"case_set": "primary_only"}}), encoding="utf-8")
            (parent / "results").mkdir()
            (parent / "logs").mkdir()
            def complete(index: int, owner: Path = parent) -> list[Path]:
                state = Path(f"results/particle_states__rf_on__batch_{index:02d}.csv")
                summary = Path(f"results/simion_summary__rf_on__batch_{index:02d}.json")
                log = Path(f"logs/simion_stdout__fly__rf_on__batch_{index}.txt")
                for path in (state, summary, log):
                    (owner / path).write_text(path.name, encoding="utf-8")
                receipt = Path(f"results/simion_batch_completion__rf_on__batch_{index:02d}.json")
                (owner / receipt).write_text(json.dumps({"role": "multipole_simion_completed_batch", "case": "rf_on",
                    "batch_index": index, "particle_id_min": index, "particle_id_max": index,
                    "particle_count": 1, "outputs": [str(log), str(state), str(summary)]}), encoding="utf-8")
                return [owner / path for path in (receipt, log, state, summary)]
            outputs = complete(1)
            def publish() -> None:
                manifest = build_run_manifest(parent / "run_config.json", "failed", output_paths=outputs)
                (parent / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            publish()
            partial = prepare(child, parent, ["rf_on"], "compact", False)
            self.assertEqual((partial["replay"]["reusable_unit_count"], partial["replay"]["replay_unit_count"]), (1, 1))
            two_cases = prepare(child, parent, ["rf_on", "zero_rf_control"], "compact", False)
            self.assertEqual((two_cases["replay"]["reusable_unit_count"], two_cases["replay"]["replay_unit_count"]), (1, 3))
            partial = prepare(child, parent, ["rf_on"], "compact", False)
            (child / "results").mkdir()
            (child / "logs").mkdir()
            child_config = json.loads((child / "run_config.json").read_text(encoding="utf-8"))
            child_config["inputs"]["continuation_plan"] = str(child / "inputs/simion_whole_unit_replay_plan.json")
            child_config["inputs"]["continuation_predecessor_manifest"] = str(parent / "run_manifest.json")
            (child / "run_config.json").write_text(json.dumps(child_config), encoding="utf-8")
            child_outputs = complete(2, child)
            child_manifest = build_run_manifest(child / "run_config.json", "failed", output_paths=child_outputs)
            (child / "run_manifest.json").write_text(json.dumps(child_manifest), encoding="utf-8")
            grand = root / "20261029_120002__sim__simion__grand"
            shutil.copytree(child / "inputs", grand / "inputs")
            grand_config = json.loads(json.dumps(child_config).replace(str(child).replace("\\", "\\\\"), str(grand).replace("\\", "\\\\")))
            grand_config["run_id"] = grand.name
            (grand / "run_config.json").write_text(json.dumps(grand_config), encoding="utf-8")
            inherited = prepare(grand, child, ["rf_on"], "compact", False)
            self.assertEqual((inherited["replay"]["reusable_unit_count"], inherited["replay"]["replay_unit_count"]), (2, 0))
            self.assertTrue(any(str(parent) in item["path"] for item in inherited["replay"]["units"][0]["terminal_outputs"]))
            outputs.extend(complete(2))
            publish()
            full = prepare(child, parent, ["rf_on"], "compact", False)
            self.assertEqual((full["replay"]["reusable_unit_count"], full["replay"]["replay_unit_count"]), (2, 0))
            child_physics = child / "inputs/simion_fly_physics.json"
            unused_changed = json.loads(json.dumps(physics_document))
            unused_changed["cases"]["unused_case"]["rf"] = 3
            child_physics.write_text(json.dumps(unused_changed), encoding="utf-8")
            self.assertEqual(prepare(child, parent, ["rf_on"], "compact", False)["replay"]["reusable_unit_count"], 2)
            child_physics.write_text(json.dumps(physics_document), encoding="utf-8")
            parent_manifest = parent / "run_manifest.json"
            parent_before = hashlib.sha256(parent_manifest.read_bytes()).digest()
            state = parent / "results/particle_states__rf_on__batch_01.csv"
            original_state = state.read_bytes()
            state.write_bytes(b"corrupted")
            with self.assertRaisesRegex(ContractError, "hash differs"):
                prepare(child, parent, ["rf_on"], "compact", False)
            state.write_bytes(original_state)
            physics = child / "inputs/simion_fly_physics.json"
            for key in physical_keys:
                physics.write_text(json.dumps({**physics_document, key: "changed"}), encoding="utf-8")
                with self.subTest(changed_physical_field=key), self.assertRaisesRegex(ValueError, "simion_fly_physics"):
                    prepare(child, parent, ["rf_on"], "compact", False)
            physics.write_text(json.dumps(physics_document), encoding="utf-8")
            inventory = child / "inputs/code_inventory.json"
            original_inventory = json.loads(inventory.read_text(encoding="utf-8"))
            changed_inventory = json.loads(json.dumps(original_inventory))
            changed_inventory["files"][2]["sha256"] = "different-batch-slicing"
            inventory.write_text(json.dumps(changed_inventory), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "batch source code differs"):
                prepare(child, parent, ["rf_on"], "compact", False)
            inventory.write_text(json.dumps(original_inventory), encoding="utf-8")
            (child / "inputs/particle_source.json").write_text("different", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "particle_source"):
                prepare(child, parent, ["rf_on"], "compact", False)
            self.assertEqual(hashlib.sha256(parent_manifest.read_bytes()).digest(), parent_before)


if __name__ == "__main__":
    unittest.main()
