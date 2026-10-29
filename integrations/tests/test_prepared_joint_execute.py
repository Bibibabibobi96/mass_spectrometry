"""Root prepared IP/MR execution routing and lifecycle, without vendor software."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
MR = REPO / "projects/parallel_mirror_dual_stripe_mr_tof"


def analysis_source_fixture(workspace, *, status="failed", owner="instrument_assembly", complete=True):
    """Public manifest/ledger with synthetic native-completion evidence, no solver."""
    from common.contracts.capacity_ledger import initialize_capacity_ledger
    from common.contracts.write_run_manifest import build_run_manifest, file_record
    root = workspace / "artifacts"
    run = root / "projects/instrument_assembly/runs/20261022_120000__test__simion__source"
    results = run / "results"
    results.mkdir(parents=True)
    logs = run / "logs"
    logs.mkdir()
    recording = dict(schema_version=1, mode="every_step", retention_class="solver_review",
                     reason="Synthetic analysis lifecycle regression", output_budget_bytes=1048576)
    contract = workspace / "new_analysis_contract.json"
    contract.write_text(json.dumps(dict(simion=dict(trajectory_recording=recording), peak_analysis=dict(test="explicit"))))
    prep = results / "prepared_joint_trial.json"
    expected = [i for i in range(1, 101) if i not in {24, 64, 80}]
    prep.write_text(json.dumps(dict(schema_version=1, role="mrtof_prepared_joint_trial", source_mode="measured_population",
        expected_particle_ids=expected, mother_particle_count=100, launched_particle_count=97,
        solver_epoch_instrument_time_us=7500.63364160348, protected_paths=[str(run)])))
    log = logs / "native_two_prism_flight.log"
    log.write_text("INERT NATIVE LOG FIXTURE; no commercial flight executed\n")
    batch_receipt = results / "batch_receipt.json"
    batch_receipt.write_text(json.dumps(dict(original_particle_ids=expected)))
    fly = results / "joint.fly2"
    fly.write_text("INERT LAUNCHED STATE FIXTURE\n")
    merge = results / "batch_log_merge_receipt.json"
    merge.write_text(json.dumps(dict(schema_version=1, role="mrtof_measured_batch_log_merge",
        status="success" if complete else "incomplete", preparation=file_record(prep), merged_log=file_record(log),
        particle_count=97, mother_particle_count=100, original_particle_ids=expected,
        all_batch_losses_retained=True, id_rebasing_applied=False, solver_epoch_instrument_time_us=7500.63364160348,
        batches=[dict(log=file_record(log), batch_receipt=file_record(batch_receipt), fly2=file_record(fly))])))
    summary = run / "summary.json"
    summary.write_text(json.dumps(dict(status=status, failure_stage="automatic_joint_diagnostics")))
    config = run / "run_config.json"
    config.write_text(json.dumps(dict(schema_version=2, run_id=run.name, project=owner, mode="prepared_joint", inputs={},
        capacity_ledger_lifecycle=dict(schema_version=1, enabled=True, artifact_root=str(root)),
        artifact_retention=dict(policy_version=1, **{"class": "solver_review"}, reason=recording["reason"]))))
    manifest = build_run_manifest(config, status, output_paths=[prep, log, batch_receipt, fly, merge, summary])
    (run / "run_manifest.json").write_text(json.dumps(manifest))
    initialize_capacity_ledger(root, objects=[dict(path=run.relative_to(root).as_posix(), owner="instrument_assembly",
        **{"class": "rebuildable_payload"}, bytes=sum(p.stat().st_size for p in run.rglob("*") if p.is_file()), status="ready")])
    return run, contract


class PreparedJointAnalysisTests(unittest.TestCase):
    def test_source_admission_keeps_original_paths_and_does_not_read_native_logs(self):
        from integrations.workflows.prepared_joint.analysis import prepare_analysis_inputs
        for status in ("success", "failed"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                source, contract = analysis_source_fixture(workspace, status=status)
                before = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
                with patch("integrations.workflows.prepared_joint.analysis.verify_record", wraps=__import__(
                    "common.contracts.verify_run_manifest", fromlist=["verify_record"]).verify_record) as verifier:
                    result = prepare_analysis_inputs(source, contract, workspace / "inputs")
                verified = [str(call.args[1]["path"]) for call in verifier.call_args_list]
                self.assertFalse(any(path.endswith((".log", ".fly2", ".pa")) for path in verified))
                self.assertEqual(result["mother_particle_count"], 100)
                self.assertEqual(result["launched_particle_count"], 97)
                self.assertEqual(result["merged_log"], str(source / "logs/native_two_prism_flight.log"))
                self.assertEqual(result["preparation"], str(source / "results/prepared_joint_trial.json"))
                self.assertEqual(result["merge_receipt"], str(source / "results/batch_log_merge_receipt.json"))
                self.assertNotIn("merged_log_identity", result)
                self.assertEqual(Path(result["analysis_contract"]).read_bytes(), contract.read_bytes())
                self.assertEqual(Path(result["source_manifest"]).read_bytes(), before[source / "run_manifest.json"])
                self.assertEqual({p.name for p in (workspace / "inputs").iterdir()},
                                 {"source_run_manifest.json", "analysis_contract.json"})
                for path, payload in before.items():
                    self.assertEqual(path.read_bytes(), payload)

    def test_source_admission_rejects_wrong_owner_and_incomplete_native_before_output(self):
        from integrations.workflows.prepared_joint.analysis import prepare_analysis_inputs
        for owner, complete, message in (("parallel_mirror_dual_stripe_mr_tof", True, "instrument_assembly/prepared_joint"),
                                         ("instrument_assembly", False, "complete original-ID")):
            with self.subTest(owner=owner, complete=complete), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                source, contract = analysis_source_fixture(workspace, owner=owner, complete=complete)
                with self.assertRaisesRegex(ValueError, message):
                    prepare_analysis_inputs(source, contract, workspace / "inputs")
                self.assertFalse((workspace / "inputs").exists())

    def test_public_analysis_runner_freezes_sources_and_publishes_success_or_failure_without_simion(self):
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("PowerShell 7 is unavailable")
        inventory = json.loads((REPO / "integrations/config/runtime_dependencies.json").read_text())
        records = [item for group in inventory["providers"] for item in group["files"]
                   if "prepared_joint" in item["consumers"]]
        support = {"common/contracts/run_artifact_support.ps1", "common/require_powershell7.ps1", "common/host_execution_lease.ps1"}
        capacity_fixture = r'''
function Invoke-RunCapacityLifecycleAdapter {return @{light_evidence_budget_exceeded=$false}}
function Enter-ArtifactWorkflowCapacitySession {
 param($Python,$RepoRoot,$ArtifactRoot,$RunDirectory,$CommittedNewBytes,$ProtectedPaths,$Owner)
 if($CommittedNewBytes-ne1048576-or$ProtectedPaths.Count-ne2){throw 'Analysis capacity/source protection differs'}
 return @{committed_new_bytes=$CommittedNewBytes}
}
function Update-ArtifactWorkflowCapacitySession {
 param($Python,$RepoRoot,$Session,$ProtectedPaths,$RemainingCommittedNewBytes)
 if($env:ANALYSIS_TEST_CAPACITY_FAIL-eq'1'-and$RemainingCommittedNewBytes-eq0){throw 'Explicit inert terminal capacity failure'}
 return @{session=$Session}
}
function Exit-ArtifactWorkflowCapacitySession {$script:capacityReleased=$true}
'''
        host_fixture = r'''
# Explicit inert host admission; this fixture never creates a host ledger.
function Enter-HostExecutionLease {
 param($Role,$Stage,$RunId)
 if($Role-ne'GATE'-or$Stage-ne'unclassified'){throw 'Analysis must request ordinary host admission'}
 [IO.File]::AppendAllText($env:ANALYSIS_TEST_HOST_EVENTS,"enter:$Role/$Stage`n")
 return @{test_lease='analysis';run_id=$RunId}
}
function Exit-HostExecutionLease {
 param($Lease,$Outcome,$RunId)
 if($Lease.test_lease-ne'analysis'-or$Lease.run_id-ne$RunId){throw 'Analysis released a different host lease'}
 [IO.File]::AppendAllText($env:ANALYSIS_TEST_HOST_EVENTS,"exit:$Outcome`n")
}
'''
        owner_fixture = r'''
# Explicit lifecycle boundary fixture; the real adapter and CLI recovery run
# separately in test_workflow_finalization_recovery.
function Initialize-RunArtifactPowerShellOwner {param($Package) @{package=$Package;result_path='inert-result'}}
function Complete-RunArtifactPowerShellOwner {
 param($Context,$Status,$Summary,$OutputPaths,$WritersStopped,$WriterCompletion,$OriginalFailure)
 if(-not$WritersStopped-or$WriterCompletion.operations.Count-or$WriterCompletion.resource_releases.Count){throw 'Analysis fabricated native execution'}
 Write-RunJson -Path $Context.package.summary -Value $Summary
 $null=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $Context.package.run_config
 $null=Update-ArtifactWorkflowCapacitySession -RemainingCommittedNewBytes 0
 Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $Context.package.run_config -Status $Status -Software @('Python fixture') -Outputs @($OutputPaths) -DeferCapacityFinalization|Out-Host
 Invoke-ProjectPython -Arguments @('-m','common.contracts.run_capacity_lifecycle','--action','seal-stopped-payload','--run-config',$Context.package.run_config)|Out-Host
 @{status=$Status;stage='complete'}
}
'''
        analyzer_fixture = '''import json, os, sys
from pathlib import Path
args=sys.argv
assert args[1]=='analyze-joint'
def argument(key): return Path(args[args.index(key)+1])
prep=argument('--preparation'); log=argument('--log'); contract=argument('--analysis-contract'); output=argument('--output')
assert prep.parent.parent.name.endswith('__source') and log.parent.parent==prep.parent.parent
assert contract.parent.parent==output.parent.parent and contract.name=='analysis_contract.json'
assert json.loads(prep.read_text())['launched_particle_count']==97
assert json.loads(contract.read_text())['peak_analysis']=={'test':'explicit'}
assert Path(os.environ['ANALYSIS_TEST_HOST_EVENTS']).read_text()=='enter:GATE/unclassified\\n'
if os.environ['ANALYSIS_TEST_FAIL']=='1': raise RuntimeError('Explicit inert analysis failure')
output.mkdir()
(output/'diagnostics_receipt.json').write_text(json.dumps(dict(status='success',inert_test=True)))
'''
        seal_fixture = '''import json, os, sys
from pathlib import Path
args=sys.argv
assert args[args.index('--action')+1]=='seal-stopped-payload'
run=Path(args[args.index('--run-config')+1]).parent
assert json.loads((run/'run_manifest.json').read_text(encoding='utf-8-sig'))['status'] in ('success','failed')
if os.environ['ANALYSIS_TEST_SEAL_FAIL']=='1': raise RuntimeError('Explicit inert seal failure')
'''
        for scenario in ("success", "analysis_failure", "wrong_owner", "incomplete_native", "capacity_failure", "seal_failure"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                repo = workspace / "simulation_repo"
                for relative in support | {item["source_repo_path"] for item in records}:
                    target = repo / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(REPO / relative, target)
                dependency = repo / "integrations/config/runtime_dependencies.json"
                dependency.parent.mkdir(parents=True, exist_ok=True)
                dependency.write_text(json.dumps(inventory))
                helpers = repo / "common/contracts/run_artifact_support.ps1"
                helpers.write_text(helpers.read_text() + capacity_fixture)
                (repo / "common/host_execution_lease.ps1").write_text(host_fixture)
                workflow_owner = repo / "common/contracts/run_artifact_workflow.ps1"
                workflow_owner.write_text(workflow_owner.read_text() + owner_fixture)
                (repo / "projects/parallel_mirror_dual_stripe_mr_tof/analysis/mrtof_batch_flight.py").write_text(analyzer_fixture)
                (repo / "common/contracts/run_capacity_lifecycle.py").write_text(seal_fixture)
                source, contract = analysis_source_fixture(workspace,
                    owner="parallel_mirror_dual_stripe_mr_tof" if scenario == "wrong_owner" else "instrument_assembly",
                    complete=scenario != "incomplete_native")
                before = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
                run_id = "20261022_120001__analysis__python__joint-test"
                run = source.parent / run_id
                completed = subprocess.run([pwsh, "-NoProfile", "-File", str(repo / "integrations/workflows/prepared_joint/execute.ps1"),
                    "-AnalyzeRunPath", str(source), "-ContractPath", str(contract), "-RunId", run_id,
                    "-RepoRoot", str(repo), "-PythonExe", sys.executable], cwd=workspace,
                    env={**os.environ, "PYTHONPATH": str(repo), "PYTHONNOUSERSITE": "1", "ProgramFiles": str(workspace / "NO_SIMION"),
                         "ANALYSIS_TEST_HOST_EVENTS": str(workspace / "host_events.txt"),
                         "ANALYSIS_TEST_FAIL": "1" if scenario == "analysis_failure" else "0",
                          "ANALYSIS_TEST_CAPACITY_FAIL": "1" if scenario == "capacity_failure" else "0",
                         "ANALYSIS_TEST_SEAL_FAIL": "1" if scenario == "seal_failure" else "0"},
                    capture_output=True, text=True, encoding="utf-8", timeout=45)
                self.assertEqual(completed.returncode == 0, scenario == "success", completed.stdout + completed.stderr)
                self.assertEqual((workspace / "host_events.txt").read_text().splitlines(),
                                 ["enter:GATE/unclassified", "exit:success" if scenario == "success" else "exit:failed"])
                self.assertFalse((workspace / "artifacts/common/host_resources.sqlite3").exists())
                manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8-sig"))
                configuration = json.loads((run / "run_config.json").read_text(encoding="utf-8-sig"))
                summary = json.loads((run / "summary.json").read_text(encoding="utf-8-sig"))
                self.assertEqual((manifest["project"], manifest["mode"]), ("instrument_assembly", "prepared_joint_analysis"))
                expected_manifest_status = (
                    "checkpoint" if scenario == "capacity_failure"
                    else "success" if scenario in {"success", "seal_failure"} else "failed"
                )
                self.assertEqual(manifest["status"], expected_manifest_status)
                self.assertFalse(summary["native_flight_executed"])
                self.assertFalse(list(run.rglob("*.pa*")))
                self.assertFalse(list(run.rglob("*.log")))
                self.assertFalse((run / "inputs/analysis_inputs.json").exists())
                self.assertNotIn("analysis_inputs", configuration["inputs"])
                if scenario in {"success", "analysis_failure", "capacity_failure", "seal_failure"}:
                    self.assertEqual(Path(configuration["inputs"]["source_preparation"]), source / "results/prepared_joint_trial.json")
                    self.assertEqual(Path(configuration["inputs"]["source_merge_receipt"]), source / "results/batch_log_merge_receipt.json")
                    self.assertEqual(Path(configuration["inputs"]["source_manifest"]).read_bytes(), before[source / "run_manifest.json"])
                    self.assertEqual(Path(configuration["inputs"]["analysis_contract"]).read_bytes(), contract.read_bytes())
                    self.assertEqual((configuration["parameters"]["mother_particle_count"],
                                      configuration["parameters"]["launched_particle_count"]), (100, 97))
                    self.assertTrue((run / "inputs/runtime_snapshot/integrations/workflows/prepared_joint/analysis.py").is_file())
                else:
                    self.assertEqual(summary["failure_stage"], "admit_completed_native_source")
                    self.assertFalse((run / "results/diagnostics").exists())
                for path, payload in before.items():
                    self.assertEqual(path.read_bytes(), payload)


class PreparedJointExecuteTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_missing_observation_calibrates_first_missing_batch_only(self):
        from common.simion.resource_scheduler import plan_recovered_formal_followup, plan_simion_dispatch
        request = {"solver": "SIMION", "field_kind": "rf", "rf_steps_per_period": 40,
                   "particle_count": 3, "independent_particles": True, "trajectory_quality": 8}
        provisional = plan_simion_dispatch(request, [], available_memory_bytes=10*1024**3,
                                           total_physical_memory_bytes=20*1024**3, logical_processors=8)
        first = provisional["waves"][0]["batches"][0]
        fallback = plan_recovered_formal_followup(provisional, {"natural_exit": True, "exit_code": 0,
            "count": first["count"], "source_row_range": [first["particle_id_min"], first["particle_id_max"]],
            "resource_observation": None})
        source = (REPO / "integrations/workflows/prepared_joint/execute.ps1").read_text()
        start = source.index("    $dispatchValue=Get-Content -LiteralPath $dispatch -Raw|ConvertFrom-Json")
        end = source.index("    $checkpoint={", start)
        block = source[start:end]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dispatch, plan = root / "dispatch.json", root / "plan.json"
            dispatch.write_text(json.dumps(fallback))
            plan.write_text(json.dumps({"batches": fallback["waves"][0]["batches"]}))
            quote = lambda value: "'" + str(value).replace("'", "''") + "'"
            script = f'''$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$dispatch={quote(dispatch)};$plan={quote(plan)};$request='unused';$profiles='unused';$continuation=@{{}}
$initial=Get-Content $plan -Raw|ConvertFrom-Json;$records=@{{}};foreach($b in $initial.batches){{$record=[pscustomobject]@{{scheduler_batch=$b;index=[int]$b.index}};if([int]$b.index-eq1){{$record|Add-Member -NotePropertyName reused -NotePropertyValue $true}};$records[[int]$b.index]=$record}}
$replay=@($initial.batches|Where-Object{{$_.index-ne1}});$script:calls=0
function Invoke-ProjectPython {{param($Arguments) $script:calls++;if($Arguments-notcontains'--recovered-missing-plan'-or$Arguments-contains'--request'){{throw 'wrong calibration'}};& {quote(sys.executable)} @Arguments;if($LASTEXITCODE-ne0){{throw 'calibration failed'}}}}
{block}
if($firstSpecification.index-ne2){{throw 'reused prefix selected for native observation'}}
$formal=[pscustomobject]@{{process_record=[pscustomobject]@{{completed=$true}};observed_peak_process_tree_working_set_bytes=1073741824;observed_process_cpu_percent=8;observed_background_cpu_percent=2;available_memory_bytes=10737418240;total_physical_memory_bytes=21474836480}}
& $replan $formal
$remaining=& $prepareRemaining $formal
if($script:calls-ne1-or@($remaining.pending).Count-ne1-or$remaining.pending[0].index-ne3){{throw 'wrong pending batches'}}
$calibrated=Get-Content $dispatch -Raw|ConvertFrom-Json
if(-not$calibrated.estimation.recovered_missing_observation_completed-or$calibrated.limits.maximum_concurrency-ne1){{throw 'wrong calibrated identity'}}
if($calibrated.estimation.observed_peak_bytes-ne1073741824-or$calibrated.estimation.observed_process_cpu_percent-ne8-or$calibrated.estimation.background_cpu_percent-ne2-or$calibrated.host.available_memory_bytes-ne10737418240-or$calibrated.host.total_physical_memory_bytes-ne21474836480){{throw 'actual observation changed'}}
if(($calibrated.waves[0].batches|ConvertTo-Json -Compress)-cne($initial.batches|ConvertTo-Json -Compress)){{throw 'fixed intervals changed'}}
'''
            path = root / "test.ps1"
            path.write_text(script, encoding="utf-8")
            completed = subprocess.run(["pwsh", "-NoProfile", "-File", str(path)], cwd=REPO,
                                       capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_existing_public_runner_replans_and_dispatches_local_batch_files(self):
        powershell = shutil.which("pwsh")
        if not powershell:
            self.skipTest("PowerShell 7 is unavailable")
        runner = REPO / "integrations/workflows/prepared_joint/execute.ps1"
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "mock.ps1"
            script.write_text(r'''param($Runner,$TestRoot,$PythonRuntime,$Repository,$Scenario)
$ErrorActionPreference='Stop'
$null = Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$null,[ref]$null)
$function=$ast.Find({param($node) $node-is[Management.Automation.Language.FunctionDefinitionAst]-and$node.Name-eq'Invoke-PreparedJointTrial'},$true)
$helperAst=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Repository 'common/resource_budget_support.ps1'),[ref]$null,[ref]$null)
$helper=$helperAst.Find({param($node) $node-is[Management.Automation.Language.FunctionDefinitionAst]-and$node.Name-eq'Invoke-ObservedPreparationFailureDrain'},$true)
Invoke-Expression $helper.Extent.Text
$helper=$helperAst.Find({param($node) $node-is[Management.Automation.Language.FunctionDefinitionAst]-and$node.Name-eq'Invoke-SimionFormalObservation'},$true)
Invoke-Expression $helper.Extent.Text
$helper=$helperAst.Find({param($node) $node-is[Management.Automation.Language.FunctionDefinitionAst]-and$node.Name-eq'Invoke-SimionBatchPhase'},$true)
Invoke-Expression $helper.Extent.Text
$code=$function.Extent.Text -replace '(?m)^  \. \(Join-Path[^\r\n]+',''
Invoke-Expression $code
$repoRoot=$TestRoot;$workspaceRoot=$TestRoot;$projectId='instrument_assembly'
New-Item -ItemType Directory -Path (Join-Path $repoRoot 'integrations/config')|Out-Null
@{schema_version=2;role='integration_runtime_dependencies';owner_id='instrument_assembly';consumer_ids=@('prepared_joint');providers=@()}|ConvertTo-Json -Depth 5|Set-Content (Join-Path $repoRoot 'integrations/config/runtime_dependencies.json')
function Freeze-ConsumerDependencies {
 param($RepoRoot,$ContractPath,$InputDir,$OwnerId,$ConsumerId)
 if($OwnerId-ne'instrument_assembly'-or$ConsumerId-ne'prepared_joint'){throw 'Wrong freeze owner/consumer'}
 $inventory=Join-Path $InputDir 'code_inventory.json';'{}'|Set-Content $inventory
 return @{execution_root=$Repository;code_inventory_path=$inventory;dependency_contract_path=$ContractPath;identities=@()}
}
'{}'|Set-Content (Join-Path $TestRoot 'run_manifest.json')
$env:PYTHONPATH=$Repository
$PreparedJointWorkbenchRunPath=$TestRoot;$ContractPath=$Runner;$RunId='mockrun';$python='mock';$simion=if($Scenario-eq'zero'){Join-Path $TestRoot 'missing-simion.exe'}else{$PythonRuntime}
$ContinuationPredecessorManifestPath=if($Scenario-in@('mixed','mixed_insufficient','zero')){Join-Path $TestRoot 'parent/run_manifest.json'}else{''}
$PreparedSourceMode='measured_population';$FieldBindingPath='';$TrajectoryEquivalenceReferenceRunPath='';$ResultPath=''
$script:capacityReleased=$false;$script:hostReleased=$false;$script:retained=$false;$script:sealed=$false
if($ContinuationPredecessorManifestPath){New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ContinuationPredecessorManifestPath),(Join-Path $TestRoot 'ancestor')|Out-Null;'{}'|Set-Content $ContinuationPredecessorManifestPath;'sealed'|Set-Content (Join-Path $TestRoot 'ancestor/source.log')}
$script:projectionCalls=0;$script:projectionCapacity=$false;$script:unprofiled=$false
function mock {
 $global:LASTEXITCODE=0;$script:projectionCalls++
 $ancestor=Join-Path $TestRoot 'ancestor/source.log'
 if($script:projectionCalls-eq2){$writable=$false;try{$stream=[IO.File]::Open($ancestor,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::ReadWrite);$stream.Dispose();$writable=$true}catch{};if($writable){throw 'Borrowed ancestor was not locked'}}
 @{run_directories=@((Split-Path -Parent $ContinuationPredecessorManifestPath),(Join-Path $TestRoot 'ancestor'));files=@($ContinuationPredecessorManifestPath,$ancestor);manifests=@{}}|ConvertTo-Json -Depth 10 -Compress
}
$script:adapted=$false;$script:observed=$false;$script:dispatched=$false;$script:analyzed=$false;$script:assetChecks=0;$script:leased=$false
function Write-RunJson {param($Path,$Depth,$Value) $Value|ConvertTo-Json -Depth 60|Set-Content $Path}
function New-RunPackage {
 param($Python,$RepoRoot,$ArtifactRoot,$RunId,$Project,$Mode,$Software,[switch]$RetentionContractEnabled,$RetentionClass,$RetentionReason,[switch]$CapacityLedgerLifecycleEnabled)
 if($Project-ne'instrument_assembly'-or$Mode-ne'prepared_joint'){throw 'Wrong new run owner/mode'}
 $r=Join-Path $TestRoot 'run';$results=Join-Path $r 'results';$logs=Join-Path $r 'logs'
 New-Item -ItemType Directory -Path (Join-Path $r 'inputs')|Out-Null
 New-Item -ItemType Directory -Path $results,$logs|Out-Null
 $config=Join-Path $r 'run_config.json';'{"run_id":"20261016_200000__sim__simion__fixture","project":"instrument_assembly","mode":"prepared_joint"}'|Set-Content $config
 return @{artifact_run_dir=$r;input_dir=(Join-Path $r 'inputs');result_dir=$results;log_dir=$logs;run_config=$config;summary=(Join-Path $r 'summary.json')}
}
function Enter-ArtifactWorkflowCapacitySession {return @{status='active'}}
function Update-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session,$ProtectedPaths,$RemainingCommittedNewBytes)
 if($ContinuationPredecessorManifestPath-and@($ProtectedPaths)-contains(Join-Path $TestRoot 'ancestor/source.log')){$script:projectionCapacity=$true}
 return @{session=@{status='active'}}}
function Exit-ArtifactWorkflowCapacitySession {}
function Write-VerifiedRunManifest {
 param($Python,$RepoRoot,$RunConfig,$Status,$Software,$Outputs,[switch]$DeferCapacityFinalization)
 if($Status-in@('success','failed','interrupted')-and-not$DeferCapacityFinalization){throw 'Stopped-payload owner must defer public capacity finalization'}
 & $PythonRuntime -m common.contracts.write_run_manifest --run-config $RunConfig --status $Status
 if($LASTEXITCODE-ne0){throw 'Actual public manifest writer rejected runner inputs'}
 $m=Get-Content (Join-Path (Split-Path -Parent $RunConfig) 'run_manifest.json') -Raw|ConvertFrom-Json
 if($m.inputs.PSObject.Properties.Value.exists-contains$false){throw 'Actual manifest has an unbound input'}
}
function Complete-FailedRun {throw 'Unexpected light-evidence finalizer used'}
function Initialize-RunArtifactPowerShellOwner {param($Package) return @{package=$Package;result_path='inert-result'}}
# This science-routing fixture replaces only the public lifecycle boundary;
# separate recovery tests execute the actual common owner and original CLI.
function Complete-RunArtifactPowerShellOwner {
 param($Context,$Status,$Summary,$OutputPaths,$WritersStopped,$WriterCompletion,$OriginalFailure)
 if(-not$WritersStopped){throw 'unknown writer retained'}
 Write-RunJson -Path $Context.package.summary -Depth 60 -Value $Summary
 $null=Apply-RunArtifactRetention
 Write-VerifiedRunManifest -RunConfig $Context.package.run_config -Status $Status -DeferCapacityFinalization|Out-Host
 Invoke-ProjectPython -Arguments @('-m','common.contracts.run_capacity_lifecycle','--action','seal-stopped-payload')
 return @{status=$Status;terminal_published=$true;lease_released=$true}
}

function Enter-HostResourceStage {$script:leased=$true;return @{test=$true;inherited=$false;token='actual-fixture-token'}}
function Get-HostResourceBudget {return @{test=$true}}
function Exit-HostResourceStage {param([Parameter(Mandatory)]$Lease,[switch]$PassThru) $script:hostReleased=$true;if($PassThru){@{status='released';token=$Lease.token}}}
function Complete-ResourceUsage {}
function Apply-RunArtifactRetention {if($Scenario-eq'closeout_failure'){throw 'Synthetic retention failure'};$script:retained=$true;$r=Join-Path $TestRoot 'run/retention_actions.json';'{}'|Set-Content $r;return $r}
function Invoke-ProjectPython {
 param($Arguments)
 if($Arguments[0]-eq'-c'){
  if(-not$script:leased){throw 'Payload verification preceded the native-stage lease'}
  $script:assetChecks+=1
  $fieldDirectory=if($Scenario-eq'candidate'){'candidate_fields'}else{'live_fields'}
  $writeSucceeded=$false
  try{$probe=[IO.File]::Open((Join-Path $TestRoot ($fieldDirectory+'/parent/field.pa')),[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::ReadWrite);$probe.Dispose();$writeSucceeded=$true}catch{}
  if($writeSucceeded){throw 'Payload verification preceded its write-denial guard'}
  & $PythonRuntime -B @Arguments
  if($LASTEXITCODE-ne0){throw 'Actual inert asset verification rejected drift'}
  return
 }
 $command=$Arguments[2]
 function Value($key){return $Arguments[[array]::IndexOf($Arguments,$key)+1]}
 if($Arguments-contains'--prepared-joint-current-preparation'){
  $parent=Join-Path $TestRoot 'parent';New-Item -ItemType Directory -Force -Path (Join-Path $parent 'results'),(Join-Path $parent 'logs')|Out-Null
  $borrowed=Join-Path $TestRoot 'ancestor_inputs';New-Item -ItemType Directory -Force -Path $borrowed|Out-Null
  $plan=Join-Path $borrowed 'simion_execution_batch_plan.json';Write-RunJson $plan 20 @{role='simion_single_wave_particle_batch_plan';batches=@(@{index=1;particle_id_min=1;particle_id_max=1;count=1},@{index=2;particle_id_min=2;particle_id_max=2;count=1})}
  $request=Join-Path $borrowed 'simion_dispatch_request.json';'{}'|Set-Content $request
  $profiles=Join-Path $borrowed 'simion_resource_profiles.json';'{}'|Set-Content $profiles
  $dispatch=Join-Path $borrowed 'simion_repository_dispatch_plan.json';Write-RunJson $dispatch 20 $(if($Scenario-eq'mixed_insufficient'){@{estimation=@{kind='observed_formal_batch'};waves=@(@{batches=@(@{count=0})})}}else{@{estimation=@{kind='observed'}}})
  $units=@();$batches=@();foreach($index in 1..2){$d=Join-Path $parent ('results/batches/batch_{0:D3}'-f$index);New-Item -ItemType Directory -Force -Path $d|Out-Null;$log=Join-Path $parent ('logs/joint_flight_batch_{0:D3}.log'-f$index);$receipt=Join-Path $d 'batch_receipt.json';$fly=Join-Path $d 'joint.fly2';'parent'|Set-Content $log;'{}'|Set-Content $receipt;'parent fly'|Set-Content $fly;$action=if($Scenario-in@('mixed','mixed_insufficient')-and$index-eq2){'replay'}else{'reuse'};$units+=@{key=('batch-{0:D3}'-f$index);action=$action;terminal_outputs=@(@{path=$log;sha256=('A'*64)},@{path=$receipt;sha256=('B'*64)},@{path=$fly;sha256=('C'*64)})};$batches+=@{index=$index;particle_id_min=$index;particle_id_max=$index;count=1;action=$action}}
  $o=Value '--output-dir';New-Item -ItemType Directory -Force -Path $o|Out-Null;Write-RunJson (Join-Path $o 'simion_whole_unit_replay_plan.json') 40 @{schema_version=2;role='simion_whole_unit_replay_plan';batch_plan=@{path=$plan;sha256=('D'*64)};dispatch_request=@{path=$request;sha256=('E'*64)};resource_profiles=@{path=$profiles;sha256=('F'*64)};dispatch_plan=@{path=$dispatch;sha256=('G'*64)};units=$units;batches=$batches;reusable_unit_count=$(if($Scenario-in@('mixed','mixed_insufficient')){1}else{2});replay_unit_count=$(if($Scenario-in@('mixed','mixed_insufficient')){1}else{0})};return
 }
 if($command-eq'recording-config'){return '{"mode":"fixed_interval","interval_us":0.1,"reason":"test","output_budget_bytes":10000}'}
 if($command-eq'prepare'){
  $r=Value '--run-directory';$results=Join-Path $r 'results'
  $fieldDirectory=if($Scenario-eq'candidate'){'candidate_fields'}else{'live_fields'}
  Write-RunJson (Join-Path $results 'prepared_joint_trial.json') 60 @{protected_paths=@();guard_paths=@((Join-Path $TestRoot ($fieldDirectory+'/parent/field.pa')),(Join-Path $TestRoot ($fieldDirectory+'/local/field.pa')));field_binding=@{path=(Join-Path $TestRoot ($fieldDirectory+'/binding.json'))};launched_particle_count=2;mother_particle_count=3;expected_particle_ids=@(1,7);prism_voltages_v=@(1,2);stripe_biases_v=@(0,0);trajectory_contract=@{path=$Runner};launcher='mock_launcher.lua';trajectory_equivalence_reference=@{reference_log='frozen'}}
  '{}'|Set-Content (Join-Path $results 'simion_dispatch_request.json')
 }elseif($command-eq'discover'){'{}'|Set-Content (Value '--output')
 }elseif($Arguments[1]-eq'common.simion.resource_scheduler'){
  if($Scenario-eq'mixed_insufficient'-and$Arguments-contains'--request'-and$Arguments-notcontains'--observed-formal-peak-bytes'){
   if($Arguments-contains'--profiles'){throw 'Insufficient profile was reused'};$script:unprofiled=$true
  }
  if($Arguments-contains'--prepare-fixed-recovery-plan'){
   if($Scenario-eq'mixed_insufficient'-and@($Arguments|Where-Object{$_-eq'--replay-batch-index'}).Count-ne1){throw 'Fixed recovery omitted missing batch'}
   $prior=Get-Content (Value '--output') -Raw|ConvertFrom-Json
   if($prior.estimation.kind-eq'formal_first_batch_observation'){$prior.estimation|Add-Member -NotePropertyName recovered_missing_observation -NotePropertyValue $true -Force}
   Write-RunJson (Value '--output') 20 $prior;return
  }
  if($Arguments-contains'--observed-formal-peak-bytes'){if($Scenario-in@('drain_failure','drain_budget_failure')){throw 'Synthetic replan failure'};$script:adapted=$true}
  $kind=if($script:adapted){'observed'}else{'formal_first_batch_observation'}
  Write-RunJson (Value '--output') 20 @{estimation=@{kind=$kind}}
 }elseif($Arguments[1]-eq'common.simion.particle_batching'){
  $batches=@(@{index=1;particle_id_min=1;particle_id_max=1;count=1})
  if($script:adapted){$batches+=@{index=2;particle_id_min=2;particle_id_max=2;count=1}}
  Write-RunJson (Value '--output') 20 @{batches=$batches}
 }elseif($command-eq'materialize-joint'){
  $d=Value '--output';New-Item -ItemType Directory -Path $d|Out-Null
  '{}'|Set-Content (Join-Path $d 'batch_receipt.json');'local'|Set-Content (Join-Path $d 'joint.fly2')
 }elseif($command-eq'merge-joint'){
  if(@($Arguments|Where-Object{$_-eq'--batch-log'}).Count-ne2){throw 'Replanned second batch was not merged'}
 }elseif($Arguments[1]-eq'common.contracts.run_capacity_lifecycle'){
  if($Arguments-notcontains'seal-stopped-payload'){throw 'Wrong finalizer'}
  $script:sealed=$true
  if($Scenario-eq'seal_failure'){throw 'Synthetic stopped payload seal failure'}
 }elseif($command-eq'compare-joint'){$script:compared=$true
 }elseif($command-eq'analyze-joint'){$script:analyzed=$true;if($Scenario-eq'analysis_failure'){throw 'Synthetic diagnostics failure'}}
 else{throw ('Unexpected Python command '+($Arguments-join' '))}
}
function Assert-LocalSpecification($Specification){
 if($Specification.argument_list[-1]-notlike'*joint.fly2'){throw 'Missing explicit local Fly2'}
 if($Specification.argument_list[-2]-notlike'*joint.iob'){throw 'Missing batch IOB'}
 if((Split-Path -Parent $Specification.argument_list[-1])-ne$Specification.working_directory){throw 'Fly2/IOB batch mismatch'}
 'status,Fly completed. 1 splats'|Set-Content $Specification.stdout
}
function Start-ObservedFormalProcess {
 param($DispatchPlanPath,$ProcessSpecification)
 if($Scenario-eq'mixed_insufficient'-and[int]$ProcessSpecification.scheduler_batch.index-ne2){throw 'Observed a reused batch'}
 Assert-LocalSpecification $ProcessSpecification;$script:observed=$true
 return @{resource_budget_exceeded=$false;completed_naturally=$true;exit_code=0;process_record=@{completed=$true;exit_code=0;root_process_id=44;root_process_started_at_utc_ticks=123;specification=$ProcessSpecification};observed_peak_process_tree_working_set_bytes=100;observed_process_cpu_percent=10;observed_background_cpu_percent=0;available_memory_bytes=10000;total_physical_memory_bytes=20000}
}
function Invoke-ResourceBudgetedProcesses {
 param($DispatchPlanPath,$RunDir,$UsagePath,$ProcessSpecifications,$ExistingProcessRecords,$OnProcessCompleted)
 if($Scenario-eq'drain_failure'){throw 'Synthetic drain failure'}
 if($Scenario-eq'drain_budget_failure'){return @{resource_budget_exceeded=$true;processes=@()}}
 if($Scenario-eq'wave_failure'){throw 'Synthetic batch runner failure'}
 if($Scenario-eq'closeout_failure'){try{throw 'Synthetic original flight failure'}catch{$_.Exception.Data['simion_wave_writer_completion_confirmed']=$true;throw}}
 if($Scenario-eq'wave_budget_failure'){return @{resource_budget_exceeded=$true;processes=@()}}
 if($Scenario-eq'mixed_insufficient'){
  if(@($ProcessSpecifications).Count-ne0-or@($ExistingProcessRecords).Count-ne1){throw 'Wrong retained observation wave'}
  if($OnProcessCompleted){foreach($record in @($ExistingProcessRecords)){& $OnProcessCompleted $record}}
 }else{
  if(@($ProcessSpecifications).Count-ne1-or$ProcessSpecifications[0].scheduler_batch.index-ne2){throw 'Wrong adaptive wave'}
  Assert-LocalSpecification $ProcessSpecifications[0];$script:dispatched=$true
  if($OnProcessCompleted){foreach($record in @($ExistingProcessRecords)+@(@{completed=$true;exit_code=0;root_process_id=44;root_process_started_at_utc_ticks=123;specification=$ProcessSpecifications[0]})){& $OnProcessCompleted $record}}
 }
 return @{resource_budget_exceeded=$false;processes=@(@{exit_code=0})}
}
try{Invoke-PreparedJointTrial;if($Scenario-notin@('success','candidate','mixed','mixed_insufficient','zero')){throw 'Expected scenario failure did not happen'}}catch{if($Scenario-in@('success','candidate','mixed','mixed_insufficient','zero')){throw};if($Scenario-eq'closeout_failure'){if($_.Exception.Message-ne'Synthetic original flight failure'-or$_.Exception.Data['prepared_joint_closeout_error']-notlike'*Synthetic retention failure*'){throw};'PUBLIC_PREPARED_RUNNER_MOCK_PASS';exit 0}}
if($Scenario-in@('drain_failure','drain_budget_failure','wave_failure','wave_budget_failure')){
 $summary=Get-Content (Join-Path $TestRoot 'run/summary.json') -Raw|ConvertFrom-Json
 $expectedReason=if($Scenario-in@('drain_failure','drain_budget_failure')){'Synthetic replan failure'}elseif($Scenario-eq'wave_failure'){'Synthetic batch runner failure'}else{'Measured joint flight failed or exceeded repository resource budget.'}
 if($summary.status-ne'writer_completion_unknown'-or$summary.reason-ne$expectedReason){throw 'Unknown writer evidence missing'}
 if($Scenario-eq'drain_failure'-and$summary.drain_error-ne'Synthetic drain failure'){throw 'Drain error missing'}
 if($Scenario-eq'drain_budget_failure'-and$summary.drain_error-notlike'*did not confirm writer completion*'){throw 'Unconfirmed budget drain missing'}
 if($script:capacityReleased-or$script:hostReleased-or$script:retained-or$script:sealed){throw 'Unknown writer was finalized'}
 'PUBLIC_PREPARED_RUNNER_MOCK_PASS';exit 0
}
$manifest=Get-Content (Join-Path $TestRoot 'run/run_manifest.json') -Raw|ConvertFrom-Json
$expectedStatus=if($Scenario-in@('analysis_failure','asset_failure')){'failed'}else{'success'}
if($manifest.status-ne$expectedStatus){throw 'Scientific manifest was incorrectly rewritten'}
if($Scenario-eq'asset_failure'){if($script:observed-or$script:dispatched-or$script:analyzed){throw 'Bad actual assets reached a vendor consumer'}}elseif($Scenario-in@('mixed','mixed_insufficient','zero')){if(-not($script:analyzed-and$script:sealed)){throw 'Recovery skipped merge or analysis'};if($Scenario-eq'zero'-and($script:observed-or$script:dispatched)){throw 'Zero-missing recovery launched SIMION'};if($Scenario-eq'mixed'-and($script:observed-or-not$script:dispatched)){throw 'Mixed recovery launched wrong batches'};if($Scenario-eq'mixed_insufficient'-and(-not$script:observed-or-not$script:adapted-or$script:dispatched)){throw 'Insufficient profile did not observe only the missing batch'}}elseif(-not($script:observed-and$script:adapted-and$script:dispatched-and$script:analyzed-and$script:sealed)){throw 'Missing public workflow stage'}
if($ContinuationPredecessorManifestPath-and($script:projectionCalls-ne2-or-not$script:projectionCapacity)){throw 'Ancestor projection was not protected and rechecked'}
if($ContinuationPredecessorManifestPath){$stream=[IO.File]::Open((Join-Path $TestRoot 'ancestor/source.log'),[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::ReadWrite);$stream.Dispose()}
if($Scenario-eq'mixed_insufficient'){$original=Get-Content (Join-Path $TestRoot 'ancestor_inputs/simion_repository_dispatch_plan.json') -Raw|ConvertFrom-Json;if($original.estimation.kind-ne'observed_formal_batch'-or-not$script:unprofiled){throw 'Ancestor dispatch was rewritten or insufficient profile reused'}}
if($Scenario-notin@('analysis_failure','asset_failure')-and-not$script:compared){throw 'Trajectory equivalence gate was skipped'}
if($script:assetChecks-ne$(if($Scenario-eq'zero'){0}else{1})){throw 'Native payload verification count differs'}
'PUBLIC_PREPARED_RUNNER_MOCK_PASS'
''', encoding="utf-8")
            for scenario in ("success", "candidate", "seal_failure", "analysis_failure", "mixed", "mixed_insufficient", "zero", "asset_failure", "drain_failure", "drain_budget_failure", "wave_failure", "wave_budget_failure", "closeout_failure"):
                with self.subTest(scenario=scenario):
                    case_root = Path(directory) / scenario
                    case_root.mkdir()
                    from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_static_field_binding import NativeStaticBindingTest
                    field_root = case_root / "live_fields"
                    field_root.mkdir()
                    binding = NativeStaticBindingTest().fixture(field_root)
                    (field_root / "binding.json").write_text(json.dumps(binding))
                    if scenario == "candidate":
                        candidate_root = case_root / "candidate_fields"
                        candidate_root.mkdir()
                        candidate = NativeStaticBindingTest().fixture(candidate_root)
                        (candidate_root / "binding.json").write_text(json.dumps(candidate))
                        (field_root / "parent/field.pa").write_bytes(b"XX")
                    if scenario == "asset_failure":
                        (field_root / "parent/field.pa").write_bytes(b"XX")
                    if scenario == "zero":
                        # Owner branch proof only: this harness substitutes preparation.
                        # Real preparation still requires PA metadata/existence.
                        shutil.rmtree(field_root)
                    result = subprocess.run([powershell,"-NoProfile","-File",str(script),str(runner),str(case_root),
                                             sys.executable,str(REPO),scenario],
                                            cwd=REPO,timeout=60,
                                            capture_output=True,text=True,encoding="utf-8",errors="replace",check=False)
                    self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                    self.assertIn("PUBLIC_PREPARED_RUNNER_MOCK_PASS",result.stdout)

    def test_old_entry_rejects_prepared_arguments_and_controller_selects_new_owner(self):
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 is unavailable")
        script = r"""
param($Repository)
$ErrorActionPreference='Stop'
$old=Join-Path $Repository 'projects/parallel_mirror_dual_stripe_mr_tof/simion/run_two_prism_trial.ps1'
if(Test-Path -LiteralPath $old){throw 'Old public entry remains'}
$controller=Join-Path $Repository 'projects/parallel_mirror_dual_stripe_mr_tof/analysis/run_downstream_workpoint_iteration.ps1'
$ast=[Management.Automation.Language.Parser]::ParseFile($controller,[ref]$null,[ref]$null)
$selected=$ast.FindAll({param($n) $n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-in@('$trialRunner','$trialArtifactRoot')},$true)
$repoRoot=$Repository;$controllerDirectory=Split-Path -Parent $controller;$artifactWorkspaceRoot='artifacts';$artifactRoot='artifacts/projects/parallel_mirror_dual_stripe_mr_tof'
foreach($kind in @('Prepared','Legacy')){
 $selection=@{ParameterSetName=$kind}
 foreach($assignment in $selected){Invoke-Expression ($assignment.Extent.Text.Replace('$PSCmdlet','$selection').Replace('$PSScriptRoot','$controllerDirectory'))}
 if($kind-eq'Prepared'){
  if($trialRunner-ne(Join-Path $Repository 'integrations/workflows/prepared_joint/execute.ps1')-or$trialArtifactRoot-ne(Join-Path $artifactWorkspaceRoot 'projects/instrument_assembly')){throw 'Prepared route differs'}
 }elseif([IO.Path]::GetFullPath($trialRunner)-ne[IO.Path]::GetFullPath((Join-Path $Repository 'integrations/workflows/oa_mr/execute.ps1'))-or$trialArtifactRoot-ne(Join-Path $artifactWorkspaceRoot 'projects/instrument_assembly')){throw 'Ordinary OA route changed'}
}
'PREPARED_ROUTE=PASS'
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "route.ps1"
            path.write_text(script, encoding="utf-8")
            result = subprocess.run([pwsh, "-NoProfile", "-File", str(path), str(REPO)],
                                    cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_prepared_child_rejects_old_or_wrong_owner(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration import load_prepared_centroid_trial
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "run_manifest.json"
            for owner, mode in (("parallel_mirror_dual_stripe_mr_tof", "two_prism_joint_measured_trial"),
                                ("orthogonal_accelerator", "prepared_joint"),
                                ("instrument_assembly", "two_prism_joint_measured_trial")):
                manifest.write_text(json.dumps(dict(status="success", project=owner, mode=mode)))
                with self.subTest(owner=owner, mode=mode), self.assertRaisesRegex(ValueError, "published successful measured joint"):
                    load_prepared_centroid_trial(manifest, manifest, manifest)

    def test_frozen_prepared_consumer_materializes_without_repository(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_measured_component_source import MeasuredComponentSourceTests
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 is unavailable")
        fixture = MeasuredComponentSourceTests("test_irregular_ids_birth_offsets_and_exact_six_dimensions")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture._materialize()
        inputs = fixture.root / "inputs"
        freeze = f"""
. '{REPO / 'integrations/runtime/dependencies.ps1'}'
$path='{REPO / 'integrations/config/runtime_dependencies.json'}'
$null=Freeze-ConsumerDependencies -RepoRoot '{REPO}' -ContractPath $path -InputDir '{inputs}' -OwnerId instrument_assembly -ConsumerId prepared_joint
"""
        completed = subprocess.run([pwsh, "-NoProfile", "-Command", freeze], cwd=REPO,
                                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)
        snapshot = inputs / "runtime_snapshot"
        relative = Path("projects/parallel_mirror_dual_stripe_mr_tof/simion")
        for name in ("mrtof_candidate.lua", "scalar_field_adapter.lua", "run_iob_flight.lua", "build_native_corridor_iob.lua"):
            self.assertEqual((snapshot / relative / name).read_bytes(), (REPO / relative / name).read_bytes())
        runtime = fixture.root / "runtime"
        runtime.mkdir()
        (runtime / "joint.iob").write_bytes(b"test IOB; never passed to a solver")
        shutil.copyfile(snapshot / relative / "mrtof_candidate.lua", runtime / "joint.lua")
        waveform = snapshot / "common/simion/voltage_waveforms.lua"
        shutil.copyfile(waveform, runtime / "joint.voltage_waveforms.lua")
        (runtime / "joint.operating_point.lua").write_text("return {static_field=nil}")
        preparation = fixture.root / "preparation.json"
        preparation.write_text(json.dumps(dict(measured_source_directory=str(fixture.output),
            frozen_runtime_directory=str(runtime), trajectory_recording=dict(mode="fixed_interval", interval_us=.1))))
        batch = fixture.root / "batch"
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        completed = subprocess.run([sys.executable, "-B", "-s", "-m",
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight", "materialize-joint",
            "--preparation", str(preparation), "--particle-id-min", "2", "--particle-id-max", "2", "--output", str(batch)],
            cwd=snapshot, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)
        receipt = json.loads((batch / "batch_receipt.json").read_text())
        self.assertEqual(receipt["original_particle_ids"], [7])
        self.assertEqual((batch / "joint.fly2").read_bytes(), (batch / "measured_source/source.fly2").read_bytes())
        self.assertEqual((batch / "joint.lua").read_bytes(), (snapshot / relative / "mrtof_candidate.lua").read_bytes())
        self.assertEqual((batch / "joint.voltage_waveforms.lua").read_bytes(), waveform.read_bytes())

    def test_equivalence_reads_exact_old_or_new_identity_without_execution_fallback(self):
        from common.contracts.write_run_manifest import file_record
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepared_joint_trial import freeze_equivalence_reference
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prior = root / "prior"
            (prior / "results/source").mkdir(parents=True)
            (prior / "logs").mkdir()
            current = root / "current"
            current.mkdir()
            filenames = ("component_particle_state.csv", "source_census.csv", "source_states.lua",
                         "source_projection.lua", "source.fly2", "clock_authority.json")
            for name in filenames:
                (prior / "results/source" / name).write_text("same frozen scientific bytes")
                (current / name).write_text("same frozen scientific bytes")
            log = prior / "logs/joint_flight_batch_001.log"
            log.write_text("MRTOF_EVENT terminal ion=7 t_us=7500.57\nstatus,Fly completed. 1 splats\nIOB_FLIGHT: PASS complete\n")
            preparation = dict(expected_particle_ids=[7], mother_particle_count=100, launched_particle_count=1,
                solver_epoch_instrument_time_us=7500, numerics=dict(maximum_step_us=.001),
                parent_preparation=dict(sha256="A"*64), field_binding=dict(sha256="B"*64),
                trajectory_contract=dict(sha256="C"*64), measured_source_directory=str(current))
            receipt = prior / "results/prepared_joint_trial.json"
            receipt.write_text(json.dumps(dict(preparation, measured_source_directory=str(prior / "results/source"))))
            records = [file_record(path) for path in [receipt, log, *sorted((prior / "results/source").iterdir())]]
            for index, (owner, mode) in enumerate((("instrument_assembly", "prepared_joint"),
                ("parallel_mirror_dual_stripe_mr_tof", "two_prism_joint_measured_trial"),
                ("parallel_mirror_dual_stripe_mr_tof", "prepared_joint"))):
                (prior / "run_manifest.json").write_text(json.dumps(dict(project=owner, mode=mode, status="interrupted", outputs=records)))
                destination = root / str(index)
                destination.mkdir()
                with patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepared_joint_trial.subprocess.run") as verifier:
                    if index == 2:
                        with self.assertRaisesRegex(ValueError, "owner/mode"):
                            freeze_equivalence_reference(prior, preparation, destination)
                    else:
                        result = freeze_equivalence_reference(prior, preparation, destination)
                        self.assertEqual(result["original_particle_ids"], [7])
                        self.assertEqual(Path(result["reference_log"]["path"]).read_bytes(), log.read_bytes())
                    verifier.assert_called_once()
