"""Accelerator interface ownership and detached preparation; no vendor solver."""
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import ValidationError

from common.contracts.write_run_manifest import build_run_manifest, file_record
from integrations.workflows.accelerator_interface.prepare import (
    CONFIG, _resolve_ip_matching, bind_joint_workbench, prepare_interface, prepare_joint_flight, verified_preparation_reference,
)

REPO = Path(__file__).resolve().parents[2]
MR = REPO / "projects/parallel_mirror_dual_stripe_mr_tof"


def reference_fixture(root, *, frame_id="astral.xyz.v2"):
    reference = root / "reference"
    (reference / "simion").mkdir(parents=True)
    config = reference / "run_config.json"
    config.write_text(json.dumps(dict(project=MR.name, inputs={})))
    trajectory = reference / "simion/trajectory_contract.json"
    trajectory.write_text(json.dumps(dict(coordinate_system=dict(frame_id=frame_id),
        accelerator=dict(focus_y_anchor=dict(project_y_mm=-55)))))
    provider = reference / "simion/accelerator_provider_runtime_receipt.json"
    provider.write_text(json.dumps(dict(mrtof_projection=dict(target_axial_energy_per_charge_v=4372))))
    (reference / "run_manifest.json").write_text(json.dumps(dict(project=MR.name, status="success",
        run_config=file_record(config), inputs={}, outputs=[file_record(trajectory), file_record(provider)])))
    return reference


class AcceleratorInterfaceTests(unittest.TestCase):
    def test_actual_iob_entry_verifies_live_assets_once_after_guards_and_before_vendor(self):
        powershell = shutil.which("pwsh")
        if not powershell:
            self.skipTest("PowerShell 7 required")
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_static_field_binding import NativeStaticBindingTest
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fields = root / "fields"
            fields.mkdir()
            binding = NativeStaticBindingTest().fixture(fields)
            result = root / "results/joint_workbench"
            result.mkdir(parents=True)
            (result / "static_field_binding.json").write_text(json.dumps(binding))
            script = root / "entry.ps1"
            script.write_text(r'''param($Runner,$Root,$Repository,$PythonRuntime,$Bad)
$ErrorActionPreference='Stop'
$ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$null,[ref]$null)
$branch=$ast.Find({param($n) $n-is[Management.Automation.Language.IfStatementAst]-and$n.Clauses[0].Item1.Extent.Text-eq'$FinalizeJointWorkbench'-and$n.Extent.Text.Contains('$paGuards.Add')},$true)
$statements=$branch.Clauses[0].Item2.Statements
$guard=@($statements|Where-Object{$_-is[Management.Automation.Language.ForEachStatementAst]-and$_.Extent.Text.Contains('$guardPaths')})
$enter=@($statements|Where-Object{$_.Extent.Text.StartsWith('$lease=Enter-HostExecutionLease')})
$verify=@($statements|Where-Object{$_.Extent.Text.StartsWith('Invoke-RunToolRootContext')-and$_.Extent.Text.Contains('verify_joint_asset_records')})
if($guard.Count-ne1-or$enter.Count-ne1-or$verify.Count-ne1){throw 'Actual entry stages are not unique'}
$guardPaths=@((Join-Path $Root 'fields/parent/field.pa'),(Join-Path $Root 'fields/local/field.pa'))
$paGuards=[Collections.Generic.List[IDisposable]]::new();$script:leased=$false
$script:pythonRoot=$Repository;$python=$PythonRuntime;$package=@{result_dir=(Join-Path $Root 'results')}
function Enter-HostExecutionLease {$script:leased=$true;return @{}}
function Invoke-RunToolRootContext {
 param($RepoRoot,$Operation)
 if(-not$script:leased-or$paGuards.Count-ne4){throw 'Verification preceded native lease/guards'}
 $writable=$false
 try{$probe=[IO.File]::Open($guardPaths[0],[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::ReadWrite);$probe.Dispose();$writable=$true}catch{}
 if($writable){throw 'Live PA writer was not denied'}
 Push-Location $RepoRoot
 try{&$Operation}finally{Pop-Location}
}
$vendorAllowed=$false;$caught=$false
try{
 Invoke-Expression $guard[0].Extent.Text
 Invoke-Expression $enter[0].Extent.Text
 Invoke-Expression $verify[0].Extent.Text
 $vendorAllowed=$true
}catch{$caught=$true}finally{foreach($item in $paGuards){$item.Dispose()}}
if(($Bad-eq'bad')-ne$caught-or($Bad-eq'bad')-eq$vendorAllowed){throw 'Live identity did not control vendor admission'}
'ACTUAL_IOB_ASSET_BOUNDARY_PASS'
''', encoding="utf-8")
            for state in ("valid", "bad"):
                if state == "bad":
                    (fields / "parent/field.pa").write_bytes(b"XX")
                completed = subprocess.run([powershell, "-NoProfile", "-File", str(script),
                    str(REPO / "integrations/workflows/accelerator_interface/execute.ps1"), str(root), str(REPO),
                    sys.executable, state], cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=40)
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                self.assertIn("ACTUAL_IOB_ASSET_BOUNDARY_PASS", completed.stdout)

    def test_final_binding_uses_private_four_and_five_slot_seeds_with_one_payload(self):
        """Tiny inert PA bytes test alias layout, not vendor PA loading or fields."""
        from integrations.workflows.accelerator_interface import prepare as module
        for count in (4, 5):
            with self.subTest(slots=count), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                snapshot = root/"snapshot"
                assets = snapshot/"common/simion/assets/iob_instance_seeds"
                assets.mkdir(parents=True)
                seed = assets/f"{count}_instance_seed.iob"
                shutil.copyfile(REPO/"common/simion/assets/iob_instance_seeds"/seed.name, seed)
                payload = assets/"iob_seed_placeholder_01.pa0"
                payload.write_bytes(b"inert shared PA fixture; not a SIMION field")
                originals = {path: path.read_bytes() for path in (seed, payload)}
                scripts = snapshot/"projects/parallel_mirror_dual_stripe_mr_tof/simion"
                scripts.mkdir(parents=True)
                for name in ("mrtof_candidate.lua", "mirror_cycle_counter.lua", "scalar_field_adapter.lua", "build_native_corridor_iob.lua"):
                    (scripts/name).write_text("-- inert frozen script fixture")
                waveform = snapshot/"common/simion/voltage_waveforms.lua"
                waveform.write_bytes((REPO/"common/simion/voltage_waveforms.lua").read_bytes())
                design, fields, actual = (root/name for name in ("design", "fields", "actual"))
                for path in (design/"inputs", design/"results/joint_flight", fields/"results", actual/"inputs"):
                    path.mkdir(parents=True)
                def write(path, value):
                    path.write_text(json.dumps(value), encoding="utf-8")
                write(design/"run_manifest.json", {})
                configs = {key: dict(identity=key) for key in ("baseline", "native_operating_point", "numerics", "source", "coordinate_transform")}
                configs["baseline"]["electric"] = dict(lift_v=4480)
                configs["source"] = dict(species=dict(mass_amu=524, charge_state=1),
                                         sampling=dict(strategy="independent_fixture_release"))
                actual_configs = dict(configs, source=dict(species=dict(mass_amu=524.0, charge_state=1),
                                                          particle_count=81, mother_particle_count=100))
                paths = {}
                for name, value in configs.items():
                    path = design/"inputs"/(name+".json")
                    write(path, value)
                    paths[name] = str(path)
                from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_handoff import resolve_ip_mr_connection
                plan = json.loads((REPO/"integrations/config/recipes/ip_mr_y_minus55_plan.json").read_text())
                connection = resolve_ip_mr_connection(plan)
                pose = plan["recipe"]["instances"][0]["transform"]
                write(design/"inputs/composition_plan.json", plan)
                write(design/"inputs/accelerator_request.json", json.loads((CONFIG/"ion_processor_matching_request.json").read_text()))
                geometry = design/"inputs/geometry.json"
                scientific_geometry = dict(frame_id=plan["assembly_frame_id"], physical_fixture=dict(width_mm=1))
                write(geometry, dict(scientific_geometry, ion_processor_instance_id="non_authoritative_label"))
                matching = design/"inputs/matching_assembly_request.json"
                projection = dict(values_v15=list(range(15)), basis="post_extraction_pulse_held_rf_zero",
                    evaluated_native_operating_point=configs["native_operating_point"], evaluated_baseline_lift_v=4480)
                write(matching, dict(field_assembly_reference=dict(provider_voltage_projection=projection)))
                materialization = design/"inputs/reference_materialization.json"
                write(materialization, {})
                write(design/"results/joint_flight/joint_preparation_receipt.json", dict(
                    reference_materialization=file_record(materialization),
                    numerics=dict(trajectory_quality=3,maximum_step_us=.004,full_path_timeout_us=100),
                    assembly=dict(source_config_paths=paths, assembly_geometry_path=str(geometry),
                                  composition_plan=plan, assembly_coordinate_transform=pose, input_identities=[file_record(matching)])))
                (design/"inputs/reference_operating_point.lua").write_text("return {}")
                write(actual/"inputs/resolved_model.json", actual_configs)
                write(fields/"results/field_binding.json", {})
                component, handoff = root/"component.json", root/"handoff.json"
                write(component, dict(source_run=str(actual)))
                write(handoff, dict(connection=connection, inputs=dict(component_receipt=file_record(component))))
                comparison = dict(role="mrtof_measured_exit_energy_comparison", centroid_match_accepted=None,
                                  inputs=dict(component_receipt=file_record(component)))
                binding = dict(accelerator_provider="dual_pressure_rectilinear_ion_processor", geometry=scientific_geometry,
                    grid=dict(origin_mm=[0, 0, 0], pitch_mm=[1, 1, 1], dimensions=[2, 2, 2]),
                    sources=dict(scalar_pa=str(fields/"parent.pa")), refinement_windows=[],
                    authority=dict(analyzer_electrode_voltages_v=[369.0] * 20,
                        component_voltages_v=[dict(component_namespace="ion_processor", component_electrode_id=i+1, voltage_v=i) for i in range(15)]
                            + [dict(component_namespace="detector", component_electrode_id=25, voltage_v=0)],
                        assembly=dict(ion_processor_registration=pose, post_extraction_state="pulse_held_rf_zero",
                                      native_operating_point=configs["native_operating_point"])),
                    instances=[dict(pa_path=str(fields/f"field_{index}.pa"), origin_mm=[0, 0, 0]) for index in range(count)])
                def source_projection(_handoff, output):
                    output.mkdir()
                    for name in ("source_runtime.lua", "source.fly2"):
                        (output/name).write_text("inert source fixture")
                    return dict(counts=dict(source=1, transferred=1, not_transferred=0))
                with patch.object(module, "REPO", snapshot), \
                        patch.object(module, "verified_reference", side_effect=lambda run, relative, **kw: run/relative), \
                        patch.object(module, "verified_preparation_reference", side_effect=lambda run, relative, **kw: run/relative), \
                        patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding.load_binding", return_value=binding), \
                        patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.measured_component_source.materialize_measured_source", side_effect=source_projection), \
                        patch.object(module, "collision_workbench_layout", return_value=dict(seed=str(seed), priority={})), \
                        patch.object(module, "render_measured_operating_point", return_value="return {}"), \
                        patch.object(module, "prepare_interface_field_audit", return_value={}):
                    # A different real source is allowed; changing its species or
                    # any configuration that produced the field is not.
                    for name in ("baseline", "native_operating_point", "numerics", "coordinate_transform", "source"):
                        changed = dict(actual_configs)
                        changed[name] = (dict(species=dict(mass_amu=100, charge_state=1)) if name == "source"
                                         else dict(actual_configs[name], changed=True))
                        write(actual/"inputs/resolved_model.json", changed)
                        rejected = root/("rejected_"+name)
                        with self.subTest(configuration=name), self.assertRaisesRegex(
                                ValueError, "species differs" if name == "source" else "differs from prepared design"):
                            bind_joint_workbench(design_run=design, field_run=fields, source_run=actual,
                                handoff_receipt=handoff, energy_comparison=comparison, output_directory=rejected)
                        self.assertFalse(rejected.exists())
                    write(actual/"inputs/resolved_model.json", actual_configs)
                    # Routing-only labels may differ; physical identity and current
                    # assembly scope/pose must still fail before source/IOB outputs.
                    original_report = json.loads((design/"results/joint_flight/joint_preparation_receipt.json").read_text())
                    import copy
                    for defect in ("scope", "design_pose", "field_pose", "physical_csg", "source_instance", "old_request", "old_plan", "field_ip_voltage", "field_point", "lift", "pulse_basis"):
                        changed_report = copy.deepcopy(original_report)
                        if defect == "scope": changed_report["assembly"]["composition_plan"]["scope"]["kind"] = "other"
                        elif defect == "design_pose": changed_report["assembly"]["assembly_coordinate_transform"]["translation_mm"][0] += 1
                        elif defect == "field_pose": binding["authority"]["assembly"]["ion_processor_registration"] = dict(pose, translation_mm=[1, -225, 9.8])
                        elif defect == "physical_csg": binding["geometry"] = dict(scientific_geometry, physical_fixture=dict(width_mm=2))
                        elif defect == "source_instance": write(handoff, dict(connection=dict(connection, connection_id="unrelated"), inputs=dict(component_receipt=file_record(component))))
                        elif defect == "old_request":
                            request = json.loads((CONFIG/"ion_processor_matching_request.json").read_text())
                            request["schema_version"] = 1
                            write(design/"inputs/accelerator_request.json", request)
                        elif defect == "old_plan": write(design/"inputs/composition_plan.json", dict(plan, schema_version=2))
                        elif defect == "field_ip_voltage": binding["authority"]["component_voltages_v"][0]["voltage_v"] += 1
                        elif defect == "field_point": binding["authority"]["assembly"]["native_operating_point"] = dict(configs["native_operating_point"], changed=True)
                        elif defect == "lift": write(matching, dict(field_assembly_reference=dict(provider_voltage_projection=dict(projection, evaluated_baseline_lift_v=4481))))
                        else: binding["authority"]["assembly"]["post_extraction_state"] = "RF_active"
                        write(design/"results/joint_flight/joint_preparation_receipt.json", changed_report)
                        rejected = root/("rejected_"+defect)
                        with self.subTest(binding_defect=defect), self.assertRaises((ValueError, ValidationError)):
                            bind_joint_workbench(design_run=design, field_run=fields, source_run=actual,
                                handoff_receipt=handoff, energy_comparison=comparison, output_directory=rejected)
                        self.assertFalse(rejected.exists())
                        binding["authority"]["component_voltages_v"][0]["voltage_v"] = 0
                        binding["authority"]["assembly"]["native_operating_point"] = configs["native_operating_point"]
                        binding["authority"]["assembly"]["post_extraction_state"] = "pulse_held_rf_zero"
                        write(matching, dict(field_assembly_reference=dict(provider_voltage_projection=projection)))
                        binding["geometry"] = scientific_geometry
                        binding["authority"]["assembly"]["ion_processor_registration"] = pose
                        write(handoff, dict(connection=connection, inputs=dict(component_receipt=file_record(component))))
                        write(design/"inputs/composition_plan.json", plan)
                        write(design/"inputs/accelerator_request.json", json.loads((CONFIG/"ion_processor_matching_request.json").read_text()))
                    write(design/"results/joint_flight/joint_preparation_receipt.json", original_report)
                    # The public finalizer must reject inconsistent measured inputs
                    # before creating frozen inputs or exported/handoff states.
                    reference = reference_fixture(root)
                    write(design/"results/accelerator_interface_preparation.json", dict(
                        selected_provider="dual_pressure_rectilinear_ion_processor",
                        inputs=dict(reference_manifest=file_record(reference/"run_manifest.json"))))
                    changed = dict(actual_configs, numerics=dict(changed=True))
                    write(actual/"inputs/resolved_model.json", changed)
                    rejected = root/"rejected_finalize"
                    with patch.object(module, "freeze_file", wraps=module.freeze_file) as freeze, \
                            patch.object(module, "_resolve_ip_matching") as export:
                        with self.assertRaisesRegex(ValueError, "differs from prepared design: numerics"):
                            module.finalize_interface(source_run=actual, reference_mr_run=reference,
                                design_run=design, field_run=fields, run_directory=rejected)
                        freeze.assert_not_called()
                        export.assert_not_called()
                    self.assertFalse(rejected.exists())
                    write(actual/"inputs/resolved_model.json", actual_configs)
                    result = bind_joint_workbench(design_run=design, field_run=fields, source_run=actual,
                        handoff_receipt=handoff, energy_comparison=comparison, output_directory=root/"bound")
                runtime = root/"bound/runtime"
                self.assertEqual((runtime/"mrtof_candidate.voltage_waveforms.lua").read_bytes(), waveform.read_bytes())
                self.assertEqual(Path(result["workbench_build_contract"]["seed"]), runtime/seed.name)
                self.assertEqual((runtime/seed.name).read_bytes(), originals[seed])
                aliases = sorted(runtime.glob("iob_seed_placeholder_*.pa0"))
                self.assertEqual([path.name for path in aliases], [f"iob_seed_placeholder_{index:02d}.pa0" for index in range(1, count+1)])
                self.assertTrue(all(os.path.samefile(path, payload) for path in aliases))
                self.assertEqual(len({path.stat().st_ino for path in [payload, *aliases]}), 1)
                self.assertEqual({path: path.read_bytes() for path in originals}, originals)
                self.assertEqual(sorted(path.name for path in assets.iterdir()), sorted(path.name for path in originals))
                self.assertIn(module._lua(str(runtime/seed.name)), (runtime/"workbench_build.lua").read_text())
                self.assertEqual(result["guard_paths"], sorted({item["pa_path"] for item in binding["instances"]} | {binding["sources"]["scalar_pa"]}))

    def test_runner_publishes_consumed_paths_through_public_manifest_writer(self):
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = reference_fixture(root)
            run = root / "20261022_210000__analysis__python__interface-publication"
            (run / "inputs").mkdir(parents=True)
            (run / "results").mkdir()
            receipt = prepare_interface(source_run=None, reference_mr_run=reference, run_directory=run,
                                        provider="orthogonal_accelerator")
            receipt_path = run / "results/accelerator_interface_preparation.json"
            config = run / "run_config.json"
            config.write_text(json.dumps(dict(schema_version=2, run_id=run.name,
                project="instrument_assembly", mode="accelerator_interface_preparation", inputs={},
                artifact_retention=dict(policy_version=1, **{"class": "compact"}, reason=None))))
            # Execute the actual runner's publication projection, without its solver stages.
            command = f"""
$tokens=$null;$errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile('{REPO / 'integrations/workflows/accelerator_interface/execute.ps1'}',[ref]$tokens,[ref]$errors)
if($errors.Count){{throw 'Runner parsing failed'}}
$loops=@($ast.FindAll({{param($node) $node -is [System.Management.Automation.Language.ForEachStatementAst] -and $node.Condition.Extent.Text -eq '$receipt.inputs.Keys'}},$true))
if($loops.Count-ne1){{throw 'Expected one consumed-input publication boundary'}}
$receipt=Get-Content -LiteralPath '{receipt_path}' -Raw|ConvertFrom-Json -AsHashtable
$configuration=Get-Content -LiteralPath '{config}' -Raw|ConvertFrom-Json -AsHashtable
. ([scriptblock]::Create($loops[0].Extent.Text))
$configuration|ConvertTo-Json -Depth 50|Set-Content -LiteralPath '{config}' -Encoding utf8
"""
            completed = subprocess.run([pwsh, "-NoProfile", "-Command", command], cwd=REPO,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)
            manifest = build_run_manifest(config, "success", output_paths=[receipt_path])
            self.assertEqual(set(manifest["inputs"]), set(receipt["inputs"]))
            (run / "run_manifest.json").write_text(json.dumps(manifest))
            for name, record in receipt["inputs"].items():
                with self.subTest(input=name):
                    self.assertEqual(manifest["inputs"][name]["sha256"], record["sha256"])
                    path = Path(record["path"])
                    self.assertEqual(verified_preparation_reference(run, str(path.relative_to(run))), path)
            request = run / "inputs/accelerator_request.json"
            request.write_text('{"changed":true}')
            with self.assertRaisesRegex(AssertionError, "byte count|SHA-256"):
                verified_preparation_reference(run, "inputs/accelerator_request.json")

    def test_runner_preserves_published_success_when_capacity_handoff_fails(self):
        """Execute the real terminal block/catch and public writer; no vendor calls."""
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 is unavailable")
        harness = r"""param($Repo,$Python,$Run,$Scenario)
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
$errors=$null;$tokens=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Repo 'integrations/workflows/accelerator_interface/execute.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$owner=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.TryStatementAst]-and$n.CatchClauses.Count-gt0},$false))[0]
$statements=@($owner.Body.Statements)
$start=@(0..($statements.Count-1)|Where-Object{$statements[$_].Extent.Text-eq"`$stage='terminal_publication'"})
if($start.Count-ne1){throw 'terminal publication boundary missing'}
$publish=[scriptblock]::Create(($statements[$start[0]..($statements.Count-1)]|ForEach-Object{$_.Extent.Text})-join"`n")
$handler=[scriptblock]::Create(($owner.CatchClauses[0].Body.Statements.Extent.Text)-join"`n")
$finalizer=[scriptblock]::Create(($owner.Finally.Statements.Extent.Text)-join"`n")
$package=@{run_config=(Join-Path $Run 'run_config.json');summary=(Join-Path $Run 'summary.json');result_dir=(Join-Path $Run 'results');artifact_run_dir=$Run}
$repoRoot=$Repo;$workspaceRoot=Split-Path -Parent $Run;$python=$Python
$terminalized=$false;$stage='fixture';$software=@('Python inert boundary');$extraOutputs=@()
$AcceleratorProvider='orthogonal_accelerator';$RunId=Split-Path -Leaf $Run
$capacitySession=@{active=$true};$lease=$null;$paGuards=[Collections.Generic.List[IO.FileStream]]::new()
$log=Join-Path $Run 'logs/prepare.log'
$script:firstRetention=$true;$script:released=$false;$script:finalized=$false
function Apply-RunArtifactRetention {
 param($Python,$RepoRoot,$RunConfig)
 if($Scenario-eq'prepublish'-and$script:firstRetention){$script:firstRetention=$false;throw 'INERT_PREPUBLICATION_FAILURE'}
 $path=Join-Path (Split-Path -Parent $RunConfig) 'retention_actions.json'
 [IO.File]::WriteAllText($path,'{}');return $path
}
function Update-ArtifactWorkflowCapacitySession {
 param($Python,$RepoRoot,$Session,$RemainingCommittedNewBytes)
 return @{session=$Session}
}
function Invoke-RunCapacityLifecycleAdapter {
 param($Python,$RepoRoot,$Action,$ArtifactRoot,$RunConfig)
 if($Action-eq'assert-retention'){return @{status='retention_valid'}}
 if($Action-ne'finalize-ready'){throw 'unexpected lifecycle action'}
 $script:finalized=$true
 if($Scenario-eq'postpublish'){
  foreach($name in @('summary.json','run_manifest.json')){
   [IO.File]::WriteAllBytes((Join-Path $Run ($name+'.published')),[IO.File]::ReadAllBytes((Join-Path $Run $name)))
  }
  throw 'INERT_CAPACITY_FINALIZATION_FAILURE'
 }
 return @{light_evidence_budget_exceeded=$false}
}
function Exit-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session)$script:released=$true}
$caught=''
$execution=[scriptblock]::Create("try{`n"+$publish.ToString()+"`n}catch{`n"+$handler.ToString()+"`n}finally{`n"+$finalizer.ToString()+"`n}")
try{. $execution}catch{$caught=$_.Exception.Message}
@{caught=$caught;released=$script:released;finalized=$script:finalized;terminalized=$terminalized}|ConvertTo-Json -Compress
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "terminal_boundary.ps1"
            script.write_text(harness, encoding="utf-8", newline="\n")
            for index, scenario in enumerate(("postpublish", "prepublish", "success")):
                with self.subTest(scenario=scenario):
                    run = root / f"20261025_10000{index}__test__python__interface-terminal"
                    for child in ("inputs", "results", "logs"):
                        (run / child).mkdir(parents=True)
                    (run / "logs/prepare.log").write_text("inert preparation completed\n", encoding="utf-8")
                    (run / "summary.json").write_text(json.dumps(dict(status="success", science="preserved")), encoding="utf-8")
                    (run / "run_config.json").write_text(json.dumps(dict(schema_version=1,
                        run_id=run.name, project="instrument_assembly", mode="accelerator_interface_preparation", inputs={},
                        capacity_ledger_lifecycle=dict(enabled=True, artifact_root=str(root / "artifacts")))), encoding="utf-8")
                    result = subprocess.run([pwsh, "-NoProfile", "-File", str(script), str(REPO), sys.executable,
                        str(run), scenario], cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=60)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    report = json.loads(result.stdout.strip().splitlines()[-1])
                    self.assertTrue(report["released"])
                    self.assertTrue(report["finalized"])
                    expected = "failed" if scenario == "prepublish" else "success"
                    self.assertEqual(json.loads((run / "summary.json").read_text())["status"], expected)
                    self.assertEqual(json.loads((run / "run_manifest.json").read_text())["status"], expected)
                    error = {"postpublish": "INERT_CAPACITY_FINALIZATION_FAILURE", "prepublish": "INERT_PREPUBLICATION_FAILURE", "success": ""}[scenario]
                    self.assertEqual(report["caught"], error)
                    if scenario == "postpublish":
                        self.assertIn("capacity handoff failed", result.stdout)
                        for name in ("summary.json", "run_manifest.json"):
                            self.assertEqual((run / name).read_bytes(), (run / (name + ".published")).read_bytes())

    def test_runner_python_commands_disable_snapshot_bytecode(self):
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 is unavailable")
        command = r"""param($Source,$Python)
$ErrorActionPreference='Stop'
$errors=$null;$tokens=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$commands=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.CommandAst]-and$n.CommandElements[0].Extent.Text-eq'$python'},$true))
if($commands.Count-ne3){throw 'expected preparation, live-asset verification and field-audit Python calls'}
foreach($call in $commands){if($call.CommandElements[1].Extent.Text-ne'-B'){throw 'snapshot call permits bytecode'}}
$python=$Python;$arguments=@('-c','import sys; assert sys.dont_write_bytecode; print("SNAPSHOT_BYTECODE_DISABLED=PASS")')
. ([scriptblock]::Create($commands[0].Extent.Text))
if($LASTEXITCODE-ne0){throw 'actual preparation command did not disable bytecode'}
"""
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "bytecode.ps1"
            script.write_text(command, encoding="utf-8", newline="\n")
            result = subprocess.run([pwsh, "-NoProfile", "-File", str(script),
                str(REPO / "integrations/workflows/accelerator_interface/execute.ps1"), sys.executable],
                cwd=directory, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("SNAPSHOT_BYTECODE_DISABLED=PASS", result.stdout)

    def test_new_preparation_consumes_only_unique_manifest_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "value.json"
            data.write_text("{}")
            manifest = dict(project="instrument_assembly", mode="accelerator_interface_preparation",
                            status="success", inputs={"value": file_record(data)}, outputs=[])
            # A run_config path is deliberately absent: it is not a second record authority.
            self.assertEqual(verified_preparation_reference(root, data.name, manifest=manifest), data)
            for owner, mode in ((MR.name, "accelerator_interface_preparation"),
                                ("instrument_assembly", "prepared_joint")):
                with self.assertRaisesRegex(ValueError, "successful instrument_assembly"):
                    verified_preparation_reference(root, data.name, manifest=dict(manifest, project=owner, mode=mode))
            with self.assertRaisesRegex(ValueError, "exactly one"):
                verified_preparation_reference(root, data.name, manifest=dict(manifest, outputs=[file_record(data)]))
            data.write_text('{"changed":true}')
            with self.assertRaisesRegex(AssertionError, "byte count|SHA-256"):
                verified_preparation_reference(root, data.name, manifest=manifest)

    def test_oa_requirement_preparation_uses_real_mr_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = reference_fixture(root)
            run = root / "prepared"
            (run / "inputs").mkdir(parents=True)
            (run / "results").mkdir()
            receipt = prepare_interface(source_run=None, reference_mr_run=reference, run_directory=run,
                                        provider="orthogonal_accelerator")
            self.assertEqual(receipt["reference_requirements"]["frame_id"], "astral.xyz.v2")
            self.assertEqual(receipt["reference_requirements"]["project_y_mm"], -55)
            self.assertEqual(receipt["reference_requirements"]["axial_energy_per_charge_v"], 4372)
            self.assertIsNone(receipt["joint_preparation"])
            self.assertFalse(list((run / "inputs").glob("*.py")))

    def matching_fixture(self):
        from projects.dual_pressure_rectilinear_ion_processor.tests.test_component_exit import ComponentExitTests
        fixture = ComponentExitTests("test_preserves_noncontiguous_ids_complete_state_and_variable_absolute_clocks")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture._negative_population()
        plan_path = REPO / "integrations/config/recipes/ip_mr_y_minus55_plan.json"
        plan = json.loads(plan_path.read_text())
        mr_provider = next(component for component in plan["components"].values()
                           if component["project_id"] == MR.name)
        reference = reference_fixture(fixture.root, frame_id=mr_provider["local_frame_id"])
        result = fixture.root / "result"
        inputs = fixture.root / "frozen"
        result.mkdir()
        inputs.mkdir()
        sources = dict(accelerator_dependency=CONFIG / "ion_processor_dependency.json",
            reference_trajectory=reference / "simion/trajectory_contract.json",
            reference_provider=reference / "simion/accelerator_provider_runtime_receipt.json",
            accelerator_request=CONFIG / "ion_processor_matching_request.json",
            composition_plan=plan_path)
        recipe = plan["recipe"]
        recipe["instances"][0]["transform"]["from_frame_id"] = fixture.model["coordinate_transform"]["from_frame_id"]
        for instance, name in zip(recipe["instances"], ("processor_a", "analyzer_b")):
            instance["instance_id"] = name
        recipe["connections"][0]["upstream"]["instance_id"] = "processor_a"
        recipe["connections"][0]["downstream"]["instance_id"] = "analyzer_b"
        local_recipe = fixture.root / "author_recipe.json"
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_ion_processor_handoff import handoff_plan
        local_recipe.write_text(json.dumps(handoff_plan(recipe)))
        sources["composition_plan"] = local_recipe
        matching = _resolve_ip_matching(source_run=fixture.run, results=result, inputs=inputs,
                                     frozen={name: file_record(path) for name, path in sources.items()})
        return fixture, reference, result, inputs, sources, matching

    def test_ip_design_prepares_only_assembly_field_plan_and_real_handoff(self):
        lua = shutil.which("lua") or "C:/Program Files/SIMION-2020/lua.exe"
        if not Path(lua).is_file():
            self.skipTest("plain Lua unavailable")
        import copy
        from projects.dual_pressure_rectilinear_ion_processor.tests.test_functional import load_config
        fixture, reference, result, inputs, sources, matching = self.matching_fixture()
        shutil.copyfile(sources['reference_trajectory'],inputs/'reference_trajectory.json')
        original_model = Path(matching['source_model_path']).read_bytes()
        original_states = copy.deepcopy(matching['rows'])
        materialization = inputs/'reference_materialization.json'
        materialization.write_text('{}')
        references = dict(reference_materialization=file_record(materialization),
                          numerics=dict(trajectory_quality=3,maximum_step_us=.004,full_path_timeout_us=100))
        configs = load_config()
        # Keep the fixture's measured source/clock; supply the actual provider
        # voltage author fields so this boundary also executes its frozen Lua.
        matching['source_model']['native_operating_point'] = copy.deepcopy(configs['native_operating_point'])
        for name in ('schedule', 'electric'):
            matching['source_model']['baseline'][name] = copy.deepcopy(configs['baseline'][name])
        matching['source_model']['native_timing'] = copy.deepcopy(configs['native_timing'])
        shutil.copyfile(sources['accelerator_dependency'], inputs/'accelerator_dependency.json')
        frozen_configs = {}
        geometry_bytes = b'{"inert_geometry_boundary_fixture":true}\n'
        def geometry_boundary(source, trajectory, request, *, connection, input_paths, output_directory):
            self.assertEqual(source,matching['source_model'])
            self.assertEqual(connection,matching['connection'])
            seed = output_directory/'seed'
            seed.mkdir(parents=True)
            for name,value in configs.items():
                path = seed/(name+'.json')
                path.write_text(json.dumps(value))
                frozen_configs[path] = path.read_bytes()
            geometry = output_directory/'assembly_geometry.json'
            geometry.write_bytes(geometry_bytes)
            field_plan = output_directory/'field_assembly_plan.json'
            field_plan.write_text(json.dumps(dict(fields=[],scope='inert geometry boundary fixture')))
            report = dict(source_config_paths={name:str(seed/(name+'.json')) for name in configs},
                composition_plan=request['composition_plan'],assembly_geometry_path=str(geometry),
                field_plan_path=str(field_plan),energy_seed=dict(qualification='unvalidated_test_boundary'),geometry_changes=[])
            return dict(report=report,seed_configs=copy.deepcopy(configs))
        module = 'integrations.workflows.accelerator_interface.prepare'
        with patch(module+'.freeze_field_reference',return_value=references) as freeze, \
             patch('integrations.workflows.accelerator_interface.geometry.prepare_ion_processor_assembly',side_effect=geometry_boundary), \
             patch('projects.parallel_mirror_dual_stripe_mr_tof.analysis.measured_component_source.materialize_measured_source',
                   side_effect=AssertionError('design must not materialize a draft flight source')):
            receipt = prepare_joint_flight(reference_run=reference,
                interface_results=result,frozen_inputs=inputs,lua_executable=Path(lua),matching=matching)
        freeze.assert_called_once_with(reference,inputs,compiler_contract=matching['inputs']['trajectory_contract'])
        design = result/'joint_flight'
        self.assertEqual({path.name for path in design.iterdir()},
                         {'assembly','provider_execution_recipe.json','joint_preparation_receipt.json'})
        self.assertEqual(json.loads((design/'joint_preparation_receipt.json').read_text()),receipt)
        self.assertEqual(receipt['reference_materialization'],references['reference_materialization'])
        self.assertEqual(receipt['numerics'],references['numerics'])
        projection = json.loads((inputs/'provider_voltage_projection.json').read_text())
        self.assertEqual(Path(projection['source_voltage_waveforms']['path']).read_bytes(),
            (REPO/'common/simion/voltage_waveforms.lua').read_bytes())
        self.assertTrue(Path(receipt['field_plan']['path']).is_file())
        self.assertEqual(Path(receipt['assembly']['assembly_geometry_path']).read_bytes(),geometry_bytes)
        for path,content in frozen_configs.items(): self.assertEqual(path.read_bytes(),content)
        self.assertEqual(Path(matching['source_model_path']).read_bytes(),original_model)
        self.assertEqual(matching['rows'],original_states)
        execution = json.loads((design/'provider_execution_recipe.json').read_text())
        self.assertEqual(execution['configuration_directory'],str(Path(receipt['assembly']['source_config_paths']['baseline']).parent))
        self.assertFalse(execution['execution_performed'])
        self.assertFalse(receipt['solver_executed'])
        self.assertFalse({'measured_source','workbench_build_contract','future_workbench_build_arguments',
                          'source_adapter_materialized','runtime_adapter_materialized','field_assembly_materialized',
                          'field_solution_exists','source_matches_new_workpoint','fly_authorized','analysis_consumer',
                          'event_particle_identity'} & receipt.keys())
        handoff = json.loads((result/'mrtof_handoff/handoff_receipt.json').read_text())
        self.assertEqual(handoff['counts'],dict(source=100,transferred=81,not_transferred=19))
        with (result/'mrtof_handoff/component_particle_state.csv').open(newline='') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual([int(row['particle_id']) for row in rows],list(range(1,82)))
        self.assertEqual([float(row['instrument_time_us']) for row in rows],[300+pid/10 for pid in range(1,82)])
        self.assertEqual([float(row['particle_birth_time_us']) for row in rows],list(range(101,182)))
        self.assertEqual((result/'mrtof_handoff/source_census.csv').read_bytes(),
                         (result/'ion_processor_exit/source_census.csv').read_bytes())

    def test_ip_export_and_handoff_use_actual_provider_without_source_reloading(self):
        fixture, reference, result, inputs, sources, matching = self.matching_fixture()
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_handoff import prepare_handoff
        handoff = prepare_handoff(matching, matching["resolved"]["composition_plan"], result / "mrtof_handoff")
        self.assertEqual(handoff["counts"], dict(source=100, transferred=81, not_transferred=19))
        with (result / "mrtof_handoff/component_particle_state.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual({row["frame_id"] for row in rows}, {matching["resolved"]["target"]["frame_id"]})
        self.assertEqual([int(row["particle_id"]) for row in rows], list(range(1, 82)))
        self.assertEqual([float(row["instrument_time_us"]) for row in rows], [300+pid/10 for pid in range(1, 82)])
        self.assertEqual([float(row["particle_birth_time_us"]) for row in rows], list(range(101, 182)))
        self.assertEqual(float(rows[0]["velocity_z_m_s"]), -38000)
        self.assertFalse(list(inputs.iterdir()))
        self.assertEqual((result / "mrtof_handoff/source_census.csv").read_bytes(),
                         (result / "ion_processor_exit/source_census.csv").read_bytes())

        self.assertEqual({row["source_component_id"] for row in rows}, {"processor_a"})
        self.assertEqual({row["target_component_id"] for row in rows}, {"analyzer_b"})
        exported = json.loads((result / "ion_processor_exit/component_exit_receipt.json").read_text())
        self.assertEqual(exported["source_project"], "dual_pressure_rectilinear_ion_processor")
        self.assertEqual(exported["producer_result"]["source_scientific_status"], "failed")
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.measured_component_source import materialize_measured_source
        materialized = materialize_measured_source(result / "mrtof_handoff/handoff_receipt.json", result / "measured")
        self.assertEqual(materialized["counts"], handoff["counts"])

        # Freeze the real production closure, then repeat the same complete
        # negative cohort in a process with no live repository import path.
        pwsh = shutil.which("pwsh")
        self.assertIsNotNone(pwsh)
        command = f"""
. '{REPO / 'integrations/runtime/dependencies.ps1'}'
$null=Freeze-ConsumerDependencies -RepoRoot '{REPO}' -ContractPath '{REPO / 'integrations/config/runtime_dependencies.json'}' -InputDir '{inputs}' -OwnerId instrument_assembly -ConsumerId accelerator_interface
"""
        frozen = subprocess.run([pwsh, "-NoProfile", "-Command", command], cwd=REPO,
            capture_output=True, encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(frozen.returncode, 0, frozen.stdout + frozen.stderr)
        authorities = fixture.root / "frozen_authorities.json"
        authorities.write_text(json.dumps({name: file_record(path) for name, path in sources.items()}), encoding="utf-8")
        program = """
import json,sys
from pathlib import Path
from integrations.workflows.accelerator_interface.prepare import _resolve_ip_matching
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_handoff import prepare_handoff
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.measured_component_source import materialize_measured_source
source,authorities,output=map(Path,sys.argv[1:])
output.mkdir()
matching=_resolve_ip_matching(source_run=source,results=output,inputs=output,frozen=json.loads(authorities.read_text()))
handoff=prepare_handoff(matching,matching["resolved"]["composition_plan"],output/"handoff")
receipt=materialize_measured_source(output/"handoff/handoff_receipt.json",output/"source")
assert receipt["counts"]=={"source":100,"transferred":81,"not_transferred":19}
assert matching["exported"]["producer_result"]["source_scientific_status"]=="failed"
assert handoff["connection"]["upstream"]["instance_id"]=="processor_a"
print("DETACHED_IP_MR_COMPLETE_SOURCE=PASS")
"""
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        completed = subprocess.run([sys.executable, "-B", "-s", "-c", program,
            str(fixture.run), str(authorities), str(fixture.root / "detached_source")],
            cwd=inputs / "runtime_snapshot", env=environment, capture_output=True,
            encoding="utf-8", errors="replace", timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("DETACHED_IP_MR_COMPLETE_SOURCE=PASS", completed.stdout)

    def test_public_prepare_clis_reject_foreign_destination_before_writing(self):
        from integrations.workflows.accelerator_interface import prepare as interface
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis import prepared_joint_trial as joint
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for module, mode, operation, arguments in (
                (interface, "accelerator_interface_preparation", "prepare_interface",
                 ["--provider", "orthogonal_accelerator", "--reference-mr-run", "missing"]),
                (joint, "prepared_joint", "prepare_trial",
                 ["prepare", "--prepared-run", "missing", "--contract", "missing"]),
            ):
                run = root / mode
                run.mkdir()
                config = run / "run_config.json"
                identity = dict(project="instrument_assembly", mode=mode, run_id=run.name)
                for invalid in (None, dict(identity, project=MR.name), dict(identity, mode="foreign"),
                                dict(identity, run_id="another-run")):
                    with self.subTest(mode=mode, invalid=invalid):
                        if invalid is not None:
                            config.write_text(json.dumps(invalid))
                        before = {item.name: item.read_bytes() for item in run.iterdir()}
                        with patch.object(module, operation) as materialize, patch.object(
                                sys, "argv", ["prepare", *arguments, "--run-directory", str(run)]):
                            with self.assertRaises((ValueError, FileNotFoundError)):
                                module.main()
                            materialize.assert_not_called()
                        self.assertEqual({item.name: item.read_bytes() for item in run.iterdir()}, before)
                config.write_text(json.dumps(identity))
                with patch.object(module, operation) as materialize, patch.object(
                        sys, "argv", ["prepare", *arguments, "--run-directory", str(run)]):
                    module.main()
                    materialize.assert_called_once()

    def test_declared_snapshot_prepares_oa_without_repository(self):
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = reference_fixture(root)
            run = root / "prepared"
            (run / "inputs").mkdir(parents=True)
            (run / "results").mkdir()
            (run / "run_config.json").write_text(json.dumps(dict(project="instrument_assembly",
                mode="accelerator_interface_preparation", run_id=run.name)))
            command = f"""
. '{REPO / 'integrations/runtime/dependencies.ps1'}'
$path='{REPO / 'integrations/config/runtime_dependencies.json'}'
$null=Freeze-ConsumerDependencies -RepoRoot '{REPO}' -ContractPath $path -InputDir '{run / 'inputs'}' -OwnerId instrument_assembly -ConsumerId accelerator_interface
"""
            completed = subprocess.run([pwsh, "-NoProfile", "-Command", command], cwd=REPO,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
            self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)
            snapshot = run / "inputs/runtime_snapshot"
            environment = dict(os.environ)
            environment.pop("PYTHONPATH", None)
            completed = subprocess.run([sys.executable, "-B", "-s", "-m", "integrations.workflows.accelerator_interface.prepare",
                "--provider", "orthogonal_accelerator", "--reference-mr-run", str(reference), "--run-directory", str(run)],
                cwd=snapshot, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)
            receipt = json.loads((run / "results/accelerator_interface_preparation.json").read_text())
            self.assertEqual(receipt["reference_requirements"]["frame_id"], "astral.xyz.v2")
            self.assertNotIn("joint_code_inventory", receipt["inputs"])
            self.assertFalse(list(snapshot.rglob("__pycache__")))
