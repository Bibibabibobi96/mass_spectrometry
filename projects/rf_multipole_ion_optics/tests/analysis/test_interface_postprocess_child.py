"""Real existing-CLI analysis successor with synthetic scientific inputs only."""
import csv
import json
import math
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[2]
CLI = PROJECT / "workflows/interface_readiness/run_comsol.ps1"


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell7 required")
class InterfacePostprocessChildTests(unittest.TestCase):
    def test_terminal_and_checkpoint_references_use_existing_public_admission(self):
        repo = PROJECT.parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "run_manifest.json"
            manifest.write_text('{"status":"success"}', encoding="utf-8")
            stopped = root / "stopped.json"
            stopped.write_text('{"fixture":"explicit stopped receipt"}', encoding="utf-8")
            command = r"""
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path REPO 'common/contracts/run_artifact_workflow.ps1')
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile(ENTRY,[ref]$t,[ref]$e)
$definition=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-InterfacePostprocessChild'},$true)
. ([scriptblock]::Create($definition.Extent.Text))
$metadata=Get-Command ENTRY
if($metadata.Parameters['StoppedReceiptPath'].ParameterSets['Analyze'].IsMandatory){throw 'terminal sources incorrectly require checkpoint receipt'}
function New-RunPackage {throw 'admission did not precede new package'}
function Enter-ArtifactWorkflowCapacitySession {
 param($Python,$RepoRoot,$ArtifactRoot,$RunDirectory,$CommittedNewBytes,$ProtectedPaths,$SourceReferences,$Owner)
 if($SourceReferences.Count-ne1-or$SourceReferences[0].manifest_record.path-cne MANIFEST){throw 'actual parent reference was not forwarded'}
 if($script:expectStopped){
  if($SourceReferences[0].stopped_receipt_record.path-cne STOPPED){throw 'explicit checkpoint receipt was not forwarded'}
 }elseif($SourceReferences[0].Contains('stopped_receipt_record')){throw 'terminal source received an invented stopped receipt'}
 throw 'EXPECTED_PUBLIC_ADMISSION_BOUNDARY'
}
$ParentManifestPath=MANIFEST;$RunId='fixture';$python=PYTHON;$repoRoot=REPO;$artifactRoot=ROOT;$CommittedNewBytes=1024
$pathContext=@{artifact_root=ROOT;execution_root=ROOT;host_resource_state_path=(Join-Path ROOT 'host.sqlite3')}
foreach($script:expectStopped in @($false,$true)){
 $StoppedReceiptPath=if($script:expectStopped){STOPPED}else{''}
 $caught=$false;try{Invoke-InterfacePostprocessChild}catch{if($_.Exception.Message-cne'EXPECTED_PUBLIC_ADMISSION_BOUNDARY'){throw};$caught=$true}
 if(-not$caught){throw 'existing public source admission bypassed'}
}
"""
            for key, value in {"REPO": repo, "ENTRY": CLI, "MANIFEST": manifest, "STOPPED": stopped,
                               "PYTHON": sys.executable, "ROOT": root}.items():
                command = re.sub(r"\b" + key + r"\b", lambda _: literal(value), command)
            result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                                    cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_frozen_analysis_consumes_parent_offset_and_actual_module_origins(self):
        from common.contracts.particle_state import PARTICLE_STATE_COLUMNS, ion11_sources

        repo = PROJECT.parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = r"""
$ErrorActionPreference='Stop'
$python=PYTHON;$repo=REPO
. (Join-Path $repo 'common/contracts/run_artifact_support.ps1')
. (Join-Path $repo 'projects/rf_multipole_ion_optics/runtime/frozen_python_package.ps1')
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile(ENTRY,[ref]$t,[ref]$e)
$list=$ast.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq'$frozenPythonRelativePaths'},$true)
Invoke-Expression $list.Extent.Text
$package=New-FrozenPythonPackage -SourceRoot $repo -CodeRoot (Join-Path ROOT 'frozen') -RelativePaths $frozenPythonRelativePaths
$function=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-InterfacePostprocessChild'},$true)
$code=$function.FindAll({param($n)$n-is[Management.Automation.Language.StringConstantExpressionAst]-and$n.Value.StartsWith('import importlib.util,json,pathlib,runpy,sys')},$true)
if($code.Count-ne1){throw 'actual project analysis Python body missing'}
@{code=$code[0].Value;root=$package.code_root}|ConvertTo-Json -Compress
"""
            for key, value in {"PYTHON": sys.executable, "REPO": repo, "ENTRY": CLI, "ROOT": root}.items():
                command = re.sub(r"\b" + key + r"\b", lambda _: literal(value), command)
            result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                                    cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            execution = json.loads(result.stdout)
            ions = root / "ions.ion"
            ions.write_text("0.25,100,1,0,0,0,0,0,2,1,3\n", encoding="utf-8")
            rows = []
            for event in ("source", "terminal"):
                row = {key: 0 for key in PARTICLE_STATE_COLUMNS}
                row.update(ion11_sources(ions, axial_offset_mm=7.)[1])
                row.update(particle_id=1, event=event, status="alive" if event == "source" else "transmitted",
                           terminal_reason="none" if event == "source" else "acceptance_surface")
                if event == "terminal":
                    row.update(time_us=1.25, elapsed_time_us=1.)
                row["rf_phase_rad"] = (2 * math.pi * 1.1e6 * row["time_us"] * 1e-6) % (2 * math.pi)
                rows.append(row)
            state = root / "state.csv"
            with state.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=PARTICLE_STATE_COLUMNS)
                writer.writeheader()
                writer.writerows(rows)
            metadata = root / "raw.json"
            metadata.write_text(json.dumps(dict(role="rf_quadrupole_comsol_raw_solver_metadata", source_ids=[1],
                                                native_order=[1], source_birth_s=[.25e-6], source_weights=[1.],
                                                source_initial_position_mm=[[0., 0., 7.]],
                                                source_initial_velocity_m_s=[[0., 0., 1.]],
                                                source_axial_offset_mm=7.)), encoding="utf-8")
            contract = root / "contract.json"
            shutil.copyfile(PROJECT / "variants/quadrupole/config/interface_contract.json", contract)
            environment = os.environ.copy()
            environment.update(PYTHONPATH=execution["root"], PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1")
            result = subprocess.run([sys.executable, "-B", "-c", execution["code"], execution["root"],
                                     str(metadata), str(state), str(root / "metrics.json"), str(ions), str(contract),
                                     "1100000", "0", str(root / "report.json"), str(root / "origins.json")],
                                    cwd=execution["root"], env=environment, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads((root / "report.json").read_text())["status"], "PASS")
            self.assertTrue(all(Path(path).is_relative_to(execution["root"]) for path in
                                json.loads((root / "origins.json").read_text()).values()))

    def test_unknown_analysis_writer_does_not_release_the_existing_guard(self):
        # Only the project-to-public-owner boundary is substituted here; the
        # common owner unknown-writer matrix remains its single real authority.
        command = r"""
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile(ENTRY,[ref]$t,[ref]$e)
$definition=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Complete-InterfaceOwner'},$true)
. ([scriptblock]::Create($definition.Extent.Text))
function Exit-HostResourceStage {throw 'UNKNOWN_ANALYSIS_RELEASED'}
function Complete-RunArtifactPowerShellOwner {
 param($Context,$Status,$Summary,$OutputPaths,$WriterCompletion,$WritersStopped,$OriginalFailure,$ResourceUsagePaths)
 if($WritersStopped-or$WriterCompletion.operations.Count-or$Summary.execution_status-cne'writer_completion_unknown'){throw 'unknown completion was promoted'}
 if($OriginalFailure.Exception.Message-cne'primary parse observer error'){throw 'unknown writer masked original failure'}
 throw 'UNKNOWN_ANALYSIS_RETAINED'
}
$ownerContext=@{run_directory='unused';result_path='unused'}
$ownerState=@{calls=[Collections.Generic.List[object]]::new();writer_unknown=$true;finalization_started=$false;prepare_seconds=0.;timer=[Diagnostics.Stopwatch]::StartNew();analysis_operations=@();analysis_usage=@()}
try{throw 'primary parse observer error'}catch{$failure=$_}
$caught=$false;try{Complete-InterfaceOwner -Status failed -Summary @{scientific_result='NOT_EVALUATED'} -Failure $failure}catch{if($_.Exception.Message-cne'UNKNOWN_ANALYSIS_RETAINED'){throw};$caught=$true}
if(-not$caught){throw 'unknown writer failed to reach retaining owner boundary'}
""".replace('ENTRY', literal(CLI))
        result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                                cwd=PROJECT.parents[1], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_actual_cli_reuses_checkpoint_exports_and_resumes_without_compute(self):
        from common.contracts.capacity_ledger import initialize_capacity_ledger
        from common.contracts.particle_state import PARTICLE_STATE_COLUMNS, ion11_sources

        repo = PROJECT.parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            facade = root / "repo"
            # Private public-policy fixture, copied from the tested source tree.
            # No shared scheduler/ledger or production policy is modified.
            for area in ("common", "projects/rf_multipole_ion_optics"):
                for file in (repo / area).rglob("*"):
                    if (file.is_file() and file.suffix in {".py", ".ps1", ".json"}
                            and not any(part in {"tests", "assets", "__pycache__"} for part in file.relative_to(repo).parts)):
                        target = facade / file.relative_to(repo)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(file, target)
            target = facade / "projects/rf_multipole_ion_optics/workflows/interface_readiness/run_comsol.ps1"
            shutil.copyfile(CLI, target)
            registry = json.loads((repo / "config/project_registry.json").read_text(encoding="utf-8"))
            registry_path = facade / "config/project_registry.json"
            registry_path.parent.mkdir(parents=True)
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            project = next(p for p in registry["projects"] if p["project_id"] == "rf_multipole_ion_optics")
            for descriptor in project["retired_project_descriptors"]:
                destination = facade / descriptor["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(repo / descriptor["path"], destination)
            policy = facade / "common/contracts/artifact_capacity_policy.json"
            document = json.loads(policy.read_text(encoding="utf-8"))
            document.update(target_gib=.125, minimum_free_gib=0)
            policy.write_text(json.dumps(document), encoding="utf-8")
            artifact = root / "artifacts"
            artifact.mkdir()
            initialize_capacity_ledger(artifact, objects=[])
            ions = root / "fixture.ion"
            ions.write_text("0.25,100,1,0,0,0,0,0,2,1,3\n", encoding="utf-8")
            expected = ion11_sources(ions)[1]
            source_map = root / "mapping.json"
            source_map.write_text(json.dumps(dict(native_order=[1], source_ids=[1], source_birth_s=[.25e-6],
                                                   source_weights=[1.], source_initial_position_mm=[[0., 0., 0.]],
                                                   source_initial_velocity_m_s=[[expected["velocity_x_m_s"], expected["velocity_y_m_s"], expected["velocity_axial_m_s"]]],
                                                   native_scope="complete_cohort")), encoding="utf-8")
            rows = []
            for event in ("source", "terminal"):
                row = {key: 0 for key in PARTICLE_STATE_COLUMNS}
                row.update(expected)
                row.update(particle_id=1, event=event, status="alive" if event == "source" else "transmitted",
                           terminal_reason="none" if event == "source" else "acceptance_surface")
                if event == "terminal":
                    row.update(time_us=1.25, elapsed_time_us=1.)
                row["rf_phase_rad"] = (2 * math.pi * 1.1e6 * row["time_us"] * 1e-6) % (2 * math.pi)
                rows.append(row)
            state = root / "fixture.csv"
            with state.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=PARTICLE_STATE_COLUMNS)
                writer.writeheader()
                writer.writerows(rows)
            limits = root / "limits.json"
            limits.write_text(json.dumps(dict(wall_clock_seconds=90, transient_run_directory_bytes=16777216,
                                              process_tree_working_set_bytes=2147483648,
                                              minimum_system_available_memory_bytes=1073741824)), encoding="utf-8")
            command = r"""
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$repo=REPO;$python=PYTHON;$artifact=ARTIFACT
foreach($key in @('MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN','MASS_SPECTROMETRY_HOST_RESOURCE_LEASE_TOKEN','MASS_SPECTROMETRY_HOST_RESOURCE_PARENT_TOKEN')){[Environment]::SetEnvironmentVariable($key,$null,'Process')}
$env:SIMULATION_PYTHON_EXE=$python;$env:MASS_SPECTROMETRY_ARTIFACT_ROOT=$artifact
$env:MASS_SPECTROMETRY_EXECUTION_ROOT=Join-Path $artifact 'execution'
$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=Join-Path $artifact 'host.sqlite3'
. (Join-Path $repo 'common/contracts/run_artifact_workflow.ps1')
. (Join-Path $repo 'common/paths/workspace_paths.ps1')
. (Join-Path $repo 'common/host_execution_lease.ps1')
$paths=Resolve-WorkspacePaths -SourceRoot $repo -Python $python
$parentId='20261031_230000__test__python__interface-parent'
$parent=New-RunPackage -Python $python -RepoRoot $repo -ArtifactRoot (Join-Path $artifact 'projects/rf_multipole_ion_optics') -PathContext $paths -RunId $parentId -Project rf_multipole_ion_optics -Mode transport_interface_readiness -RetentionContractEnabled -RetentionClass solver_review -RetentionReason 'synthetic completed stage test' -CapacityLedgerLifecycleEnabled -Software @('Python software fixture') -AdditionalDirectories @('comsol')
$config=Get-Content $parent.run_config -Raw|ConvertFrom-Json -AsHashtable
$config.parameters=@{execution_stage='full_particle_transport'}
$source=Join-Path $parent.input_dir 'source.ion';Copy-Item IONS $source
$interface=Join-Path $parent.input_dir 'interface.json';Copy-Item (Join-Path $repo 'projects/rf_multipole_ion_optics/variants/quadrupole/config/interface_contract.json') $interface
$design=Join-Path $parent.input_dir 'design.json';Write-RunJson -Path $design -Value @{drive=@{frequency_Hz=1100000.;phase_rad=0.}}
$config.inputs.particle_table=$source;$config.inputs.interface_contract=$interface;$config.inputs.resolved_design=$design
Write-RunJson -Path $parent.run_config -Value $config -Depth 64
Copy-Item STATE (Join-Path $parent.result_dir 'particle_state.csv')
$map=Get-Content SOURCE_MAP -Raw|ConvertFrom-Json -AsHashtable
Write-RunJson -Path (Join-Path $parent.result_dir 'release_source_mapping.json') -Value $map -Depth 10
$raw=$map.Clone();$raw.role='rf_quadrupole_comsol_raw_solver_metadata';$raw.raw_solution_persisted=$true;$raw.source_axial_offset_mm=0.
Write-RunJson -Path (Join-Path $parent.result_dir 'solver_raw_metadata.json') -Value $raw -Depth 10
'synthetic inert model, not COMSOL output'|Set-Content (Join-Path $parent.run_dir 'comsol/rf_multipole_ion_optics__model.mph')
'STATUS=PASS'|Set-Content (Join-Path $parent.log_dir 'comsol_bootstrap_report.txt')
# Actual managed Python PID/start/exit and public host release provide the
# process evidence. The project receipt role and scientific inputs are a fixture.
$limit=Get-Content LIMITS -Raw|ConvertFrom-Json
$budget=(Get-HostResourceBudget -Role COMSOL -Stage postprocess).Clone();$budget.memory_bytes=[long]$limit.process_tree_working_set_bytes
$lease=Enter-HostResourceStage -StatePath $paths.host_resource_state_path -Role COMSOL -Stage postprocess -RunId $parentId -Budget $budget
$seen=Invoke-ResourceBudgetedProcess -Limits $limit -RunDir $parent.artifact_run_dir -UsagePath (Join-Path $parent.log_dir 'fixture_usage.json') -FilePath $python -ArgumentList @('-c','"pass"') -WorkingDirectory $repo
$released=Exit-HostResourceStage -Lease $lease -PassThru
$receipt=@{role='comsol_launcher_completion';run_id=$parentId;fixture='not_native_comsol';host_release=@{inherited=[bool]$lease.inherited;token=[string]$lease.token;result=$released;error=$null};operations=@(@{operation_id='synthetic-completed-task';observation=@{exit_confirmed=$true;returncode=[int]$seen.exit_code;process_id=[int]$seen.root_process_id;process_started_at_utc_ticks=[long]$seen.root_process_started_at_utc_ticks}})}
Write-RunJson -Path (Join-Path $parent.log_dir 'native_completion.json') -Value $receipt -Depth 20
$stopped=Join-Path ROOT 'stopped.json'
$seal="import json,sys;from pathlib import Path;from common.contracts.run_capacity_lifecycle import seal_checkpoint;print(json.dumps(seal_checkpoint(Path(sys.argv[1]),Path(sys.argv[2]),owner='rf_multipole_ion_optics',writing_stopped=True,retain_payload=True,retention_reason='explicit synthetic fixture source')))"
Push-Location $repo;try{$json=& $python -B -c $seal $artifact $parent.run_config;if($LASTEXITCODE){throw 'fixture seal failed'};$json|Set-Content $stopped}finally{Pop-Location}
$before=@{};foreach($file in @('run_config.json','run_manifest.json','summary.json','logs/native_completion.json','results/solver_raw_metadata.json','results/release_source_mapping.json','results/particle_state.csv','inputs/source.ion')){$before[$file]=[Convert]::ToBase64String([IO.File]::ReadAllBytes((Join-Path $parent.artifact_run_dir $file)))}
$badStopped=Join-Path ROOT 'bad_stopped.json';'{}'|Set-Content $badStopped
$badId='20261031_230050__analysis__python__invalid-source';$caught=$false
$leaseDirectory=Join-Path $artifact 'common/capacity_protection_leases'
$leasesBefore=@(Get-ChildItem $leaseDirectory -File -ErrorAction SilentlyContinue|ForEach-Object Name)
try{& ENTRY -AnalyzeOnly -ParentManifestPath (Join-Path $parent.artifact_run_dir 'run_manifest.json') -StoppedReceiptPath $badStopped -LimitsPath LIMITS -RunId $badId -ResultPath (Join-Path ROOT 'bad_result.json') -PythonExe $python}catch{if($_.Exception.Message-notlike'*Source capacity owner verification failed*'){throw};$caught=$true}
$leasesAfter=@(Get-ChildItem $leaseDirectory -File -ErrorAction SilentlyContinue|ForEach-Object Name)
if(($leasesBefore-join',')-cne($leasesAfter-join',')){throw 'invalid source leaked a new capacity lease'}
if(-not$caught-or(Test-Path (Join-Path $artifact ('projects/rf_multipole_ion_optics/runs/'+$badId)))){throw 'invalid checkpoint source was accepted or created a new run'}
$result=Join-Path ROOT 'child_result.json';$childId='20261031_230100__analysis__python__interface'
& ENTRY -AnalyzeOnly -ParentManifestPath (Join-Path $parent.artifact_run_dir 'run_manifest.json') -StoppedReceiptPath $stopped -LimitsPath LIMITS -RunId $childId -ResultPath $result -PythonExe $python
$out=Get-Content $result -Raw|ConvertFrom-Json
if($out.stage-ne'complete'-or$out.status-ne'success'-or-not$out.writers_confirmed){throw 'analysis child did not finalize'}
$summary=Get-Content (Join-Path $out.run_directory 'summary.json') -Raw|ConvertFrom-Json
if($summary.gui_verified-or$summary.parent_request_completed-or$summary.new_solve_calls-ne0-or$summary.scientific_result-cne'NOT_EVALUATED'){throw 'analysis overclaimed parent/GUI/scientific completion'}
$completion=Get-Content (Join-Path $out.run_directory 'results/execution_completion.json') -Raw|ConvertFrom-Json
if($completion.writer_completion.operations.Count-ne1-or$completion.writer_completion.operations[0].observation.process_id-le0){throw 'actual analysis process fact missing'}
$manifest=Join-Path $out.run_directory 'run_manifest.json';$manifestBefore=[Convert]::ToBase64String([IO.File]::ReadAllBytes($manifest))
& ENTRY -ResumeFinalization -ResultPath $result -PythonExe $python
if([Convert]::ToBase64String([IO.File]::ReadAllBytes($manifest))-cne$manifestBefore){throw 'resume rewrote sealed child manifest'}
# A changed analysis fails in its own successor; immutable parent and previous
# frozen analysis remain unchanged. This is a synthetic parser fault, not physics.
$metrics=Join-Path $repo 'projects/rf_multipole_ion_optics/analysis/analyze_comsol_particle_state_metrics.py'
"raise RuntimeError('injected isolated analysis failure')"|Set-Content $metrics
$failedResult=Join-Path ROOT 'failed_child_result.json';$caught=$false
try{& ENTRY -AnalyzeOnly -ParentManifestPath (Join-Path $parent.artifact_run_dir 'run_manifest.json') -StoppedReceiptPath $stopped -LimitsPath LIMITS -RunId '20261031_230200__analysis__python__interface-fail' -ResultPath $failedResult -PythonExe $python}catch{if($_.Exception.Message-notlike'*Frozen postprocess failed with exit 1*'){throw};$caught=$true}
if(-not$caught){throw 'analysis child swallowed actual parser failure'}
$failed=Get-Content $failedResult -Raw|ConvertFrom-Json
if($failed.status-cne'failed'-or$failed.stage-cne'complete'-or-not$failed.writers_confirmed-or-not$failed.lease_released){throw 'failed parser did not retain failure and safely close actual writer'}
$failedSummary=Get-Content (Join-Path $failed.run_directory 'summary.json') -Raw|ConvertFrom-Json
if($failedSummary.failure_stage-cne'postprocess'-or$failedSummary.scientific_result-cne'NOT_EVALUATED'){throw 'analysis failure phase/science misreported'}
$stderr=Get-Content (Join-Path $failed.run_directory 'logs/postprocess.stderr.log') -Raw
if($stderr-notlike'*injected isolated analysis failure*'){throw 'actual Python primary error absent'}
$failedManifest=Join-Path $failed.run_directory 'run_manifest.json';$failedBytes=[Convert]::ToBase64String([IO.File]::ReadAllBytes($failedManifest))
$caught=$false;try{& ENTRY -ResumeFinalization -ResultPath $failedResult -PythonExe $python}catch{if($_.Exception.Message-notlike'*Original execution terminal status=failed*'){throw};$caught=$true}
if(-not$caught-or[Convert]::ToBase64String([IO.File]::ReadAllBytes($failedManifest))-cne$failedBytes){throw 'failed terminal resume reran analysis or changed status'}
Write-Output ('ACTUAL_POSTPROCESS_OPERATION='+($completion.writer_completion|ConvertTo-Json -Depth 12 -Compress))
foreach($key in $before.Keys){if([Convert]::ToBase64String([IO.File]::ReadAllBytes((Join-Path $parent.artifact_run_dir $key)))-cne$before[$key]){throw 'analysis changed parent bytes'}}
$origins=Get-Content (Join-Path $out.run_directory 'results/analysis_module_origins.json') -Raw|ConvertFrom-Json
foreach($property in $origins.PSObject.Properties){if(-not$property.Value.StartsWith((Join-Path $out.run_directory 'inputs/code')+[IO.Path]::DirectorySeparatorChar)){throw 'active analysis source fallback'}}
Write-Output ('ACTUAL_INTERFACE_CHILD='+$out.run_directory)
"""
            bindings = {"REPO": facade, "PYTHON": sys.executable, "ARTIFACT": artifact,
                        "IONS": ions, "SOURCE_MAP": source_map, "STATE": state, "LIMITS": limits, "ROOT": root, "ENTRY": target}
            for key, value in bindings.items():
                command = re.sub(r"\b" + key + r"\b", lambda _: literal(value), command)
            environment = os.environ.copy()
            for key in list(environment):
                if key.startswith("MASS_SPECTROMETRY_HOST_"):
                    environment.pop(key)
            result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                                    cwd=facade, env=environment, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=180)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("ACTUAL_INTERFACE_CHILD=", result.stdout)
            print(result.stdout)
