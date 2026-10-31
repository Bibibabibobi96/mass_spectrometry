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



def _copy_path_consumer_repository(target):
    shutil.copytree(REPO / "common", target / "common", ignore=shutil.ignore_patterns("assets", "__pycache__"))
    shutil.copytree(REPO / "config", target / "config", ignore=shutil.ignore_patterns("__pycache__"))
    contract = json.loads((REPO / "integrations/config/runtime_dependencies.json").read_text(encoding="utf-8"))
    paths = {row["source_repo_path"] for group in contract["providers"] for row in group["files"]
             if "multipole_ip" in row["consumers"]}
    paths.update({"integrations/config/runtime_dependencies.json", "integrations/registry.json",
                  "integrations/runtime/dependencies.ps1"})
    for relative in paths:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / relative, destination)


class AcceleratorInterfaceTests(unittest.TestCase):
    def test_ip_recovery_compares_normalized_request_to_sealed_preparation(self):
        powershell = shutil.which("pwsh")
        if not powershell:
            self.skipTest("PowerShell 7 required")
        from integrations.workflows.multipole_ip.prepare import load_request
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = dict(path="producer/run_manifest.json", bytes=1, sha256="a" * 64)
            request = dict(schema_version=2, role="multipole_ip_preparation_request",
                source=dict(manifest=dict(record), run_id="source", project_id="rf_multipole_ion_optics", case_id="rf_on"),
                receiver=dict(manifest=dict(record), run_id="receiver", project_id="dual_pressure_rectilinear_ion_processor"),
                composition_plan=dict(record), species_id="ion", particle_weight=1)
            author = root / "author.json"
            author.write_text(json.dumps(request), encoding="utf-8")
            normalized = load_request(author)
            run = root / "preparation"
            (run / "inputs").mkdir(parents=True)
            frozen = run / "inputs/multipole_ip_request.json"
            frozen.write_text(json.dumps(normalized), encoding="utf-8")
            original = frozen.read_bytes()
            self.assertEqual(load_request(frozen), normalized)
            manifest = run / "run_manifest.json"
            manifest.write_text(json.dumps(dict(project="instrument_assembly", mode="multipole_ip_preparation",
                status="success", inputs=dict(request=file_record(frozen)), outputs=[])), encoding="utf-8")
            script = root / "compare.ps1"
            script.write_text(r'''param($Entry,$Repo,$Run,$Request,$Python)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Entry,[ref]$null,[ref]$null)
$definition=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Assert-MultipoleIpRecoveryRequest'},$true)
Invoke-Expression $definition.Extent.Text
function Invoke-RunToolRootContext {param($RepoRoot,$Operation) & $Operation}
$repoRoot=$Repo;$python=$Python
Assert-MultipoleIpRecoveryRequest -Run $Run -Request $Request
''', encoding="utf-8")
            command = [powershell, "-NoProfile", "-File", str(script),
                str(REPO / "integrations/workflows/accelerator_interface/execute.ps1"), str(REPO), str(run), str(author), sys.executable]
            equal = subprocess.run(command, cwd=REPO, capture_output=True, text=True, encoding="utf-8", check=False, timeout=30)
            self.assertEqual(equal.returncode, 0, equal.stdout + equal.stderr)
            request["particle_weight"] = 2
            author.write_text(json.dumps(request), encoding="utf-8")
            changed = subprocess.run(command, cwd=REPO, capture_output=True, text=True, encoding="utf-8", check=False, timeout=30)
            self.assertNotEqual(changed.returncode, 0)
            self.assertIn("unchanged request", changed.stderr)
            self.assertEqual(frozen.read_bytes(), original)


    def test_full_joint_finalization_routes_only_to_existing_flight_owner(self):
        powershell = shutil.which("pwsh")
        if not powershell:
            self.skipTest("PowerShell 7 required")
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "finalization.ps1"
            script.write_text(r'''param($Entry)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Entry,[ref]$null,[ref]$null)
$branch=$ast.Find({param($n)$n-is[Management.Automation.Language.IfStatementAst]-and$n.Clauses[0].Item1.Extent.Text-eq'$ResumeFinalization'},$true)
if($null-eq$branch){throw 'Missing original CLI recovery branch'}
$body=(@($branch.Clauses[0].Item2.Statements|Where-Object{$_-isnot[Management.Automation.Language.ReturnStatementAst]}|ForEach-Object{$_.Extent.Text})-join"`n")
$ResumeFinalization=$true;$FullJoint=$true;$RunId='existing-flight';$ResultPath='external-result';$PythonExe='python-runtime';$repoRoot='repository'
$PSBoundParameters.Clear()
foreach($key in @('ResumeFinalization','FullJoint','RunId','ResultPath')){$PSBoundParameters[$key]=(Get-Variable -Name $key -ValueOnly)}
$script:calls=0;$script:inject=$false
function Invoke-JointOwnerStage {
 param($Script,$Arguments)
 $script:calls++
 if($Script-ne(Join-Path $repoRoot 'integrations/workflows/prepared_joint/execute.ps1')-or
    -not$Arguments.ResumeFinalization-or$Arguments.RunId-ne$RunId-or$Arguments.ResultPath-ne$ResultPath-or
    $Arguments.PythonExe-ne$PythonExe-or$Arguments.Count-ne5){throw 'Recovery forwarded new scientific or native inputs'}
 if($script:inject){throw 'original owner finalization error'}
}
Invoke-Expression $body
if($script:calls-ne1){throw 'Recovery did not reach the original owner exactly once'}
$script:inject=$true;$caught=$false
try{Invoke-Expression $body}catch{$caught=$_.Exception.Message-eq'original owner finalization error'}
if(-not$caught){throw 'Recovery failure was swallowed'}
$PSBoundParameters.SimionExe='must-not-start';$caught=$false
try{Invoke-Expression $body}catch{$caught=$_.Exception.Message-like'*omit scientific*'}
if(-not$caught-or$script:calls-ne2){throw 'Recovery accepted a new solver option'}
'FULL_JOINT_FINALIZATION=PASS'
''', encoding="utf-8")
            result = subprocess.run([powershell, "-NoProfile", "-File", str(script),
                str(REPO / "integrations/workflows/accelerator_interface/execute.ps1")],
                cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("FULL_JOINT_FINALIZATION=PASS", result.stdout)

    def test_ip_negative_result_requires_complete_published_execution(self):
        powershell = shutil.which("pwsh")
        if not powershell:
            self.skipTest("PowerShell 7 required")
        from projects.dual_pressure_rectilinear_ion_processor.tests.test_component_exit import ComponentExitTests
        fixture = ComponentExitTests("test_complete_negative_native_exports_81_states_and_preserves_19_losses_and_failed_result")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture._negative_population()
        fixture.summary.update(execution_status="completed", data_validity="valid", science_status="not_passed",
                               analysis_exit_code=2, native_completed=True, diagnostics_complete=True)
        fixture._write_json("summary.json", fixture.summary)
        fixture._seal()
        script = fixture.root / "ip_status.ps1"
        script.write_text(r'''param($Entry,$Repo,$Run,$Python)
$ErrorActionPreference='Stop'
$ast=[Management.Automation.Language.Parser]::ParseFile($Entry,[ref]$null,[ref]$null)
$definition=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Assert-CompletedIpScientificFailure'},$true)
Invoke-Expression $definition.Extent.Text
function Invoke-RunToolRootContext {param($RepoRoot,$Operation) & $Operation}
$repoRoot=$Repo;$python=$Python
$summary=Assert-CompletedIpScientificFailure -Run $Run
if($summary.analysis_exit_code-ne2){throw 'wrong status'}
''', encoding="utf-8")
        command = [powershell, "-NoProfile", "-File", str(script),
                   str(REPO / "integrations/workflows/accelerator_interface/execute.ps1"), str(REPO), str(fixture.run), sys.executable]
        okay = subprocess.run(command, cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(okay.returncode, 0, okay.stdout + okay.stderr)
        fixture.summary["diagnostics_complete"] = False
        fixture._write_json("summary.json", fixture.summary)
        fixture._seal()
        bad = subprocess.run(command, cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("not a verified completed scientific negative", bad.stderr)

    def test_full_joint_uses_measured_mp_source_and_preserves_failure_policy(self):
        powershell = shutil.which("pwsh")
        if not powershell:
            self.skipTest("PowerShell 7 required")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "source_dispatch.ps1"
            script.write_text(r'''param($Entry,$Root,$Scenario)
$ErrorActionPreference='Stop'
$ast=[Management.Automation.Language.Parser]::ParseFile($Entry,[ref]$null,[ref]$null)
$definition=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-FullJoint'},$true)
Invoke-Expression $definition.Extent.Text
function New-AcceleratorInterfaceRunId {param($Provider) 'final'}
function Invoke-JointAnalysisPreflight {param($Design,$Source,$Contract)}
function Assert-JointFieldRunId {param($Id)}
function Write-FullJointFailure {param($Stage,$Flight,$Reason,$Elapsed,$OwnerRun)
  $script:failedStage=$Stage;$script:failedOwner=$OwnerRun
}
function Write-FullJointFlightResult {param($Workbench,$Flight,$Elapsed)}
function Get-JointDesignReceipt {param($Run) return @{status='prepared'}}
function Get-MultipoleIpPreparation {param($Run,$ConfigurationDirectory)
  if($ConfigurationDirectory-ne$Root){throw 'configuration was not forwarded'}
  return @{exit_count=$(if($Scenario-eq'zero'){0}else{1});mother_count=2;source=@{run_id='mp-original';case_id='rf_on'}}
}
function Assert-MultipoleIpRecoveryRequest {param($Run,$Request)
  $script:calls.Add('source_reuse')
  if($Scenario-eq'changed-request'){throw 'request identity differs'}
}
function Assert-CompletedIpScientificFailure {param($Run)
  if($Scenario-eq'unsafe'){throw 'incomplete diagnostics'}
  return @{status='failed';analysis_exit_code=2}
}
$script:calls=[Collections.Generic.List[string]]::new()
function Invoke-JointOwnerStage {param($Script,$Arguments)
  if($Arguments.ContainsKey('Request')){$script:calls.Add('source');return}
  if($Arguments.ContainsKey('InjectedSource')){
    $script:calls.Add('ip')
    if($Arguments.InjectedSource-ne(Join-Path $workspaceRoot 'artifacts/projects/instrument_assembly/runs/mp/results/multipole_ip/ip_injected_source.json')){throw 'source package differs'}
    if($Scenario-in@('resume','resume-failure')){
      if($Arguments.ContinuationPredecessorManifestPath-ne(Join-Path $Root 'parent/run_manifest.json')){throw 'IP parent not forwarded'}
      if($Scenario-eq'resume-failure'){throw 'IP_RECOVERY_SENTINEL'}
    }elseif($Arguments.ContainsKey('ContinuationPredecessorManifestPath')){throw 'IP recovery leaked to fresh run'}
    if($Scenario-in@('negative','unsafe','no-policy')){throw 'Analysis or required diagnostics incomplete; see frozen summary and logs'}
    if($Scenario-eq'seal-failure'){throw 'stopped payload sealing failed'}
    return
  }
  if($Arguments.ContainsKey('MatchingRequestPath')){
    $script:calls.Add('design')
    if($Arguments.IonProcessorRunPath-ne(Join-Path $workspaceRoot 'artifacts/projects/dual_pressure_rectilinear_ion_processor/runs/ip')){throw 'IP identity not forwarded'}
    $p=Join-Path $workspaceRoot 'artifacts/projects/instrument_assembly/runs/design'
    New-Item -ItemType Directory -Force (Join-Path $p 'results/joint_flight/assembly')|Out-Null
    Set-Content (Join-Path $p 'run_manifest.json') '{}'
    Set-Content (Join-Path $p 'results/accelerator_interface_preparation.json') '{}'
    Set-Content (Join-Path $p 'results/joint_flight/assembly/assembly_preparation.json') '{}'
    return
  }
  if($Arguments.ContainsKey('RequestPath')){
    $script:calls.Add('field');New-Item -ItemType Directory -Force $Arguments.RunDirectory|Out-Null
    Set-Content (Join-Path $Arguments.RunDirectory 'run_manifest.json') '{}';return
  }
  if($Arguments.ContainsKey('FinalizeJointWorkbench')){
    $script:calls.Add('binding');$p=Join-Path $workspaceRoot 'artifacts/projects/instrument_assembly/runs/final'
    New-Item -ItemType Directory -Force $p|Out-Null;Set-Content (Join-Path $p 'run_manifest.json') '{}';return
  }
  $script:calls.Add('flight')
}
$workspaceRoot=$Root;$artifactRoot=Join-Path $Root 'artifacts';$repoRoot=$Root;$AcceleratorProvider='dual_pressure_rectilinear_ion_processor'
$MultipoleIpRequestPath=Join-Path $Root 'request.json';Set-Content $MultipoleIpRequestPath '{}'
$MultipoleIpRunId='mp';$IonProcessorRunId='ip';$IonProcessorConfigurationDirectory=$Root;$IonProcessorFieldRunPath=''
$ContinueOnIpScientificFailure=$Scenario-in@('negative','unsafe','seal-failure');$IonProcessorRunPath=''
$MatchingRequestPath='matching';$ContractPath='observation';$ReferenceMrRunPath='reference'
$FieldRequestPath=Join-Path $Root 'field.json';Set-Content $FieldRequestPath '{"run_id":"field"}'
$RunId='design';$LuaExe='';$PythonExe='';$SimionExe='';$FinalizeJointWorkbench=$false
$PreparedInterfaceRunPath='';$JointFieldRunPath='';$PreparedJointWorkbenchRunPath='';$ContinuationPredecessorManifestPath='';$IonProcessorContinuationPredecessorManifestPath=''
if($Scenario-in@('resume','resume-failure','changed-request','field-conflict','prepared-conflict','old-design-conflict')){
  New-Item -ItemType Directory -Path (Join-Path $Root 'parent')|Out-Null
  $IonProcessorContinuationPredecessorManifestPath=Join-Path $Root 'parent/run_manifest.json'
  Set-Content $IonProcessorContinuationPredecessorManifestPath 'PARENT_UNCHANGED'
}
if($Scenario-eq'field-conflict'){$IonProcessorFieldRunPath='other-field'}
if($Scenario-eq'prepared-conflict'){$PreparedJointWorkbenchRunPath='ready'}
if($Scenario-eq'old-design-conflict'){$PreparedInterfaceRunPath='old-source-design'}
$failed=$false;$message='';try {Invoke-FullJoint} catch {$failed=$true;$message=$_.Exception.Message}
$expected=if($Scenario-eq'zero'){'source'}elseif($Scenario-in@('field-conflict','prepared-conflict','old-design-conflict')){''}elseif($Scenario-eq'changed-request'){'source_reuse'}elseif($Scenario-eq'resume-failure'){'source_reuse,ip'}elseif($Scenario-eq'resume'){'source_reuse,ip,design,field,binding,flight'}elseif($Scenario-in@('unsafe','no-policy','seal-failure')){'source,ip'}else{'source,ip,design,field,binding,flight'}
if(($script:calls -join ',')-ne$expected-or$failed-ne($Scenario-in@('unsafe','no-policy','seal-failure','resume-failure','changed-request','field-conflict','prepared-conflict','old-design-conflict'))){throw "unexpected sequence $script:calls failure=$failed error=$message"}
if($Scenario-eq'resume-failure'){
  if($message-ne'IP_RECOVERY_SENTINEL'){throw 'IP recovery error was replaced'}
  if($script:failedStage-ne'ion_processor_flight'-or$script:failedOwner-ne(Join-Path $Root 'artifacts/projects/dual_pressure_rectilinear_ion_processor/runs/ip')){throw 'IP recovery failure reported a different stage owner'}
}
if($IonProcessorContinuationPredecessorManifestPath-and(Get-Content $IonProcessorContinuationPredecessorManifestPath)-ne'PARENT_UNCHANGED'){throw 'Parent mutated'}
Write-Output 'MP_IP_JOINT=PASS'
''', encoding="utf-8")
            for scenario in ("normal", "zero", "negative", "unsafe", "no-policy", "seal-failure", "resume", "resume-failure", "changed-request", "field-conflict", "prepared-conflict", "old-design-conflict"):
                case = root / scenario
                case.mkdir()
                result = subprocess.run([powershell, "-NoProfile", "-File", str(script),
                    str(REPO / "integrations/workflows/accelerator_interface/execute.ps1"), str(case), scenario],
                    cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("MP_IP_JOINT=PASS", result.stdout)

    def test_multipole_source_validates_published_receiver_geometry(self):
        powershell = shutil.which("pwsh")
        if not powershell:
            self.skipTest("PowerShell 7 required")
        from integrations.tests.test_multipole_ip_prepare import MultipoleIPPreparationTests, write_json
        from common.contracts.rigid_transform import RigidTransform
        fixture = MultipoleIPPreparationTests("test_current_three_component_parent_derives_both_scopes_without_repositioning")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.execute()
        root = fixture.run
        model = json.loads((fixture.receiver / "inputs/resolved_model.json").read_text())
        configuration = fixture.root / "configuration"
        configuration.mkdir()
        for name in ("baseline", "numerics"):
            write_json(configuration / f"{name}.json", model[name])
        frame = model["baseline"]["clock"]["frame_id"]
        write_json(configuration / "coordinate_transform.json", RigidTransform.identity(frame).to_contract())
        result = root / "results/multipole_ip"
        write_json(root / "run_manifest.json", dict(project="instrument_assembly", mode="multipole_ip_preparation",
            status="success", inputs={}, outputs=[file_record(result / "preparation_receipt.json"),
                                                   file_record(result / "ip_injected_source.json")]))
        script = fixture.root / "validate.ps1"
        script.write_text(r'''param($Entry,$Repo,$Run,$Config,$Python)
$ErrorActionPreference='Stop'
$ast=[Management.Automation.Language.Parser]::ParseFile($Entry,[ref]$null,[ref]$null)
$definition=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Get-MultipoleIpPreparation'},$true)
Invoke-Expression $definition.Extent.Text
function Invoke-RunToolRootContext {param($RepoRoot,$Operation) & $Operation}
$repoRoot=$Repo;$python=$Python
$receipt=Get-MultipoleIpPreparation -Run $Run -ConfigurationDirectory $Config
if($receipt.exit_count-ne1){throw 'wrong receipt'}
''', encoding="utf-8")
        command = [powershell, "-NoProfile", "-File", str(script),
                   str(REPO / "integrations/workflows/accelerator_interface/execute.ps1"), str(REPO), str(root), str(configuration), sys.executable]
        result_ok = subprocess.run(command, cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result_ok.returncode, 0, result_ok.stdout + result_ok.stderr)
        model["baseline"]["native_geometry"]["domain_start_x_mm"] += 1
        write_json(configuration / "baseline.json", model["baseline"])
        result_bad = subprocess.run(command, cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertNotEqual(result_bad.returncode, 0)
        self.assertIn("receiver configuration", result_bad.stderr)

    def test_full_joint_field_request_reaches_real_provider_without_native_execution(self):
        powershell = shutil.which("pwsh")
        if not powershell:
            self.skipTest("PowerShell 7 required")
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_ion_processor_assembly import AssemblyTests
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ion_processor_assembly as assembly
        from integrations.workflows.accelerator_interface.geometry import prepare_ion_processor_assembly
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_handoff import resolve_ip_mr_connection

        fixture = AssemblyTests("test_seed_target_geometry_and_oa_removed")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        root = fixture.root
        reference = Path(fixture.request["field_assembly_reference"]["numerical_plan"]["path"])
        numerical_plan = json.loads(reference.read_text())
        numerical_plan.update(resource_budget={"cpu_cores": 8, "memory_bytes": 8589934592, "io_slots": 1},
                              resource_limits={"automatic_retry_count": 0})
        reference.write_text(json.dumps(numerical_plan), encoding="utf-8")
        fixture.request["field_assembly_reference"]["numerical_plan"] = file_record(reference)
        fixture.trajectory["simion"]["numerical_profiles"] = {
            "native_static_field": {"refine": {"convergence_v": 1e-5}},
            "grid_generation": {"spacing_quantum_mm": 0.01},
        }
        paths = [fixture.write(name + ".json", value) for name, value in
                 (("source", fixture.source), ("trajectory", fixture.trajectory), ("request", fixture.request))]
        assembly_dir = root / "results/joint_flight/assembly"
        assembly_dir.parent.mkdir(parents=True)
        with patch.object(assembly, "_analyzer_geometry_lines", return_value=["e(2) { box3d(1,2,3,4,5,6) }"]):
            prepare_ion_processor_assembly(fixture.source, fixture.trajectory, fixture.request,
                connection=resolve_ip_mr_connection(fixture.request["composition_plan"]),
                input_paths=paths, output_directory=assembly_dir)
        (root / "results/accelerator_interface_preparation.json").write_text(
            json.dumps({"status": "prepared", "inputs": {}}), encoding="utf-8")
        manifest = dict(status="success", project="instrument_assembly", mode="accelerator_interface_preparation",
                        inputs={}, outputs=[file_record(path) for path in root.rglob("*") if path.is_file()])
        (root / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        template = root / "field_template.json"
        template.write_text(json.dumps(dict(schema_version=1, role="mrtof_native_static_field_provider_request",
            run_id="20261029_120000__sim__simion__field-fixture", numerical_contract_path=str(root / "trajectory.json"),
            ion_processor_local_grid=dict(box_mm=[0, -227, -0.5, 4, -31.5, 14], pitch_mm=[0.05, 0.1, 0.05],
                                         active_box_mm=[[-3.5, 3.5], [-226.5, -32], [-0.25, 13.75]]),
            surface_allowance_bytes_per_level=1024)), encoding="utf-8")
        script = root / "real_field.ps1"
        script.write_text(r'''param($Entry,$Repo,$Root,$Template,$Python)
$ErrorActionPreference='Stop'
$ast=[Management.Automation.Language.Parser]::ParseFile($Entry,[ref]$null,[ref]$null)
foreach($name in @('Invoke-FullJoint','Write-FullJointFlightResult','Write-FullJointFailure','Get-JointSourceStart','Assert-JointFieldRunId')){
  $definition=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$name},$true)
  Invoke-Expression $definition.Extent.Text
}
function New-AcceleratorInterfaceRunId {param($Provider) 'final'}
function Invoke-JointAnalysisPreflight {param($Design,$Source,$Contract)}
function Invoke-RunToolRootContext {param($RepoRoot,$Operation) & $Operation}
function Get-JointDesignReceipt {param($Run) Get-Content (Join-Path $Run 'results/accelerator_interface_preparation.json') -Raw|ConvertFrom-Json -AsHashtable}
$script:ownerCalls=0
function Invoke-JointOwnerStage {
  param($Script,$Arguments)
  $script:ownerCalls++
  if($Arguments.ContainsKey('RequestPath')){
    if($Arguments.PythonExe-cne$Python){throw 'Provider interpreter differs from caller runtime'}
    $output=@(& $Script -RequestPath $Arguments.RequestPath -RunDirectory $Arguments.RunDirectory -PythonExe $Arguments.PythonExe)
    $plan=($output-join"`n")|ConvertFrom-Json
    if($plan.project-ne'parallel_mirror_dual_stripe_mr_tof'-or$plan.run_id-ne'20261029_120000__sim__simion__field-fixture'-or$plan.fly_authorized-ne$false){throw 'provider plan mismatch'}
    New-Item -ItemType Directory -Force $Arguments.RunDirectory|Out-Null
    Set-Content (Join-Path $Arguments.RunDirectory 'run_manifest.json') '{}'
  }elseif($Arguments.ContainsKey('FinalizeJointWorkbench')){
    $p=Join-Path $workspaceRoot 'artifacts/projects/instrument_assembly/runs/final';New-Item -ItemType Directory -Force $p|Out-Null;Set-Content (Join-Path $p 'run_manifest.json') '{}'
  }else{
    $p=Join-Path $workspaceRoot ('artifacts/projects/instrument_assembly/runs/'+$Arguments.RunId);New-Item -ItemType Directory -Force $p|Out-Null;Set-Content (Join-Path $p 'summary.json') '{"status":"success","diagnostics":"fixture","actual_native_batch_count":0,"reused_batch_count":1}'
  }
}
$repoRoot=$Repo;$workspaceRoot=$Root;$PreparedInterfaceRunPath=$Root;$JointFieldRunPath='';$python=$Python
$AcceleratorProvider='dual_pressure_rectilinear_ion_processor';$IonProcessorRunPath='source';$ReferenceMrRunPath='reference'
$MatchingRequestPath='';$FieldRequestPath=$Template;$ContractPath='observation';$RunId='';$LuaExe='';$PythonExe='';$SimionExe=''
$PreparedJointWorkbenchRunPath='';$ContinuationPredecessorManifestPath='';$FinalizeJointWorkbench=$false
Invoke-FullJoint
$before=$script:ownerCalls
$bad=Get-Content $Template -Raw|ConvertFrom-Json -AsHashtable;$bad.run_id='field-fixture';$bad|ConvertTo-Json -Depth 20|Set-Content $Template
$rejected=$false
try{Invoke-FullJoint}catch{$rejected=$true}
if(-not$rejected-or$script:ownerCalls-ne$before){throw 'invalid field run_id was not rejected before any owner stage'}
Write-Output 'REAL_FIELD_PROVIDER=PASS'
''', encoding="utf-8")
        result = subprocess.run([powershell, "-NoProfile", "-File", str(script),
            str(REPO / "integrations/workflows/accelerator_interface/execute.ps1"), str(REPO), str(root), str(template), sys.executable],
            cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("REAL_FIELD_PROVIDER=PASS", result.stdout)

    def test_zero_ip_exit_stops_before_matching(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def write(name, value):
                path = root / name
                path.write_text(json.dumps(value), encoding="utf-8")
                return {"path": str(path)}
            frozen = dict(
                accelerator_dependency=write("dependency.json", dict(api_version=2,
                    provider_project_id="dual_pressure_rectilinear_ion_processor", execution_scope="prepare_only_no_solver",
                    provider_callable="export_component_exit", provider_module="projects/dual_pressure_rectilinear_ion_processor/analysis/component_exit.py")),
                accelerator_request=write("request.json", {}), composition_plan=write("plan.json", {}),
            )
            zero = dict(role="ion_processor_component_exit_export", status="zero_exit",
                        counts=dict(source=3, transferred=0, not_transferred=3))
            connection = dict(upstream=dict(instance_id="ip"), downstream=dict(instance_id="mr"))
            with patch('integrations.workflows.accelerator_interface.prepare.derive_assembly_scope', return_value={}), \
                 patch('projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_handoff.resolve_ip_mr_connection', return_value=connection), \
                 patch('projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_handoff.resolve_matching_request', side_effect=AssertionError('must not match')), \
                 patch('projects.dual_pressure_rectilinear_ion_processor.analysis.component_exit.export_component_exit', return_value=zero):
                self.assertEqual(_resolve_ip_matching(source_run=root, results=root, inputs=root, frozen=frozen), zero)

    def test_full_joint_dispatches_actual_owner_sequence_and_stops_on_failure(self):
        powershell = shutil.which("pwsh")
        if not powershell:
            self.skipTest("PowerShell 7 required")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "dispatch.ps1"
            script.write_text(r'''param($Entry,$Root,$Fail,$SourceRoot,$Python)
$ErrorActionPreference='Stop'
$ast=[Management.Automation.Language.Parser]::ParseFile($Entry,[ref]$null,[ref]$null)
$definition=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-FullJoint'},$true)
Invoke-Expression $definition.Extent.Text
foreach($name in @('Write-FullJointFlightResult','Write-FullJointFailure','Get-JointSourceStart')){
  $definition=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$name},$true)
  Invoke-Expression $definition.Extent.Text
}
function New-AcceleratorInterfaceRunId { param($Provider) return 'final' }
function Invoke-JointAnalysisPreflight {param($Design,$Source,$Contract) if($Fail-eq'preflight'){throw 'clock mismatch'}}
function Assert-JointFieldRunId { param($Id) }
function Get-JointDesignReceipt { param($Run) return Get-Content (Join-Path $Run 'results/accelerator_interface_preparation.json') -Raw|ConvertFrom-Json -AsHashtable }
$script:calls=[Collections.Generic.List[string]]::new()
function Invoke-JointOwnerStage {
  param($Script,$Arguments)
  $name=if($Arguments.ContainsKey('MatchingRequestPath')){'design'}elseif($Arguments.ContainsKey('RequestPath')){'field'}elseif($Arguments.ContainsKey('FinalizeJointWorkbench')){'binding'}else{'flight'}
  $script:calls.Add($name)
  if($name-eq$Fail){throw 'injected stage failure'}
  if($name-eq'design'){
    $p=Join-Path $artifactRoot 'projects/instrument_assembly/runs/design'
    New-Item -ItemType Directory -Force (Join-Path $p 'results/joint_flight/assembly')|Out-Null
    Set-Content (Join-Path $p 'run_manifest.json') '{}'
    Set-Content (Join-Path $p 'results/joint_flight/assembly/assembly_preparation.json') '{}'
    Set-Content (Join-Path $p 'results/accelerator_interface_preparation.json') '{"status":"prepared"}'
  }elseif($name-eq'field'){
    $r=Get-Content $Arguments.RequestPath -Raw|ConvertFrom-Json
    if($r.replacement_assembly_manifest-ne(Join-Path $artifactRoot 'projects/instrument_assembly/runs/design/run_manifest.json')){throw 'design binding differs'}
    if($r.ion_processor_local_grid.pitch_mm[0]-ne0.05){throw 'field inputs changed'}
    New-Item -ItemType Directory -Force $Arguments.RunDirectory|Out-Null
    Set-Content (Join-Path $Arguments.RunDirectory 'run_manifest.json') '{}'
  }elseif($name-eq'binding'){
    $p=Join-Path $artifactRoot 'projects/instrument_assembly/runs/final'
    New-Item -ItemType Directory -Force $p|Out-Null
    Set-Content (Join-Path $p 'run_manifest.json') '{}'
  }elseif($name-eq'flight'){
    $p=Join-Path $artifactRoot ('projects/instrument_assembly/runs/'+$Arguments.RunId)
    $d=Join-Path $p 'results/diagnostics';New-Item -ItemType Directory -Force $d|Out-Null
    @{status='success';diagnostics=$d;actual_native_batch_count=0;reused_batch_count=2}|ConvertTo-Json|Set-Content (Join-Path $p 'summary.json')
    Set-Content (Join-Path $d 'diagnostics_receipt.json') '{"status":"complete_recorded_diagnostics","counts":{"detected":2},"detector_peak":{"fwhm_us":0.1}}'
  }
}
. (Join-Path $SourceRoot 'common/paths/workspace_paths.ps1')
$context=Resolve-WorkspacePaths -SourceRoot $SourceRoot -ArtifactRoot (Join-Path $Root 'selected-store') -Python $Python
$MultipoleIpRequestPath='';$MultipoleIpRunId='';$IonProcessorRunId='';$IonProcessorConfigurationDirectory='';$IonProcessorFieldRunPath='';$ContinueOnIpScientificFailure=$false;$ResultPath=''
$artifactRoot=[string]$context.artifact_root;$repoRoot=$Root;$AcceleratorProvider='dual_pressure_rectilinear_ion_processor'
$IonProcessorRunPath='source';$MatchingRequestPath='matching';$ContractPath='observation';$ReferenceMrRunPath='reference'
$FieldRequestPath=Join-Path $Root 'field.json';$RunId='design';$LuaExe='';$PythonExe='';$SimionExe=''
$FinalizeJointWorkbench=$false;$PreparedInterfaceRunPath='';$JointFieldRunPath=''
$PreparedJointWorkbenchRunPath='';$ContinuationPredecessorManifestPath=''
Set-Content $FieldRequestPath '{"run_id":"field","ion_processor_local_grid":{"pitch_mm":[0.05,0.1,0.05]}}'
try { Invoke-FullJoint } catch { if(-not$Fail){throw} }
$expected=if($Fail-eq'preflight'){@('design')}elseif($Fail){@('design','field')}else{@('design','field','binding','flight')}
if(($script:calls -join ',')-ne($expected -join ',')){throw "wrong sequence: $script:calls"}
if(-not$Fail){
  $script:calls.Clear();$PreparedInterfaceRunPath=Join-Path $artifactRoot 'projects/instrument_assembly/runs/design'
  $JointFieldRunPath=Join-Path $artifactRoot 'projects/parallel_mirror_dual_stripe_mr_tof/runs/field'
  $MatchingRequestPath='';$FieldRequestPath=''
  Invoke-FullJoint
  if(($script:calls -join ',')-ne'binding,flight'){throw "reuse ran extra stages: $script:calls"}
  $script:calls.Clear();$PreparedJointWorkbenchRunPath=Join-Path $artifactRoot 'projects/instrument_assembly/runs/final'
  $PreparedInterfaceRunPath='';$JointFieldRunPath='';$ContinuationPredecessorManifestPath='predecessor'
  $exit=Join-Path $PreparedJointWorkbenchRunPath 'results/ion_processor_exit';$binding=Join-Path $PreparedJointWorkbenchRunPath 'results/joint_workbench'
  New-Item -ItemType Directory -Force $exit,$binding|Out-Null
  Set-Content (Join-Path $exit 'component_exit_receipt.json') '{"inputs":{"inputs/injected_source.json":{}}}'
  Set-Content (Join-Path $binding 'static_field_binding.json') '{"parent":{"grid":{"origin_mm":[0,1,2],"pitch_mm":[1,1,1],"dimensions":[2,2,2]}},"refinement_windows":[]}'
  $direct=@(Invoke-FullJoint)
  if(($script:calls -join ',')-ne'flight'){throw "workbench reuse ran extra stages: $script:calls"}
  if(-not($direct -match 'DATA_VALIDITY=recorded_diagnostics_complete SCIENCE=not_qualified SOURCE=upstream_injected_population.*NATIVE_BATCHES=0 REUSED_BATCHES=2')){throw 'execution, source, scientific status or reuse not reported'}
  if(-not($direct -match 'fwhm_us.*0.1')-or-not($direct -match 'origin_mm')){throw 'peak or field scope not reported'}
  $failed=Join-Path $Root 'failed';New-Item -ItemType Directory -Force $failed|Out-Null
  Set-Content (Join-Path $failed 'summary.json') '{"status":"failed","failure_stage":"automatic_joint_diagnostics","reason":"real analysis failure"}'
  $failure=@(Write-FullJointFailure -Stage flight_and_analysis -Flight $failed -Reason generic -Elapsed 1 2>&1)
  if(-not($failure -match 'STAGE=automatic_joint_diagnostics.*RECOVERY=use_prepared_joint_analysis_without_fly.*real analysis failure')){throw 'failed analysis did not expose actual stage and recovery'}
  $script:calls.Clear();$PreparedJointWorkbenchRunPath='';$PreparedInterfaceRunPath=Join-Path $artifactRoot 'projects/instrument_assembly/runs/design'
  $JointFieldRunPath='';$FieldRequestPath=Join-Path $Root 'field.json'
  Set-Content (Join-Path $PreparedInterfaceRunPath 'results/accelerator_interface_preparation.json') '{"status":"zero_exit","source_exit":{"inputs":{"inputs/injected_source.json":{}},"counts":{"source":3,"not_transferred":3}}}'
  $zero=@(Invoke-FullJoint)
  if($script:calls.Count-ne0-or-not($zero -match 'FULL_JOINT=ZERO_EXIT.*SOURCE=upstream_injected_population.*MOTHER=3.*FLY=False')){throw 'zero exit source or stopping differs'}
}
Write-Output 'FULL_JOINT_DISPATCH=PASS'
''', encoding="utf-8")
            for failure in ("", "field", "preflight"):
                case = root / (failure or "success")
                case.mkdir()
                result = subprocess.run([powershell, "-NoProfile", "-File", str(script),
                    str(REPO / "integrations/workflows/accelerator_interface/execute.ps1"), str(case), failure, str(REPO), sys.executable],
                    cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("FULL_JOINT_DISPATCH=PASS", result.stdout)

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
$receipt=@{status='prepared'}
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
if($commands.Count-eq0){throw 'expected Python calls in accelerator interface owner'}
foreach($call in $commands){if($call.CommandElements[1].Extent.Text-ne'-B'){throw 'snapshot call permits bytecode'}}
$python=$Python;$arguments=@('-c','import sys; assert sys.dont_write_bytecode; print("SNAPSHOT_BYTECODE_DISABLED=PASS")')
$preparation=@($commands|Where-Object{$_.Extent.Text.Contains('@arguments')})
if($preparation.Count-ne1){throw 'actual preparation command missing'}
. ([scriptblock]::Create($preparation[0].Extent.Text))
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
        self._check_ip_design_preparation(upstream=False)

    def test_ip_design_accepts_admitted_upstream_source_without_resampling(self):
        self._check_ip_design_preparation(upstream=True)

    def _check_ip_design_preparation(self, *, upstream):
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
        if upstream:
            # This is the resolved-model representation written by IP prepare
            # for an already admitted population, not an ion-release spec.
            admitted_source = dict(frame_id=configs['baseline']['clock']['frame_id'],
                particle_count=100, mother_particle_count=120,
                species=dict(mass_amu=524.0, charge_state=1))
            admission = dict(clock_epoch_id='instrument_epoch',
                particle_ids=list(range(1,101)), mother_particle_count=120)
            matching['source_model']['source'] = copy.deepcopy(admitted_source)
            matching['source_model']['source_profile'] = 'upstream'
            matching['source_model']['injected_source'] = copy.deepcopy(admission)
            configs['source'] = copy.deepcopy(admitted_source)
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
                         {'assembly','joint_preparation_receipt.json'})
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


    def test_full_joint_cli_keeps_resolved_roots_scoped_for_actual_child(self):
        if not shutil.which("pwsh"):
            self.skipTest("PowerShell 7 required")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            _copy_path_consumer_repository(repo)
            entry = repo / "integrations/workflows/accelerator_interface/execute.ps1"
            entry.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / "integrations/workflows/accelerator_interface/execute.ps1", entry)
            child = repo / "integrations/workflows/prepared_joint/execute.ps1"
            child.parent.mkdir(parents=True)
            child.write_text(r"""param($PreparedJointWorkbenchRunPath,$ContractPath,$RunId,$RepoRoot,$PythonExe)
$ErrorActionPreference='Stop'
$run=Join-Path $env:MASS_SPECTROMETRY_ARTIFACT_ROOT "projects/instrument_assembly/runs/$RunId"
if($PreparedJointWorkbenchRunPath-cne$env:TEST_PARENT){throw 'explicit cross-root parent changed'}
@{artifact_root=$env:MASS_SPECTROMETRY_ARTIFACT_ROOT;execution_root=$env:MASS_SPECTROMETRY_EXECUTION_ROOT;host_resource_state_path=$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH;parent=$PreparedJointWorkbenchRunPath}|ConvertTo-Json|Set-Content $env:TEST_OBSERVED
New-Item -ItemType Directory -Force $run|Out-Null
@{status='success';diagnostics=$run;actual_native_batch_count=0;reused_batch_count=1}|ConvertTo-Json|Set-Content (Join-Path $run 'summary.json')
$env:MASS_SPECTROMETRY_ARTIFACT_ROOT='CHILD_DRIFT'
$env:MASS_SPECTROMETRY_EXECUTION_ROOT='CHILD_DRIFT'
$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH='CHILD_DRIFT'
if($env:TEST_FAIL-eq'1'){throw 'CHILD_ROOT_FAILURE'}
""", encoding="utf-8")
            parent = root / "other-owner/runs/parent"
            parent.mkdir(parents=True)
            marker = parent / "run_manifest.json"
            marker.write_bytes(b'EXPLICIT_PARENT_UNCHANGED')
            original = marker.read_bytes()
            driver = root / "scope.ps1"
            driver.write_text(r"""param($Entry,$Repo,$Parent,$Python,$Expected,$Fail)
$ErrorActionPreference='Stop'
$before=@{};foreach($key in @('MASS_SPECTROMETRY_ARTIFACT_ROOT','MASS_SPECTROMETRY_EXECUTION_ROOT','MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH')){$before[$key]=[Environment]::GetEnvironmentVariable($key)}
$failed=$false
try {& $Entry -FullJoint -PreparedJointWorkbenchRunPath $Parent -ContractPath observation -RunId 20261031_180000__sim__simion__root-test -PythonExe $Python -RepoRoot $Repo}
catch {if($Fail-ne'1'-or$_.Exception.Message-notmatch'CHILD_ROOT_FAILURE'){throw};$failed=$true}
if($failed-ne($Fail-eq'1')){throw 'child failure propagation differs'}
foreach($key in $before.Keys){if([Environment]::GetEnvironmentVariable($key)-cne$before[$key]){throw "environment leaked: $key"}}
""", encoding="utf-8")
            host = os.environ.get("MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH", str(root / "host.sqlite3"))
            for failure in ("0", "1"):
                selected = root / ("selected" + failure)
                observed = root / ("observed" + failure + ".json")
                environment = dict(os.environ, MASS_SPECTROMETRY_ARTIFACT_ROOT=str(selected),
                    MASS_SPECTROMETRY_EXECUTION_ROOT=str(root / "execution"),
                    MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=host, TEST_PARENT=str(parent),
                    TEST_OBSERVED=str(observed), TEST_FAIL=failure)
                result = subprocess.run(["pwsh", "-NoProfile", "-File", str(driver), str(entry), str(repo),
                    str(parent), sys.executable, str(selected), failure], capture_output=True,
                    text=True, encoding="utf-8", env=environment, cwd=root, timeout=120)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                actual = json.loads(observed.read_text(encoding="utf-8-sig"))
                self.assertEqual(actual, dict(artifact_root=str(selected.resolve()),
                    execution_root=str((root / "execution").resolve()), host_resource_state_path=str(Path(host).resolve()), parent=str(parent)))
                self.assertTrue((selected / "projects/instrument_assembly/runs/20261031_180000__sim__simion__root-test/summary.json").is_file())
                self.assertEqual(marker.read_bytes(), original)
            self.assertFalse((repo.parent / "artifacts").exists())


    def test_multipole_cli_uses_nondefault_root_and_preserves_parent_records(self):
        if not shutil.which("pwsh"):
            self.skipTest("PowerShell 7 required")
        from integrations.tests.test_multipole_ip_prepare import MultipoleIPPreparationTests, write_json
        fixture = MultipoleIPPreparationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.write_parent()
        write_json(fixture.request_path, fixture.request)
        repo = fixture.root / "repo"
        _copy_path_consumer_repository(repo)
        entry = repo / "integrations/workflows/multipole_ip/execute.ps1"
        entry.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / "integrations/workflows/multipole_ip/execute.ps1", entry)
        # The real package, input freezer and scientific Python prepare execute.
        # Capacity admission is the explicit inert boundary of this consumer test;
        # public SourceReferences owns the cross-root validation/fault matrix.
        support = repo / "common/contracts/run_artifact_support.ps1"
        support.write_text(support.read_text(encoding="utf-8") + r"""
function Enter-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$ArtifactRoot,$RunDirectory,$CommittedNewBytes,$ProtectedPaths,$SourceReferences,$Owner)
 @{artifact_root=$ArtifactRoot;run=$RunDirectory;protected=@($ProtectedPaths);refs=@($SourceReferences)}|ConvertTo-Json -Depth 30|Set-Content $env:TEST_CAPACITY_CAPTURE
 return [pscustomobject]@{artifact_root=$ArtifactRoot}
}
function Update-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session,$RemainingCommittedNewBytes) return @{session=$Session}}
function Exit-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session)}
function Apply-RunArtifactRetention {param($Python,$RepoRoot,$RunConfig) throw 'AFTER_REAL_MP_PREPARE'}
function Complete-FailedRun {param($Python,$RepoRoot,$RunConfig,$Summary,$SummaryRole,$Reason,$Software,$Status,$FailureStage)
 if($Reason-notmatch'AFTER_REAL_MP_PREPARE'){throw "UNEXPECTED_PREPARE_FAILURE:$Reason"}
}
""", encoding="utf-8")
        selected = fixture.root / "selected-store"
        from common.contracts.capacity_ledger import initialize_capacity_ledger
        selected.mkdir()
        initialize_capacity_ledger(selected, objects=[])
        capture = fixture.root / "capacity.json"
        parents = {str(path): path.read_bytes() for base in (fixture.source, fixture.receiver) for path in base.rglob("*") if path.is_file()}
        host = os.environ.get("MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH", str(fixture.root / "host.sqlite3"))
        environment = dict(os.environ, MASS_SPECTROMETRY_ARTIFACT_ROOT=str(selected),
            MASS_SPECTROMETRY_EXECUTION_ROOT=str(fixture.root / "execution"),
            MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=host, SIMULATION_PYTHON_EXE=sys.executable, TEST_CAPACITY_CAPTURE=str(capture))
        result = subprocess.run(["pwsh", "-NoProfile", "-File", str(entry), "-Request", str(fixture.request_path),
            "-RunId", "20261031_180100__analysis__python__mp-root-test", "-PythonExe", sys.executable,
            "-RepoRoot", str(repo)], env=environment, cwd=fixture.root, capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("AFTER_REAL_MP_PREPARE", result.stderr)
        run = selected / "projects/instrument_assembly/runs/20261031_180100__analysis__python__mp-root-test"
        self.assertTrue((run / "results/multipole_ip/preparation_receipt.json").is_file(), result.stdout + result.stderr)
        receipt = json.loads((run / "results/multipole_ip/preparation_receipt.json").read_text(encoding="utf-8"))
        self.assertEqual((receipt["mother_count"], receipt["exit_count"]), (2, 1))
        config = json.loads((run / "run_config.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(config["paths"], dict(source_root=str(repo.resolve()), artifact_root=str(selected.resolve()),
            execution_root=str((fixture.root / "execution").resolve()), host_resource_state_path=str(Path(host).resolve())))
        actual = json.loads(capture.read_text(encoding="utf-8-sig"))
        self.assertEqual(actual["artifact_root"], str(selected))
        self.assertEqual(actual["protected"], [str(run)])
        self.assertEqual([row["manifest_record"] for row in actual["refs"]],
                         [fixture.request["source"]["manifest"], fixture.request["receiver"]["manifest"]])
        self.assertEqual({str(path): path.read_bytes() for base in (fixture.source, fixture.receiver) for path in base.rglob("*") if path.is_file()}, parents)
        self.assertFalse((repo.parent / "artifacts").exists())


    def test_interface_capacity_transports_explicit_parent_manifest_authority(self):
        if not shutil.which("pwsh"):
            self.skipTest("PowerShell 7 required")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parents = [root / "other-root" / name for name in ("reference", "ip", "design", "field")]
            for parent in parents:
                parent.mkdir(parents=True)
                (parent / "run_manifest.json").write_text('{"status":"success"}', encoding="utf-8")
            original = {str(parent): (parent / "run_manifest.json").read_bytes() for parent in parents}
            driver = root / "capacity.ps1"
            driver.write_text(r"""param($Repo,$Entry,$Python,$Root)
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
$repoRoot=$Repo;$artifactRoot=Join-Path $Root 'selected';$package=@{artifact_run_dir=(Join-Path $artifactRoot 'projects/instrument_assembly/runs/new')};$RunId='new';$python=$Python
$reference,$sourceRun,$designRun,$fieldRun=@('reference','ip','design','field')|ForEach-Object{Join-Path $Root "other-root/$_"}
$pathEnvironment=@{MASS_SPECTROMETRY_ARTIFACT_ROOT=$artifactRoot};$script:admissions=0
function Enter-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$ArtifactRoot,$RunDirectory,$CommittedNewBytes,$ProtectedPaths,$SourceReferences,$Owner)
 if($ProtectedPaths.Count-ne1-or$ProtectedPaths[0]-cne$RunDirectory){throw 'foreign parent entered child protection paths'}
 if($SourceReferences.Count-ne4){throw "source reference count differs: $($SourceReferences.Count)"}
 foreach($ref in $SourceReferences){
  if($ref.manifest_record-isnot[Collections.IDictionary]-or-not$ref.manifest_record.exists-or$ref.protected_paths.Count-ne1){throw 'SOURCE_MANIFEST_MISSING'}
  if($ref.manifest_record.path-cne(Join-Path $ref.protected_paths[0] 'run_manifest.json')){throw 'parent identity differs'}
 }
 $script:admissions++
 $SourceReferences|ConvertTo-Json -Depth 20|Set-Content (Join-Path $Root 'references.json')
}
$ast=[Management.Automation.Language.Parser]::ParseFile($Entry,[ref]$null,[ref]$null)
$body=$ast.Find({param($n)$n-is[Management.Automation.Language.TryStatementAst]-and$n.Body.Extent.Text-match'\$parents='},$true).Body
$selected=@($body.Statements|Where-Object{$_.Extent.Text-match'^\$(parents|sourceRecords|sourceReferences)=|^\$capacitySession=Enter-'})
if($selected.Count-ne4){throw 'actual source admission boundary not found'}
foreach($statement in $selected){Invoke-Expression $statement.Extent.Text}
if($script:admissions-ne1){throw 'actual admission was not reached'}
Remove-Item (Join-Path $fieldRun 'run_manifest.json')
$failed=$false;try {foreach($statement in $selected){Invoke-Expression $statement.Extent.Text}}catch{if($_.Exception.Message-notmatch'SOURCE_MANIFEST_MISSING'){throw};$failed=$true}
if(-not$failed-or$script:admissions-ne1){throw 'missing parent did not reject before admission'}
""", encoding="utf-8")
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(driver), str(REPO),
                str(REPO / "integrations/workflows/accelerator_interface/execute.ps1"), sys.executable, str(root)],
                cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            references = json.loads((root / "references.json").read_text(encoding="utf-8-sig"))
            self.assertEqual([row["manifest_record"] for row in references], [file_record(parent / "run_manifest.json") for parent in parents[:3]] +
                             [dict(file_record(parents[0] / "run_manifest.json"), path=str(parents[3] / "run_manifest.json"))])
            self.assertEqual({str(parent): (parent / "run_manifest.json").read_bytes() for parent in parents[:3]},
                             {str(parent): original[str(parent)] for parent in parents[:3]})
