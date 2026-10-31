"""Native and static-field contract tests for the MR-TOF flight runner."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from common.contracts.write_run_manifest import file_record

REPO = Path(__file__).resolve().parents[2]
RUNNER = REPO / "integrations/workflows/oa_mr/execute.ps1"

class TwoPrismTrialRunnerTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_fixed_partition_observes_largest_missing_not_reused_prefix(self):
        from common.simion.resource_scheduler import plan_simion_dispatch, prepare_fixed_partition_dispatch
        request = {"solver":"SIMION", "field_kind":"rf", "rf_steps_per_period":40,
                   "particle_count":6, "independent_particles":True, "trajectory_quality":8}
        initial = plan_simion_dispatch(request, [], available_memory_bytes=10*1024**3,
                                       total_physical_memory_bytes=20*1024**3, logical_processors=8)
        batches = [dict(index=i, particle_id_min=low, particle_id_max=high, count=high-low+1,
                        simion_particle_id_offset=low-1) for i,(low,high) in enumerate(((1,1),(2,3),(4,6)),1)]
        plan = prepare_fixed_partition_dispatch(initial, dict(role="simion_single_wave_particle_batch_plan",
            coverage="complete_population", particle_count=6, batches=batches), [2,3])
        source = RUNNER.read_text(encoding="utf-8")
        start = source.index("    $dispatch=Get-Content -Raw -LiteralPath $runtimeDispatchPlanPath|ConvertFrom-Json")
        end = source.index("    $checkpointAction={", start)
        block = source[start:end]
        with TemporaryDirectory() as directory:
            root = Path(directory); dispatch = root/"dispatch.json"; dispatch.write_text(json.dumps(plan))
            quote = lambda value: "'"+str(value).replace("'", "''")+"'"
            script = f'''$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$runtimeDispatchPlanPath={quote(dispatch)};$batchContinuationPlan=@{{}};$replayBatchIndexes=@(2,3);$batchRecords=@{{1=@{{index=1}};2=@{{index=2}};3=@{{index=3}}}}
$dispatchRequestPath='unused';$resourceProfilesPath='unused';$batchPlanPath='unused'
function Get-MrtofBatchProcessSpecification {{param($Record) return [pscustomobject]@{{index=$Record.index}}}}
function Publish-MrtofFirstBatchAberration {{param($Record)}}
function Invoke-ProjectPython {{param($Arguments) & {quote(sys.executable)} @Arguments;if($LASTEXITCODE-ne0){{throw 'calibration failed'}}}}
{block}
if($firstSpec.index-ne3-or$formalBatchIndex-ne3){{throw 'did not observe largest missing unit'}}
$formal=[pscustomobject]@{{process_record=[pscustomobject]@{{completed=$true}};observed_peak_process_tree_working_set_bytes=1073741824;observed_process_cpu_percent=8;observed_background_cpu_percent=2;available_memory_bytes=10737418240;total_physical_memory_bytes=21474836480}}
& $replan $formal
$result=Get-Content $runtimeDispatchPlanPath -Raw|ConvertFrom-Json
if($result.estimation.observed_missing_batch_index-ne3-or$result.limits.maximum_concurrency-ne6-or$result.waves[0].batches[2].count-ne3){{throw 'calibrated fixed partition differs'}}
'''
            path = root/"fixed.ps1"; path.write_text(script, encoding="utf-8")
            result = subprocess.run([shutil.which("pwsh"),"-NoProfile","-File",str(path)],cwd=REPO,
                                    capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_continuation_protects_ancestor_before_locking_borrowed_evidence(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root/"parent"; ancestor = root/"ancestor"; parent.mkdir(); ancestor.mkdir()
            (parent/"logs").mkdir(); (parent/"results").mkdir()
            local = parent/"logs/native_two_prism_flight__batch01.log"; local.write_text("parent")
            borrowed = ancestor/"batch.log"; borrowed.write_text("ancestor")
            (parent/"run_config.json").write_text("{}")
            (ancestor/"run_manifest.json").write_text(json.dumps(dict(role="simulation_run_manifest", status="success")))
            manifest = dict(role="simulation_run_manifest", status="failed", inputs={"reused_batch_002_log": {"path":str(borrowed)}},
                            outputs=[{"path":str(local)}])
            (parent/"run_manifest.json").write_text(json.dumps(manifest))
            script = root/"protect.ps1"
            script.write_text(r'''param($Runner,$Parent,$Borrowed,$Repo)
$ErrorActionPreference='Stop';$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$null,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$runtime=Join-Path $Repo 'projects/parallel_mirror_dual_stripe_mr_tof/simion/native_corridor_runtime_support.ps1'
$ast=[Management.Automation.Language.Parser]::ParseFile($runtime,[ref]$null,[ref]$errors)
$node=$ast.Find({param($a)$a-is[Management.Automation.Language.FunctionDefinitionAst]-and$a.Name-eq'Protect-MrtofContinuationEvidence'},$true)
Invoke-Expression $node.Extent.Text
function Update-ArtifactWorkflowCapacitySession {
 param($Python,$RepoRoot,$Session,$ProtectedPaths,$SourceReferences)
 if(@($ProtectedPaths).Count-ne0-or@($SourceReferences).Count-ne2){throw 'Explicit manifest authorities were not admitted'}
 foreach($reference in $SourceReferences){
  $record=$reference.manifest_record;$authority=Split-Path -Parent $record.path
  if($authority-notin@($Parent,(Split-Path $Borrowed))-or$reference.protected_paths[0]-ne$authority){throw 'Wrong explicit authority'}
  if(-not$record.exists-or$record.bytes-ne(Get-Item $record.path).Length-or$record.sha256-ne(Get-FileHash $record.path -Algorithm SHA256).Hash){throw 'Manifest binding changed'}
  if($authority-eq(Split-Path $Borrowed)-and$reference.protected_paths-notcontains$Borrowed){throw 'Borrowed evidence not protected by its manifest'}
 }
 # Admission must precede read locks; this is still writable at this boundary.
 $writer=[IO.File]::Open($Borrowed,'Open','ReadWrite','ReadWrite');$writer.Dispose()
 $script:admitted=$true;return @{session=$Session}
}
$script:projectionCalls=0;$script:drift=$false;$script:omitAuthority=$false
function pythonFixture {
 $global:LASTEXITCODE=0;$script:projectionCalls++
 $ancestor=Split-Path $Borrowed;$parentManifest=Join-Path $Parent 'run_manifest.json';$ancestorManifest=Join-Path $ancestor 'run_manifest.json'
 $manifests=@{};$manifests[$parentManifest]=(Get-FileHash $parentManifest -Algorithm SHA256).Hash
 $manifests[$ancestorManifest]=if($script:drift-and$script:projectionCalls-eq2){'changed'}else{(Get-FileHash $ancestorManifest -Algorithm SHA256).Hash}
 @{run_directories=$(if($script:omitAuthority){@($Parent)}else{@($Parent,$ancestor)});
   files=@($Borrowed,(Join-Path $Parent 'logs/native_two_prism_flight__batch01.log'),$parentManifest,$ancestorManifest);
   manifests=$manifests}|ConvertTo-Json -Depth 20 -Compress
}
$guards=[Collections.Generic.List[IO.FileStream]]::new();$script:admitted=$false
$null=Protect-MrtofContinuationEvidence -Parent $Parent -Session @{status='active'} -Python pythonFixture -RepoRoot $Parent -Guards $guards
if(-not$script:admitted-or$script:projectionCalls-ne2){throw 'capacity renewal or locked reprojection missing'}
foreach($path in @($Borrowed,(Join-Path $Parent 'logs/native_two_prism_flight__batch01.log'),(Join-Path $Parent 'run_manifest.json'))){
 $blocked=$false;try{$w=[IO.File]::Open($path,'Open','Write','ReadWrite');$w.Dispose()}catch{$blocked=$true}
 if(-not$blocked){throw 'continuation source is writable'}
}
foreach($stream in $guards){$stream.Dispose()}
$guards=[Collections.Generic.List[IO.FileStream]]::new();$script:projectionCalls=0;$script:drift=$true;$caught=$false
try{Protect-MrtofContinuationEvidence -Parent $Parent -Session @{status='active'} -Python pythonFixture -RepoRoot $Parent -Guards $guards|Out-Null}catch{$caught=$_.Exception.Message-match'projection changed'}
foreach($stream in $guards){$stream.Dispose()}
if(-not$caught){throw 'changed projection was accepted'}
$guards=[Collections.Generic.List[IO.FileStream]]::new();$script:projectionCalls=0;$script:drift=$false;$script:omitAuthority=$true;$script:admitted=$false;$caught=$false
try{Protect-MrtofContinuationEvidence -Parent $Parent -Session @{status='active'} -Python pythonFixture -RepoRoot $Parent -Guards $guards|Out-Null}catch{$caught=$_.Exception.Message-match'no explicit projected run authority'}
foreach($stream in $guards){$stream.Dispose()}
if(-not$caught-or$script:admitted){throw 'Missing explicit authority reached admission'}

''', encoding="utf-8")
            result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(script), str(RUNNER), str(parent), str(borrowed), str(REPO)],
                                    cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

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
        source = RUNNER.read_text(encoding="utf-8")
        start = source.index("    $dispatch=Get-Content -Raw -LiteralPath $runtimeDispatchPlanPath|ConvertFrom-Json")
        end = source.index("    $checkpointAction={", start)
        block = source[start:end]
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dispatch = root / "dispatch.json"
            dispatch.write_text(json.dumps(fallback))
            quote = lambda value: "'" + str(value).replace("'", "''") + "'"
            script = f'''$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$runtimeDispatchPlanPath={quote(dispatch)};$batchContinuationPlan=@{{}};$replayBatchIndexes=@(2,3);$batchRecords=@{{1=@{{index=1}};2=@{{index=2}};3=@{{index=3}}}}
$dispatchRequestPath='unused';$resourceProfilesPath='unused';$batchPlanPath='unused';$script:calls=0
function Get-MrtofBatchProcessSpecification {{param($Record) return [pscustomobject]@{{index=$Record.index}}}}
function Publish-MrtofFirstBatchAberration {{param($Record)}}
function Invoke-ProjectPython {{param($Arguments) $script:calls++;if($Arguments-notcontains'--recovered-missing-plan'-or$Arguments-contains'--request'){{throw 'wrong calibration'}};& {quote(sys.executable)} @Arguments;if($LASTEXITCODE-ne0){{throw 'calibration failed'}}}}
{block}
if($firstSpec.index-ne2-or$formalBatchIndex-ne2){{throw 'reused prefix selected for native observation'}}
$formal=[pscustomobject]@{{process_record=[pscustomobject]@{{completed=$true}};observed_peak_process_tree_working_set_bytes=1073741824;observed_process_cpu_percent=8;observed_background_cpu_percent=2;available_memory_bytes=10737418240;total_physical_memory_bytes=21474836480}}
& $replan $formal
if($script:calls-ne1-or@($replanState.replayIndexes).Count-ne2-or$replanState.replayIndexes[0]-ne2-or$replanState.replayIndexes[1]-ne3){{throw 'wrong pending batches'}}
$calibrated=Get-Content $runtimeDispatchPlanPath -Raw|ConvertFrom-Json
if(-not$calibrated.estimation.recovered_missing_observation_completed-or$calibrated.limits.maximum_concurrency-ne3){{throw 'wrong calibrated identity'}}
if($calibrated.estimation.observed_peak_bytes-ne1073741824-or$calibrated.estimation.observed_process_cpu_percent-ne8-or$calibrated.estimation.background_cpu_percent-ne2-or$calibrated.host.available_memory_bytes-ne10737418240-or$calibrated.host.total_physical_memory_bytes-ne21474836480){{throw 'actual observation changed'}}
if(@($calibrated.waves[0].batches).Count-ne3-or$calibrated.waves[0].batches[0].particle_id_max-ne1-or$calibrated.waves[0].batches[1].particle_id_min-ne2){{throw 'fixed intervals changed'}}
'''
            path = root / "test.ps1"
            path.write_text(script, encoding="utf-8")
            completed = subprocess.run(["pwsh", "-NoProfile", "-File", str(path)], cwd=REPO,
                                       capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_real_recovery_stages_skip_native_for_zero_and_run_only_missing_batches(self):
        """Execute the public script's stages with real recovery, guards and merging.

        The supplied logs are inert vendor output, not physical qualification.
        Capacity admission is inert; the public checkpoint writer and scientific
        input/terminal identity checks execute normally.
        """
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_mrtof_batch_continuation import MrtofBatchContinuationTests
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_static_field_binding import NativeStaticBindingTest
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_bunch_source_and_schedule import _states
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.bunch_source_and_schedule import materialize_bunch_source
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import load_binding
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial import resolve_trajectory_recording
        from common.contracts.verify_run_manifest import verify_record
        from common.integration.resolve_assembly import compile_assembly_layout, derive_assembly_scope
        from common.integration.test_resolve_assembly import direct_fixture
        recipe,components=direct_fixture()
        parent_assembly=compile_assembly_layout(recipe,components)
        source = RUNNER.read_text(encoding="utf-8")
        start = source.index("    if(-not[string]::IsNullOrWhiteSpace($BatchContinuationRunPath)){")
        stages = "  if($isBunchFlight){\n" + source[start:source.index("  # Static component guards remain live", start)]
        python_helper = source[source.index("function Format-InvariantNumber {"):source.index("function Invoke-SimionStage {")]
        path_import = next(line for line in source.splitlines()
                           if line.startswith(". ") and "common/paths/workspace_paths.ps1" in line)
        pa_provenance = next(line for line in source.splitlines()
                             if line.strip().startswith("$config['provenance']['pa_bindings']="))
        final_inputs = source[source.index("  $flightInputs=[ordered]@{"):source.index("  foreach($entry in $flightInputs.GetEnumerator())")]
        for name in ("native_global_fallback_pa", "private_accelerator_controller_pa", "read_only_detector_pa"):
            self.assertNotIn(name + "=", final_inputs)
        for case in ("zero", "mixed", "fresh", "science_changed", "gui_missing", "mixed_missing"):
            with self.subTest(case=case), TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                fixture = MrtofBatchContinuationTests()
                parent, config_path = fixture._fixture(root, static_mode="native_static_pa")
                current = config_path.parent
                fields = root / "fields"
                fields.mkdir()
                descriptor = NativeStaticBindingTest().fixture(fields)
                binding_path = root / "binding.json"
                binding_path.write_text(json.dumps(descriptor))
                metadata = load_binding(binding_path)
                metadata_path = root / "metadata.json"
                metadata_path.write_text(json.dumps(metadata))
                # Both runs bind the same actual sealed payload authority;
                # only their tiny transported descriptor locators differ.
                for run in (parent, current):
                    config = json.loads((run / "run_config.json").read_text())
                    Path(config["inputs"]["static_field_binding"]).write_bytes(binding_path.read_bytes())
                    trial_path = Path(config["inputs"]["trial_materialization"])
                    trial = json.loads(trial_path.read_text())
                    trial["field_binding"] = dict(path=config["inputs"]["static_field_binding"], **metadata)
                    trial["trajectory_recording"] = resolve_trajectory_recording({"simion": {}})
                    trial_path.write_text(json.dumps(trial))
                for index, count in ((1, 1), (2, 2)):
                    if index == 2 and case in ("mixed", "mixed_missing"):
                        continue
                    (parent / "logs" / f"native_two_prism_flight__batch{index:02d}.log").write_text(
                        "".join(f"MRTOF_EVENT terminal ion={i} splat=1 t_us=2 turns=0 x_mm=0 y_mm=0 z_mm=0 vx_mm_us=0 vy_mm_us=0 vz_mm_us=0 central_crossings=0\n" for i in range(1, count+1))
                        + f"status,Fly completed. {count} splats\nIOB_FLIGHT: PASS iob=fixture.iob\n")
                local_scope=(dict(instance_ids=['oa'],research_scope='inert publication fixture',
                    boundary_assumptions='upstream guide omitted') if case.startswith('mixed') else None)
                selected=derive_assembly_scope(parent_assembly,local_scope=local_scope)
                self.assertEqual(selected['scope']['kind'],'local' if local_scope else 'full')
                if local_scope is None:
                    self.assertEqual(selected['scope']['instance_ids'],['guide','oa'])
                for run in (parent,current):
                    assembly_path=run/'inputs/oa_mr_composition_plan.json'
                    assembly_path.write_text(json.dumps(parent_assembly),encoding='utf-8')
                    if local_scope is not None:
                        (run/'inputs/oa_mr_local_scope.json').write_text(json.dumps(local_scope),encoding='utf-8')
                fixture._seal_oa_parent(parent)
                parent_before = {path: path.read_bytes() for path in parent.rglob("*") if path.is_file()}
                config = json.loads(config_path.read_text())
                config.update(run_id="20261025_170000__sim__simion__oa-recovery-fixture",
                              project="instrument_assembly", mode="oa_mr")
                config_path.write_text(json.dumps(config))
                if case == "science_changed":
                    path = Path(config["inputs"]["trial_materialization"])
                    trial = json.loads(path.read_text())
                    trial["source_time_of_birth_us"] = 0.5
                    path.write_text(json.dumps(trial))
                if case in ("zero", "gui_missing", "mixed_missing"):
                    for level in (descriptor["parent"], *descriptor["refinement_windows"]):
                        Path(level["pa_path"]).unlink()
                        Path(level["surface_path"]).unlink()
                results = current / "results"
                results.mkdir()
                plan_path = results / "simion_execution_batch_plan.json"
                plan_path.write_bytes((parent / "inputs/simion_execution_batch_plan.json").read_bytes())
                dispatch_path = results / "dispatch.json"
                dispatch_path.write_text(json.dumps(dict(particle_count=3, field_kind="electrostatic",
                    estimation=dict(kind="exact_resource_profile", observed_batch_work_units=2),
                    limits=dict(maximum_concurrency=1), waves=[dict(batches=[])])))
                source_receipt = root / "source.json"
                materialize_bunch_source(states=_states(100), mother_particle_count=1000,
                    source_profile_id="recovery_fixture", frame_id="fixture",
                    state_table_path=root / "states.csv", fly2_path=root / "source.fly2",
                    receipt_path=source_receipt)
                solver = current / "inputs"
                (solver / "4_instance_seed.iob").write_bytes(Path(config["inputs"]["iob_seed"]).read_bytes())
                script = root / "stages.ps1"
                script.write_text(r"""param($Repo,$Python,$Root,$Current,$Parent,$Case,$Metadata,$SourceReceipt)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
$OutputEncoding=[Text.UTF8Encoding]::new($false)
$repoRoot=$Repo;$script:pythonRoot=$Repo;$python=$Python
$simion=if($Case-eq'zero'){Join-Path $Root 'missing_simion.exe'}else{$Python}
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
""" + path_import + r"""
$helperAst=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Repo 'common/resource_budget_support.ps1'),[ref]$null,[ref]$null)
$helper=$helperAst.Find({param($node) $node-is[Management.Automation.Language.FunctionDefinitionAst]-and$node.Name-eq'Invoke-ObservedPreparationFailureDrain'},$true)
Invoke-Expression $helper.Extent.Text
$helper=$helperAst.Find({param($node) $node-is[Management.Automation.Language.FunctionDefinitionAst]-and$node.Name-eq'Invoke-SimionFormalObservation'},$true)
Invoke-Expression $helper.Extent.Text
$helper=$helperAst.Find({param($node) $node-is[Management.Automation.Language.FunctionDefinitionAst]-and$node.Name-eq'Invoke-SimionBatchPhase'},$true)
Invoke-Expression $helper.Extent.Text

$runDir=$Current;$runConfig=Join-Path $Current run_config.json
$resultDir=Join-Path $Current results;$logDir=Join-Path $Current logs;$solverDir=Join-Path $Current inputs
$artifactSolverDir=$solverDir;$package=@{input_dir=$solverDir;artifact_run_dir=$Current;run_dir=$Current}
$compositionPlanLocal=Join-Path $solverDir 'oa_mr_composition_plan.json'
$scopePath=Join-Path $solverDir 'oa_mr_local_scope.json'
$localScopeLocal=if(Test-Path -LiteralPath $scopePath){$scopePath}else{$null}
$checkpointConfig=Get-Content $runConfig -Raw|ConvertFrom-Json -AsHashtable
$trial=Get-Content $checkpointConfig.inputs.trial_materialization -Raw|ConvertFrom-Json -Depth 100
$staticFieldLocal=$checkpointConfig.inputs.static_field_binding;$FieldBindingPath=$staticFieldLocal
$staticFieldBinding=Get-Content $Metadata -Raw|ConvertFrom-Json -Depth 100
$staticFieldRequested=$true;$staticFieldMode='native_static_pa';$isBunchFlight=$true
$BatchContinuationRunPath=if($Case-eq'fresh'){''}else{$Parent}
$continuationParent=$Parent
$batchPlanPath=Join-Path $resultDir simion_execution_batch_plan.json
$runtimeDispatchPlanPath=Join-Path $resultDir dispatch.json
$dispatchRequestPath=$null;$resourceProfilesPath=$null;$batchContinuationPlan=$null;$batchContinuationPlanPath=$null
$batchResourceUsagePath=Join-Path $logDir usage.json
$batchRuntimeRoot=$null;$batchRecords=@{};$checkpointOutputs=[Collections.Generic.List[string]]::new();$nativeOperations=[Collections.Generic.List[object]]::new();$ResultPath='';$frozenEntryRecord=$null;$contract=$Metadata
$staticPaGuards=[Collections.Generic.List[IO.FileStream]]::new()
$bunchSourceLocal=$SourceReceipt;$bunchSourceContract=Get-Content $SourceReceipt -Raw|ConvertFrom-Json
$bunchSelectionRequested=$false;$RetainGuiWorkbench=$Case-eq'gui_missing';$retainGuiWorkbenchFiles=$RetainGuiWorkbench
$ownsHostResourceLease=$false;$resourceLease=@{};$ownsCapacitySession=$false
$writerCompletion=[pscustomobject]@{stopped=$true}
$capacitySession=@{committed_new_bytes=26214400};$trajectoryRecording=$null
$NativeCorridorRuntimeSession=if($Case-eq'zero'){@{caller_owned=$true;directory=$Root}}else{$null}
$nativeRuntimeCheckpointPath=$null
if($null-ne$NativeCorridorRuntimeSession){$retainGuiWorkbenchFiles=$true}
$nativeCorridorRun=$null;$nativeBankGeneration=$null;$nativeBankKey=$null
$fixedMirrorStripeAuthority=$null;$mirrorVoltageVariation=$null;$bunchSourceReceipt=$SourceReceipt
$globalFallbackAnalyzer=$staticFieldBinding.instances[0].pa_path;$sourceDetector=$staticFieldBinding.instances[3].pa_path
$fly2Input=Join-Path $Root source.fly2;$sidecar='operating.lua';$temporarySolverDir=$null
$RunId=$checkpointConfig.run_id;$script:vendor=[Collections.Generic.List[string]]::new()
foreach($name in @('reviewedContract','selectedContract','acceleratorGeometryContract','trajectoryContractSource',
 'mirrorSummary','stripeSummary','acceleratorReceipt','acceleratorProviderPlan','acceleratorResolvedCampaign',
 'fixedMirrorStripeLoader','trialTool','batchTool','programSource','waveformsSource','counterSource','mapSource','launcherSource')){
 Set-Variable -Name $name -Value $Metadata
}
function Update-ArtifactWorkflowCapacitySession {
 param($Python,$RepoRoot,$Session,$ProtectedPaths,$ProtectedCacheKeys,$RemainingCommittedNewBytes)
 return @{session=$Session;renewal=@{};admission_gate=@{}}
}
function Initialize-RunArtifactPowerShellOwner {return @{result_path='inert'}}
function Enter-HostResourceStage {throw 'Unexpected heavy admission'}
function Update-HostResourceStage {throw 'Unexpected heavy transition'}
function Test-RunFilesIdentical {param($Left,$Right) return [Linq.Enumerable]::SequenceEqual([byte[]][IO.File]::ReadAllBytes($Left),[byte[]][IO.File]::ReadAllBytes($Right))}
# Only the vendor boundary supplies inert completion output.
function Invoke-SimionStage {
 param($Stage,$Arguments,$ResourceLease,$RegisterHostProcess)
 if($Stage-ne'build_temporary_iob'){throw 'Unexpected vendor stage'}
 $script:vendor.Add($Stage)
 $Stage|Add-Content (Join-Path $Root vendor.txt)
 Copy-Item $fly2Input ([IO.Path]::ChangeExtension($temporaryIob,'.fly2'))
 'inert IOB'|Set-Content $temporaryIob
}
function Invoke-ResourceBudgetedProcesses {
 param($DispatchPlanPath,$RunDir,$UsagePath,$ProcessSpecifications,$ExistingProcessRecords,$OnProcessCompleted)
 $records=@(foreach($spec in $ProcessSpecifications){
  $index=[int]$spec.scheduler_batch.index;$count=[int]$spec.scheduler_batch.count
  $actual=(Get-Content $spec.argument_list[-1] -Raw|Select-String -Pattern 'standard_beam \{' -AllMatches).Matches.Count
  if($actual-ne$count){throw 'Real batch materialization did not preserve its count'}
  $script:vendor.Add('batch-'+$index)
  $lines=@(for($i=1;$i-le$count;$i++){"MRTOF_EVENT terminal ion=$i splat=1 t_us=2 turns=0 x_mm=0 y_mm=0 z_mm=0 vx_mm_us=0 vy_mm_us=0 vz_mm_us=0 central_crossings=0"})
  $lines+=@("status,Fly completed. $count splats",'IOB_FLIGHT: PASS iob=inert.iob')
  $lines|Set-Content -LiteralPath $spec.stdout
  # The inert vendor boundary now supplies the production scientific transport.
  # Historical parent logs above remain untouched and have no invented CSV.
  $rows=@(for($i=1;$i-le$count;$i++){[pscustomobject]@{kind='terminal';ion=$i;splat=1;t_us=2;turns=0;x_mm=0;y_mm=0;z_mm=0;vx_mm_us=0;vy_mm_us=0;vz_mm_us=0;central_crossings=0}})
  $rows|ConvertTo-Csv -NoTypeInformation|Set-Content -LiteralPath $spec.environment.MRTOF_SCIENTIFIC_EVENTS_PATH -Encoding utf8
  ''|Set-Content -LiteralPath $spec.stderr
   if($OnProcessCompleted){$null=& $OnProcessCompleted ([pscustomobject]@{specification=$spec;exit_code=0;completed=$true;root_process_id=44;root_process_started_at_utc_ticks=123})}
  @{exit_code=0}
 })
 return @{resource_budget_exceeded=$false;processes=$records}
}
# Exercise the owner map expressions and assignment loops, without binding the
# unrelated vendor inputs that the existing recovery fixture does not consume.
$tokens=$null;$errors=$null
$ownerAst=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Repo 'integrations/workflows/oa_mr/execute.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
function Register-AssemblyFixtureInputs {
 param([string]$Table,$Config)
 $assignment=$ownerAst.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq('$'+$Table)},$true)
 $map=$assignment.Find({param($n)$n-is[Management.Automation.Language.HashtableAst]},$true)
 $entries=@($map.KeyValuePairs|Where-Object{$_.Item1.Value-in@('composition_plan','local_scope')})
 if($entries.Count-ne2){throw "Assembly inputs missing from actual owner $Table"}
 $values=[ordered]@{}
 foreach($entry in $entries){$values[$entry.Item1.Value]=. ([scriptblock]::Create($entry.Item2.Extent.Text))}
 Set-Variable -Name $Table -Value $values
 $checkpointConfig=$Config;$config=$Config
 $loop=$ownerAst.Find({param($n)$n-is[Management.Automation.Language.ForEachStatementAst]-and$n.Extent.Text.Contains('$'+$Table+'.GetEnumerator()')},$true)
 if($null-eq$loop){throw "Actual owner input assignment loop missing: $Table"}
 . ([scriptblock]::Create($loop.Extent.Text))
}
Register-AssemblyFixtureInputs checkpointInputs $checkpointConfig
Write-RunJson -Path $runConfig -Depth 100 -Value $checkpointConfig
Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status checkpoint -Software @('inert publication fixture')|Out-Null
$checkpointAssemblyInputs=(Get-Content (Join-Path $Current run_manifest.json) -Raw|ConvertFrom-Json -AsHashtable).inputs
""" + python_helper + "\ntry{\n" + stages + r"""
 $config=Get-Content $runConfig -Raw|ConvertFrom-Json -AsHashtable
 Register-AssemblyFixtureInputs flightInputs $config
 if(-not$config.Contains('provenance')){$config['provenance']=[ordered]@{}}
""" + pa_provenance + r"""
 Write-RunJson -Path $runConfig -Depth 100 -Value $config
 $summary=Join-Path $resultDir summary.json
 Write-RunJson -Path $summary -Value @{status='success';qualification='inert_vendor_fixture__workflow_mechanism_only'}
 Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success -Software @('inert vendor fixture') -Outputs @($summary,$rawLog,$batchMergeReceipt)|Out-Null
 @{checkpoint_inputs=$checkpointAssemblyInputs;vendor=@($script:vendor);replay=@($replayBatchIndexes);shared_session=$NativeCorridorRuntimeSession;records=@($batchRecords.Values|ForEach-Object{@{index=$_.index;offset=$_.offset;count=$_.count;log=$_.stdout}})}|ConvertTo-Json -Depth 20 -Compress
} finally {
 foreach($guard in $staticPaGuards){$guard.Dispose()}
 foreach($path in @($temporarySolverDir,$batchRuntimeRoot)){
  if($null-ne$path-and(Test-Path $path)){Remove-Item -LiteralPath $path -Recurse -Force}
 }
}
""", encoding="utf-8")
                completed = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(script),
                    str(REPO), sys.executable, str(root), str(current), str(parent), case,
                    str(metadata_path), str(source_receipt)], cwd=REPO, capture_output=True, text=True,
                    encoding="utf-8", timeout=60)
                output = completed.stdout + completed.stderr
                if case in ("science_changed", "gui_missing", "mixed_missing"):
                    self.assertNotEqual(completed.returncode, 0, output)
                    self.assertNotIn("MRTOF_BATCH_LOG_MERGE=PASS", output)
                    self.assertFalse((root / 'vendor.txt').exists(), output)
                    self.assertEqual(parent_before, {path: path.read_bytes() for path in parent.rglob("*") if path.is_file()})
                    continue
                self.assertEqual(completed.returncode, 0, output)
                actual = json.loads(completed.stdout.splitlines()[-1])
                expected = [] if case == "zero" else ([2] if case == "mixed" else [1, 2])
                self.assertEqual(actual["replay"], expected)
                if case == "zero":
                    self.assertEqual(actual["shared_session"], dict(caller_owned=True, directory=str(root)))
                    self.assertFalse((root / "vendor.txt").exists())
                self.assertEqual(actual["vendor"], [] if not expected else
                                 ["build_temporary_iob", *[f"batch-{i}" for i in expected]])
                self.assertEqual(sorted((r["index"], r["offset"], r["count"]) for r in actual["records"]),
                                 [(1, 0, 1), (2, 1, 2)])
                manifest = json.loads((current / "run_manifest.json").read_text(encoding="utf-8-sig"))
                self.assertEqual(manifest["status"], "success")
                for inputs in (actual['checkpoint_inputs'],manifest['inputs']):
                    assembly_inputs={'composition_plan':current/'inputs/oa_mr_composition_plan.json'}
                    if local_scope is not None:
                        assembly_inputs['local_scope']=current/'inputs/oa_mr_local_scope.json'
                    else:
                        self.assertNotIn('local_scope',inputs)
                        self.assertFalse((current/'inputs/oa_mr_local_scope.json').exists())
                    for name,path in assembly_inputs.items():
                        self.assertEqual(inputs[name],file_record(path))
                        verify_record(name,inputs[name])
                        original=path.read_bytes()
                        try:
                            # Same-size corruption proves hash binding, not
                            # merely file existence or a byte-count check.
                            path.write_bytes(original.replace(b'oa',b'ox',1))
                            self.assertNotEqual(path.read_bytes(),original)
                            with self.assertRaises(AssertionError):verify_record(name,inputs[name])
                        finally:path.write_bytes(original)
                final_config = json.loads(config_path.read_text(encoding="utf-8-sig"))
                self.assertEqual(final_config["provenance"]["pa_bindings"]["identity_authority_input"], "static_field_binding")
                self.assertEqual(final_config["provenance"]["pa_bindings"]["payload_consumed"], bool(expected))
                if case != "fresh":
                    self.assertEqual(manifest["inputs"]["reused_batch_001_log"]["path"],
                                     str(parent / "logs/native_two_prism_flight__batch01.log"))
                    self.assertFalse(any(Path(r["path"]).is_relative_to(parent) for r in manifest["outputs"]))
                from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import read_scientific_events
                merged_path = current / "logs/native_two_prism_flight.log"
                merged = merged_path.read_text(encoding="utf-8")
                merged_receipt = json.loads((results / "batch_log_merge_receipt.json").read_text(encoding="utf-8"))
                events, completions, _ = read_scientific_events(merged_path,
                    scientific_event_output=merged_receipt["scientific_event_output"])
                self.assertEqual([int(event["ion"]) for event in events if event["kind"] == "terminal"], [1, 2, 3])
                self.assertEqual([int(event["splat"]) for event in events if event["kind"] == "terminal"], [1, 1, 1])
                self.assertEqual(completions[0].splats, 3)
                self.assertNotIn("MRTOF_EVENT", merged)
                self.assertIn("Fly completed. 3 splats", merged)
                self.assertEqual(parent_before, {path: path.read_bytes() for path in parent.rglob("*") if path.is_file()})

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_native_payload_identity_is_checked_inside_guards_before_vendor(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_static_field_binding import NativeStaticBindingTest
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import load_binding
        source = RUNNER.read_text()
        start = source.index("    $guardPaths=@($staticFieldBinding.instances")
        block = source[start:source.index("  $iobAnalyzerInput=$globalFallbackAnalyzer", start)]
        with TemporaryDirectory() as directory:
            root = Path(directory)
            descriptor = NativeStaticBindingTest().fixture(root)
            binding_path = root / "binding.json"
            binding_path.write_text(json.dumps(descriptor))
            metadata_path = root / "metadata.json"
            metadata_path.write_text(json.dumps(load_binding(binding_path)))
            script = root / "native_boundary.ps1"
            script.write_text(r"""
param($Python,$Repo,$Binding,$Metadata)
$ErrorActionPreference='Stop'
$staticPaGuards=[Collections.Generic.List[IO.FileStream]]::new()
$staticFieldBinding=Get-Content $Metadata -Raw|ConvertFrom-Json -Depth 100
$staticFieldRequested=$true;$staticFieldMode='native_static_pa';$staticFieldLocal=$Binding
function Invoke-ProjectPython {param($Arguments)
 foreach($stream in $staticPaGuards){
  $blocked=$false
  try{$writer=[IO.File]::Open($stream.Name,[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::None);$writer.Dispose()}catch [IO.IOException]{$blocked=$true}
  if(-not$blocked){throw 'Native verification preceded its payload read guard'}
 }
 $env:PYTHONPATH=$Repo
 & $Python -B @Arguments
 if($LASTEXITCODE-ne0){throw 'Actual native payload validation rejected the input'}
}
try {
 if($true){
""" + block + r"""
 'VENDOR_BOUNDARY_REACHED'
} finally {foreach($stream in $staticPaGuards){$stream.Dispose()}}
""", encoding="utf-8")
            payload = Path(descriptor["parent"]["pa_path"])
            original = payload.read_bytes()
            for case in ("valid", "changed", "missing"):
                with self.subTest(case=case):
                    if case == "changed": payload.write_bytes(b"PA")
                    elif case == "missing": payload.unlink()
                    completed = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(script),
                        sys.executable, str(REPO), str(binding_path), str(metadata_path)],
                        cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=30)
                    output = completed.stdout + completed.stderr
                    if case == "valid":
                        self.assertEqual(completed.returncode, 0, output)
                        self.assertIn("VENDOR_BOUNDARY_REACHED", output)
                    else:
                        self.assertNotEqual(completed.returncode, 0, output)
                        self.assertNotIn("VENDOR_BOUNDARY_REACHED", output)
                    payload.write_bytes(original)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_real_batch_record_appends_outputs_without_losing_frozen_config(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            script = root/"batch_config.ps1"
            script.write_text(r'''param($Entry,$Repo,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
$ast=[Management.Automation.Language.Parser]::ParseFile($Entry,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'New-MrtofBatchRecord'},$true)
Invoke-Expression $node.Extent.Text
Remove-Variable config -ErrorAction SilentlyContinue
$runConfig=Join-Path $Root 'run_config.json';$batchRuntimeRoot=Join-Path $Root 'runtime'
$package=@{artifact_run_dir=$Root};$logDir=$Root;$temporaryIob='inert-not-flown.iob'
$bunchSelectionRequested=$false;$bunchSourceLocal='inert-source-receipt';$trial=[pscustomobject]@{trajectory_recording=$null}
Write-RunJson -Path $runConfig -Value @{inputs=@{frozen='original-source'};provenance=@{source='unchanged'};parameters=@{sentinel=@{ids=@(7,9001);clock='original'};scientific_event_outputs=@{'7'=@{events_path='prior-owned-output'}}}}
function Invoke-ProjectPython {param($Arguments)
 if($Arguments[2]-ne'materialize'){throw 'Unexpected native or science operation'}
 # The source adapter is an inert boundary here. Only the real owner's config
 # persistence and path declarations are tested; no solver/file is fabricated.
}
$first=New-MrtofBatchRecord -PlannedBatch @{index=1;count=2;particle_id_min=1;particle_id_max=2}
$between=Get-Content $runConfig -Raw|ConvertFrom-Json -AsHashtable
$between.inputs.checkpoint_added='preserve-latest-checkpoint';Write-RunJson -Path $runConfig -Value $between
$second=New-MrtofBatchRecord -PlannedBatch @{index=2;count=3;particle_id_min=3;particle_id_max=5}
$actual=Get-Content $runConfig -Raw|ConvertFrom-Json -AsHashtable
if($actual.parameters.sentinel.clock-ne'original'-or($actual.parameters.sentinel.ids-join',')-ne'7,9001'-or$actual.inputs.frozen-ne'original-source'-or$actual.inputs.checkpoint_added-ne'preserve-latest-checkpoint'-or$actual.provenance.source-ne'unchanged'){throw 'Batch record replaced frozen inputs, clock or current checkpoint'}
if($actual.parameters.scientific_event_outputs.Count-ne3-or$actual.parameters.scientific_event_outputs['7'].events_path-ne'prior-owned-output'){throw 'Existing output declaration was lost'}
foreach($record in @($first,$second)){
 $stored=$actual.parameters.scientific_event_outputs[[string]$record.index]
 if($stored.events_path-cne$record.scientific_event_output.events_path-or$stored.Contains('trajectory_path')){throw 'Actual per-batch outputs differ from stored configuration'}
}
'BATCH_CONFIG_APPEND=PASS'
''', encoding="utf-8")
            result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(script), str(RUNNER), str(REPO), directory],
                cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn("BATCH_CONFIG_APPEND=PASS", result.stdout)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_new_owner_freezes_and_executes_detached_provider(self):
        source = RUNNER.read_text(encoding="utf-8")
        start = source.index("  $failureStage='freeze_executable_dependencies'")
        freeze = source[start:source.index("  if($null-ne$nativeRuntimeCheckpointPath){", start)]
        materialize_start = source.index("  $acceleratorInstance='3'")
        materialize = source[materialize_start:source.index("  $trial=Get-Content", materialize_start)]
        copy_builder = next(line for line in source.splitlines()
                            if "-Label 'native corridor IOB builder'" in line)
        build_start = source.index("    $buildArguments=@('--nogui','--noprompt','lua',")
        build = source[build_start:source.index("    $failureStage='build_temporary_iob'", build_start)]
        stage_fixture = r"""
# Inert physics/vendor fixture: the real frozen argparse and priority renderer
# run; neither a native field nor an IOB is built.
foreach($fixtureBunch in @($false,$true)){
foreach($staticFieldRequested in @($false,$true)){
 $fieldKind=if($staticFieldRequested){'static'}else{'native'}
 $solverDir=Join-Path $Root ($fieldKind+'_'+[string]$fixtureBunch)
 New-Item -ItemType Directory -Path $solverDir|Out-Null
 $providerSimionRoot=Join-Path $script:pythonRoot 'projects/parallel_mirror_dual_stripe_mr_tof/simion'
 $contract='contract';$acceleratorGeometry='geometry';$trajectoryContract='numerics';$reviewed='reviewed'
 $mirrorLocal='mirror';$stripeLocal='stripe';$acceleratorLocal='accelerator'
 $acceleratorProviderPlanLocal='provider';$compositionPlanLocal='composition-plan';$localScopeLocal=$null;$acceleratorResolvedCampaignLocal='campaign'
 $Prism1VoltageV=190.;$Prism2VoltageV=-186.;$AcceleratorSourceYOffsetMm=0.
 $Stripe1VoltageV=$null;$fixedMirrorStripeAuthorityLocal=$null;$mirrorVoltageVariationLocal=$null
 $bunchSourceContract=if($fixtureBunch){[pscustomobject]@{fixture_only=$true}}else{$null}
 $bunchSourceLocal=if($fixtureBunch){Join-Path $solverDir 'inert_bunch.json'}else{$null}
 if($fixtureBunch){'{"fixture_only":true}'|Set-Content -LiteralPath $bunchSourceLocal}
 $bunchSelectionRequested=$false;$TrajectoryStepScale=1.
 $PulseAcceleratorUntilInitialExit=$false;$AcceleratorSafeExitOnly=$false
 $acceleratorPulseScheduleLocal=$null;$TrajectoryProfileId=''
 $fly2Input=Join-Path $solverDir 'source.fly2';$sidecar=Join-Path $solverDir 'operating.lua'
 $trialReceipt=Join-Path $solverDir 'trial.json';$staticFieldLocal=Join-Path $solverDir 'static_field_binding.json'
 if($staticFieldRequested){'{}'|Set-Content $staticFieldLocal}else{
  $groups=@(@(17),@(16),@(13,14),@(11,12),@(5,10),@(4,9),@(3,8),@(2,7))
  $recipes=@(for($i=0;$i-lt8;$i++){@{local_id=$i+1;physical_ids=@($groups[$i])}})
  @{identity=@{basis_namespace=@{response_recipe=@{response_recipes=$recipes}}}}|ConvertTo-Json -Depth 20|Set-Content (Join-Path $solverDir 'native_corridor_bank_cache_manifest.json')
 }
 function Format-InvariantNumber {param($Value) [string]$Value}
 function Copy-RequiredInput {param($Source,$Destination,$Label)
  if([IO.Path]::GetFileName($Source)-eq'native_corridor_priority_contract.lua'){throw 'Priority template fallback'}
  Copy-Item -LiteralPath $Source -Destination $Destination;return $Destination
 }
 function Invoke-ProjectPython {param($Arguments)
  $env:PYTHONPATH=$script:pythonRoot
  & $Python -B -s $Fixture @Arguments
  if($LASTEXITCODE-ne0){throw 'Inert physics fixture or real CLI dispatch failed'}
 }
""" + copy_builder + "\n" + materialize + r"""
 $receipt=Get-Content -LiteralPath $trialReceipt -Raw|ConvertFrom-Json
 $privateIobSeed='seed';$iobAnalyzerInput='analyzer';$nativeControllerForIob='corridor'
 $iobAcceleratorInput='accelerator';$iobDetectorInput='detector';$temporaryIob='not-built.iob'
 $iobProgramPath='program';$iobFly2Path=$fly2Input;$nativeOriginArguments=@(0,0,0,0,0,0,0,0,0,0,0,0)
""" + build + r"""
 # Inert vendor boundary consumes exactly the real runner's builder arguments.
 $priority=$buildArguments[[array]::IndexOf($buildArguments,'--')+11]
 if($priority-ne$receipt.native_corridor_priority_contract.path){throw 'Builder consumed another priority'}
 if($buildArguments[3]-ne(Join-Path $solverDir 'build_native_corridor_iob.lua')){throw 'Wrong builder'}
 $text=Get-Content -LiteralPath $priority -Raw
 if(-not$text.Contains('native_corridor')){throw 'Generated four-slot priority missing'}
 if($staticFieldRequested){
  if($text.Contains('corridor_voltage_groups')){throw 'Static field inherited native groups'}
 }elseif(-not$text.Contains('{ 17 }')){throw 'Priority did not use the actual frozen bank groups'}
}
}
'INERT_FROZEN_PRIORITY_ROUTE_PASS'
"""
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / "inert_materializer.py"
            fixture.write_text(r"""# Test-only inert physics stage, using the actual frozen parser/priority renderer.
import json
from pathlib import Path
import sys
from unittest.mock import patch
from common.contracts.write_run_manifest import file_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis import two_prism_simion_trial as module
assert Path(module.__file__).is_relative_to(Path.cwd())
assert sys.argv[1:3] == ['-m', module.__name__]
sys.argv = [module.__name__, *sys.argv[3:]]
def inert_materialize(**arguments):
    assert arguments['batch_scientific_event_locators'] is (arguments['bunch_source_receipt_path'] is not None)
    sidecar = arguments['sidecar_path']
    manifest = arguments['native_corridor_cache_manifest_path']
    if arguments['field_binding_path'] is None:
        assert manifest == sidecar.parent / 'native_corridor_bank_cache_manifest.json'
        data = json.loads(manifest.read_text(encoding='utf-8-sig'))
    else:
        assert manifest is None
        assert arguments['field_binding_path'] == sidecar.parent / 'static_field_binding.json'
        data = None
    priority = sidecar.parent / 'native_corridor_priority_contract.lua'
    assert not priority.exists()
    priority.write_text(module.native_corridor_priority_lua(data), encoding='utf-8')
    result = dict(inert_fixture=True, prism_voltages_v=[arguments['prism_1_v'], arguments['prism_2_v']],
                  native_corridor_priority_contract=file_record(priority))
    arguments['receipt_path'].write_text(json.dumps(result), encoding='utf-8')
    return result
with patch.object(module, 'materialize_trial', side_effect=inert_materialize):
    module.main()
""", encoding="utf-8")
            script = root / "freeze.ps1"
            script.write_text(r"""param($Repo,$Root,$Python,$Owner,$Fixture)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$repoRoot=$Repo;$runDir=$Root;$projectId='instrument_assembly';$ContractPath='';$continuationParent=$null
$runConfig=Join-Path $Root 'run_config.json'
@{project=$Owner;mode='oa_mr';inputs=@{}}|ConvertTo-Json|Set-Content $runConfig
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
. (Join-Path $Repo 'integrations/runtime/dependencies.ps1')
""" + freeze + r"""
$config=Get-Content -LiteralPath $runConfig -Raw|ConvertFrom-Json -AsHashtable
if($config.inputs.code_inventory-ne$frozen.code_inventory_path){throw 'Frozen code identity was lost'}
$env:PYTHONPATH=$null
Push-Location -LiteralPath $script:pythonRoot
try{
 & $Python -B -s -c "from pathlib import Path; from projects.parallel_mirror_dual_stripe_mr_tof.analysis import two_prism_simion_trial, mrtof_batch_flight; assert Path(two_prism_simion_trial.__file__).is_relative_to(Path.cwd()); assert Path(mrtof_batch_flight.__file__).is_relative_to(Path.cwd())"
 if($LASTEXITCODE-ne0){throw 'Detached provider import failed'}
 & $Python -B -s -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial recording-config --contract (Join-Path $script:pythonRoot 'projects/parallel_mirror_dual_stripe_mr_tof/config/simion_candidate_two_zone.json')
 if($LASTEXITCODE-ne0){throw 'Detached provider compilation failed'}
 & $Python -B -s -c "import json; from pathlib import Path; from common.contracts.particle_count_policy import validate_standard_particle_count; from projects.parallel_mirror_dual_stripe_mr_tof.analysis.accelerator_component_requirements import build_two_zone_accelerator_requirements; validate_standard_particle_count(100); c=json.loads(Path('projects/parallel_mirror_dual_stripe_mr_tof/config/simion_candidate_two_zone.json').read_text(encoding='utf-8')); assert build_two_zone_accelerator_requirements(c)['variant_id']=='two_zone'"
 if($LASTEXITCODE-ne0){throw 'Detached source policy or physical provider requirements failed'}
""" + stage_fixture + r"""
}finally{Pop-Location}
'OA_MR_FROZEN_PROVIDER_PASS'
""", encoding="utf-8")
            for owner in ("instrument_assembly", "parallel_mirror_dual_stripe_mr_tof"):
                with self.subTest(owner=owner):
                    output = root / owner
                    output.mkdir()
                    result = subprocess.run(
                        ["pwsh", "-NoProfile", "-File", str(script), str(REPO), str(output), sys.executable, owner, str(fixture)],
                        cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=60,
                    )
                    if owner == "instrument_assembly":
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertIn("OA_MR_FROZEN_PROVIDER_PASS", result.stdout)
                        self.assertIn("INERT_FROZEN_PRIORITY_ROUTE_PASS", result.stdout)
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("OA-MR run owner or mode differs", result.stderr)
                        self.assertEqual(json.loads((output / "run_config.json").read_text(encoding="utf-8-sig"))["inputs"], {})

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_new_run_owner_and_source_owners_are_separate(self):
        source = RUNNER.read_text(encoding="utf-8")
        create = source[source.index("$package=New-RunPackage"):source.index("$runDir=$package.run_dir")]
        identities = "\n".join(line for line in source.splitlines()
                               if line.startswith(("$projectId=", "$providerProjectId=")))
        checks = "\n".join(line.strip().rstrip("`") for line in source.splitlines()
                            if "& $python" in line and "--require-project $providerProjectId" in line)
        # Execute the real command blocks; a foreign source must fail before a
        # materializer can turn it into a scientifically different source.
        command = r"""
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$python='Check-Source';$repoRoot='repo';$workspaceRoot='workspace';$RunId='fixture'
$trajectoryRetentionClass='compact';$trajectoryRetentionReason='fixture'
$bunchSourceManifest='source';$mirrorManifest='source';$stripeManifest='source';$manifest='source';$nativeBankManifest='source'
function New-RunPackage {
 param($Python,$RepoRoot,$ArtifactRoot,$RunId,$Project,$Mode,$Software,[switch]$RetentionContractEnabled,$RetentionClass,$RetentionReason,[switch]$CapacityLedgerLifecycleEnabled,$AdditionalDirectories,[switch]$UseShortExecutionPath)
 if($Project-ne'instrument_assembly'-or$Mode-ne'oa_mr'-or$ArtifactRoot-notlike'*instrument_assembly'){throw 'Incorrect new run identity'}
 return @{project=$Project;mode=$Mode}
}
function Check-Source {
 $required=$args[[array]::IndexOf($args,'--require-project')+1]
 if($required-ne$script:sourceOwner){throw 'SOURCE_OWNER_REJECTED'}
}
""" + identities + "\n" + create + "\n" + r"""
$script:sourceOwner='parallel_mirror_dual_stripe_mr_tof'
""" + checks + "\n" + r"""
$script:sourceOwner='instrument_assembly'
$caught=$false
try{
""" + checks + r"""
}catch{if($_.Exception.Message-ne'SOURCE_OWNER_REJECTED'){throw};$caught=$true}
if(-not$caught){throw 'Foreign source owner was accepted'}
'OWNER_BOUNDARIES_PASS'
"""
        result = subprocess.run(["pwsh", "-NoProfile", "-Command", command],
                                cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OWNER_BOUNDARIES_PASS", result.stdout)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_preflight_checkpoint_refresh_only_after_formal_observation(self):
        source = RUNNER.read_text(encoding="utf-8-sig")
        start = source.index("    $prepareRemaining={")
        block = source[start:source.index("    $writerCompletion.stopped=$false", start)]
        initial = {"inputs": {"simion_execution_batch_plan": "frozen-plan.json"},
                   "parameters": {"unchanged": "frozen source and field"}}
        cases = (
            ("exact", None, [1, 2], [1, 2], initial, False, [1, 2], 0),
            ("formal_index_zero", 0, [0, 1, 2], [0, 1, 2], initial, False, [1, 2], 1),
            ("continuation_replay", None, [1, 2], [2], initial, False, [2], 0),
            ("continuation_formal", 1, [1, 2], [2], initial, False, [2], 1),
            ("empty", None, [], [], None, False, [], 0),
            ("missing_inputs", 0, [0, 1], [0, 1], {}, False, None, 0),
            ("write_failure", 0, [0, 1], [0, 1], initial, True, None, 1),
        )
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for label, formal, indices, replay, config, write_failure, pending, writes in cases:
                with self.subTest(case=label):
                    run_config, batch_plan = root / "run_config.json", root / "batch_plan.json"
                    if run_config.exists():
                        run_config.unlink()
                    if config is not None:
                        run_config.write_text(json.dumps(config), encoding="utf-8")
                    before = run_config.read_bytes() if run_config.exists() else None
                    batch_plan.write_text(json.dumps({"batches": [{"index": i} for i in indices]}),
                                          encoding="utf-8")
                    formal_value = "$null" if formal is None else str(formal)
                    script = (
                        "$ErrorActionPreference='Stop';Set-StrictMode -Version Latest;"
                        f"$runConfig={quote(run_config)};$batchPlanPath={quote(batch_plan)};"
                        f"$runDir={quote(root)};$formalBatchIndex={formal_value};"
                        f"$package=@{{artifact_run_dir={quote(root)}}};"
                        + ("$batchContinuationPlan=@{};" if label == "continuation_formal" else "$batchContinuationPlan=$null;")
                        +
                        f"$replayBatchIndexes=@({','.join(map(str, replay))});"
                        "$batchRecords=@{};"
                        f"foreach($index in @({','.join(map(str, indices))}))"
                        "{$batchRecords[[int]$index]=@{index=[int]$index}};"
                        "$checkpointOutputs=@('initial-output.json');$python='unused';$repoRoot='unused';"
                        "$script:writes=0;$script:manifests=0;"
                        "function Write-RunJson {param($Path,$Value) $script:writes++;"
                        + ("throw 'WRITE_FAILURE';" if write_failure else
                           "$Value|ConvertTo-Json -Depth 20|Set-Content -LiteralPath $Path;")
                        + "};function Write-VerifiedRunManifest {param($Python,$RepoRoot,$RunConfig,"
                        "$Manifest,$Status,$Software,$Outputs) $script:manifests++;"
                        "if($Status-ne'checkpoint'-or$Outputs[0]-ne'initial-output.json'){throw 'identity changed'}};"
                        "function Get-MrtofBatchProcessSpecification {param($Record) $Record.index};"
                        "try {\n" + block + "\n$prepared=& $prepareRemaining $null;$pendingSpecs=@($prepared.pending)\n} catch {"
                        "@{error=$_.Exception.Message;writes=$script:writes;manifests=$script:manifests}"
                        "|ConvertTo-Json -Compress;exit 1};"
                        "@{writes=$script:writes;manifests=$script:manifests;pending=@($pendingSpecs)}"
                        "|ConvertTo-Json -Compress"
                    )
                    script_path = root / "preflight.ps1"
                    script_path.write_text(script, encoding="utf-8")
                    result = subprocess.run(
                        ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(script_path)],
                        cwd=RUNNER.parents[3], capture_output=True, text=True, encoding="utf-8", timeout=30,
                    )
                    actual = json.loads(result.stdout.splitlines()[-1])
                    self.assertEqual(actual["writes"], writes)
                    if pending is None:
                        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertEqual(actual["manifests"], 0)
                        if write_failure:
                            self.assertEqual(actual["error"], "WRITE_FAILURE")
                    else:
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertEqual(actual["manifests"], writes)
                        self.assertEqual(actual["pending"], pending)
                        if formal is not None:
                            expected_plan = batch_plan if label == "continuation_formal" else root / "results/simion_execution_batch_plan.json"
                            expected = {**initial, "inputs": {"simion_execution_batch_plan": str(expected_plan)}}
                            self.assertEqual(json.loads(run_config.read_text(encoding="utf-8-sig")), expected)
                        else:
                            self.assertEqual(run_config.read_bytes() if run_config.exists() else None, before)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_summary_counts_final_batches_after_first_observation_replans(self):
        source = RUNNER.read_text(encoding="utf-8")
        statement = next(line for line in source.splitlines() if "$summaryValue.batch_recovery=" in line)
        for replay, expected in (([1, 2], (2, 0)), ([], (0, 2)), ([2], (1, 1))):
            with self.subTest(replay=replay):
                script = (
                    "$ErrorActionPreference='Stop';Set-StrictMode -Version Latest;"
                    "$isBunchFlight=$true;$summaryValue=@{};$batchContinuationPlanPath=$null;"
                    "$initialBatchPlan=@{batches=@(@{index=1})};"
                    "$finalBatchPlan=@{batches=@(@{index=1},@{index=2})};"
                    f"$replayBatchIndexes=@({','.join(map(str, replay))});"
                    + statement + ";$summaryValue.batch_recovery|ConvertTo-Json -Compress"
                )
                result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                    cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                recovery = json.loads(result.stdout)
                self.assertEqual((recovery["native_batches_executed"], recovery["reused_batches"]), expected)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_recovery_plan_uses_durable_owner_after_execution_alias_is_removed(self):
        source = RUNNER.read_text(encoding="utf-8")
        assignment = next(line for line in source.splitlines() if "$continuationRoot=Join-Path" in line)
        with TemporaryDirectory() as directory:
            owner = Path(directory) / "durable owner"
            alias = Path(directory) / "removed alias"
            quote = lambda path: "'" + str(path).replace("'", "''") + "'"
            script = ("$ErrorActionPreference='Stop';"
                      f"$package=@{{artifact_run_dir={quote(owner)};input_dir={quote(alias)}}};"
                      + assignment + ";$continuationRoot")
            result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(Path(result.stdout.strip()), owner / "inputs/mrtof_batch_continuation")
            self.assertFalse(alias.exists())

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_pose_consumes_materialized_receipt_without_reopening_author_inputs(self):
        source = RUNNER.read_text(encoding="utf-8")
        start = source.index("  $posePath=Join-Path $resultDir 'resolved_iob_pose.json'")
        block = source[start:source.index("  # The native-system bundle", start)]
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for authority in ("reviewed_analyzer_contract", "native_static_pa_frozen_resolved_geometry",
                              "comsol_static_scalar_v_frozen_resolved_geometry"):
                with self.subTest(authority=authority):
                    expected = {"origins_mm": {"analyzer": [0, -242, -425], "accelerator": [0, -72.25, -6],
                                               "detector": [-10, -20, -30]},
                                "mesh_mm_per_gu": {"analyzer": [1, 1, 1], "accelerator": [.25, .25, .25],
                                                   "detector": [.5, .5, .5]},
                                "analyzer_geometry_authority": authority,
                                "accelerator_geometry_authority": "oa_provider_plan__mr_configurable_clearance_gated_y_pose",
                                "detector_return_policy_authority": "current_trajectory_contract"}
                    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
                    script = (
                        "$ErrorActionPreference='Stop';Set-StrictMode -Version Latest;"
                        f"$resultDir={quote(root)};"
                        f"$trial={quote(json.dumps({'resolved_iob_pose': expected}))}|ConvertFrom-Json -Depth 100;"
                        "function Write-RunJson {param($Path,$Depth,$Value) $Value|ConvertTo-Json -Depth 100|Set-Content -LiteralPath $Path};"
                        "function Invoke-ProjectPython {throw 'Unexpected geometry compilation'};\n"
                        + block + "\n$pose|ConvertTo-Json -Depth 100 -Compress"
                    )
                    completed = subprocess.run(["pwsh", "-NoProfile", "-Command", script],
                        cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=30)
                    self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                    self.assertEqual(json.loads(completed.stdout.splitlines()[-1]), expected)
                    self.assertEqual(json.loads((root / "resolved_iob_pose.json").read_text(encoding="utf-8-sig")), expected)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_final_config_preserves_native_nested_geometry_and_stopping_identity(self):
        numerics = {"solver": "SIMION2020", "refine_stopping": "contract_convergence",
                    "convergence_v": 1e-5, "surface": "fractional", "boundary_mode": "grounded_enclosure"}
        window = {"native_solver_numerics": {**numerics, "boundary_mode": "x_mirror_five_faces"},
                  "authority": {"assembly": {"accelerator_resolved_electrodes": {
                      "grid_supports": [{"aperture_box_mm": {"x_min_mm": -21, "x_max_mm": 21},
                                         "ideal_sheet_mm": {"z_mm": 30}}]}}},
                  "geometry": {"prism_electrodes": [{"parts": [{
                      "polygon_yz_mm": [[0, 1], [2, 3]], "x": [0, 1]}]}]}}
        value = {"inputs": {"static_field_dependencies": {
                    "native_solver_numerics": numerics, "refinement_windows": [window]}},
                 "provenance": {"upstream_manifest_verification": {"static_field": {"windows": [window]}}}}
        publication = next(line.strip() for line in RUNNER.read_text(encoding="utf-8-sig").splitlines()
                           if line.strip().startswith("Write-RunJson -Path $runConfig -Value $config"))
        writer = RUNNER.parents[3] / "common/contracts/run_artifact_support.ps1"
        with TemporaryDirectory() as directory:
            source, target = Path(directory) / "input.json", Path(directory) / "run_config.json"
            source.write_text(json.dumps(value), encoding="utf-8")
            quote = lambda path: "'" + str(path).replace("'", "''") + "'"
            command = (f". {quote(writer)}\n"
                       f"$config=Get-Content -Raw -LiteralPath {quote(source)}|ConvertFrom-Json -Depth 100\n"
                       f"$runConfig={quote(target)}\n{publication}")
            result = subprocess.run(["pwsh", "-NoProfile", "-Command", command], cwd=RUNNER.parent,
                                    capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8-sig")), value)
            self.assertNotIn("truncated", result.stdout.lower())

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_standard_source_diagnostic_is_one_postprocess_output(self):
        source = RUNNER.read_text(encoding="utf-8-sig")
        start = source.index("  $sourceTimingDiagnostic=$null;")
        end = source.index("  $manifestOutputs=@", start)
        block = source[start:end]
        self.assertGreater(start, source.rindex("Write-RunJson -Path $runConfig -Value $config", 0, start))
        self.assertLess(end, source.rindex("Complete-RunArtifactPowerShellOwner"))
        publication = next(line for line in source.splitlines()
                           if line.strip().startswith("if($null-ne$sourceTimingDiagnostic){$manifestOutputs"))
        with TemporaryDirectory() as directory:
            for bunch, count, safe_exit, subset, minimum_id, expected in (
                (True, 13, False, False, 1, 1), (False, 1, False, False, 1, 0),
                (True, 13, True, False, 1, 0), (True, 12, False, True, 2, 0),
                (True, 100, False, True, 1, 1), (True, 1, False, True, 1, 0),
            ):
                with self.subTest(bunch=bunch, count=count, safe_exit=safe_exit, subset=subset, minimum_id=minimum_id):
                    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
                    script = (
                        "$ErrorActionPreference='Stop';Set-StrictMode -Version Latest;"
                        + f"$resultDir={quote(directory)};$logDir=$resultDir;"
                        + f"$isBunchFlight=${str(bunch).lower()};$isSafeExitOnly=${str(safe_exit).lower()};"
                        + f"$bunchSelectionRequested=${str(subset).lower()};"
                        + f"$BunchParticleIdMin={minimum_id};$trial=@{{source_particle_count={count}}};"
                        + "$runConfig='final-config.json';$observation='observation.json';"
                        + "$batchMergeReceipt='merge.json';$global:calls=0;$global:received=@();"
                        + "function Invoke-ProjectPython {param($Arguments) $global:calls++;"
                        + "$global:received=$Arguments}\n"
                        + block + "\n$manifestOutputs=@('observation.json');" + publication
                        + "\n@{calls=$global:calls;args=$global:received;outputs=$manifestOutputs;"
                        + "log_exists=($null-ne$sourceTimingDiagnosticLog-and(Test-Path -LiteralPath $sourceTimingDiagnosticLog));"
                        + "log_text=$(if($null-ne$sourceTimingDiagnosticLog-and(Test-Path -LiteralPath $sourceTimingDiagnosticLog)){"
                        + "Get-Content -LiteralPath $sourceTimingDiagnosticLog -Raw}else{''})}|ConvertTo-Json -Compress"
                    )
                    completed = subprocess.run(
                        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                        cwd=RUNNER.parents[3], capture_output=True, text=True,
                        encoding="utf-8", timeout=30,
                    )
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    result = json.loads(completed.stdout.splitlines()[-1])
                    self.assertEqual(result["calls"], expected)
                    self.assertEqual(len(result["outputs"]), 3 if expected else 1)
                    self.assertEqual(result["log_exists"], bool(expected))
                    if expected:
                        self.assertIn("SOURCE_Z_ENERGY_TIMING_DIAGNOSTIC=PASS", result["log_text"])
                        self.assertIn("--completed-run-config", result["args"])
                        self.assertIn("final-config.json", result["args"])
                        self.assertIn("--batch-merge-receipt", result["args"])
                        self.assertNotIn("--run-dir", result["args"])

    @classmethod
    def setUpClass(cls):
        cls.source = RUNNER.read_text(encoding="utf-8")

    def test_requires_native_bank_and_system_bundle(self):
        selection = self.source.split("if($staticFieldRequested){", 1)[1].split(
            "$nativeCorridorRun=", 1,
        )[0]
        static, native = selection.split("}else{", 1)
        self.assertIn("analysis.static_field_binding", static)
        self.assertIn("Static field binding cannot consume a native adjustable runtime.", static)
        self.assertNotIn("IsNullOrWhiteSpace($NativeCorridorBankRunPath)", static)
        self.assertIn("IsNullOrWhiteSpace($NativeCorridorBankRunPath)", native)
        self.assertIn("NativeCorridorBankRunPath is required for a native flight.", native)
        self.assertIn("NativeCorridorBankRunPath requires NativeSystemRuntimeBundlePath.", native)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_summary_preserves_nested_phase_space_acceptance_objects(self):
        acceptance = {
            "status": "evaluated__center_particle_only",
            "absolute_tolerance_per_charge_v": 0.05,
            "reference_provider_tolerance_per_charge_v": None,
            "within_tolerance": False,
        }
        value = {"cohort_analysis": {"prism_phase_space_diagnostic": {"surfaces": {
            "accelerator_safe_exit": {"kinetic_energy_per_charge": {
                "component_target_diagnostic": {"components": {
                    "Ex": {"acceptance": acceptance},
                    "Ey": {"acceptance": {**acceptance, "within_tolerance": True}},
                }}
            }}
        }}}}
        publication = next(
            line.strip() for line in self.source.splitlines()
            if line.strip().startswith("Write-RunJson -Path $summary -Depth 100 ")
        )
        writer = RUNNER.parents[3] / "common/contracts/run_artifact_support.ps1"
        with TemporaryDirectory() as directory:
            source = Path(directory) / "input.json"
            target = Path(directory) / "summary.json"
            source.write_text(json.dumps(value), encoding="utf-8")
            quote = lambda path: "'" + str(path).replace("'", "''") + "'"
            command = (
                f". {quote(writer)}\n"
                f"$summaryValue=Get-Content -Raw -LiteralPath {quote(source)}|ConvertFrom-Json\n"
                f"$summary={quote(target)}\n{publication}"
            )
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", command],
                cwd=RUNNER.parent,
                capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8-sig")), value)

    def test_no_legacy_five_region_public_inputs_remain(self):
        for name in ("LocalWorkbenchRunPath", "LocalResponseFamilyRunPath",
                     "LocalRegionOverrideWorkbenchRunPath", "LocalRegionOverrideRegions",
                     "LocalHandoffSelectionRunPath", "RuntimeCentralStripeResponse",
                     "BootstrapGlobalOperatingPa", "localWorkbenchRun",
                     "useNativeCorridor", "hybridFixedResponseScreening",
                     "localOperatingCacheReceipt", "batchTemplateRecord"):
            self.assertNotIn(name, self.source)
        self.assertNotIn("basisLinkDir", self.source)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_all_step_scale_boundaries_allow_coarser_finite_positive_values(self):
        project = REPO / "projects/parallel_mirror_dual_stripe_mr_tof"
        for path, variable, guard in (
            (RUNNER, "TrajectoryStepScale", "if([double]::IsNaN($TrajectoryStepScale)"),
            (project / "analysis/run_native_candidate_chain.ps1", "TrajectoryStepScaleOverride",
             "if($null-ne$TrajectoryStepScaleOverride-and("),
            (project / "analysis/run_native_corridor_bunch_screening.ps1", "trajectoryStepScale",
             "if($null-ne$trajectoryStepScale-and("),
        ):
            source = path.read_text(encoding="utf-8-sig")
            start = source.index(guard)
            # The validator is either a one-line guard or the existing three-line guard.
            end = source.index("}", start) + 1
            validator = source[start:end]
            for expression, valid in (("1", True), ("2", True), ("4", True),
                                      ("0", False), ("-1", False),
                                      ("[double]::NaN", False), ("[double]::PositiveInfinity", False)):
                script = ("$ErrorActionPreference='Stop';$" + variable + "=" + expression + ";"
                          + validator + ";'accepted'")
                completed = subprocess.run(
                    ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                    cwd=project.parents[1], capture_output=True, text=True, encoding="utf-8", timeout=30,
                )
                self.assertEqual(completed.returncode == 0, valid, completed.stdout + completed.stderr)

    def test_native_runtime_preserves_four_instance_and_bundle_identity(self):
        for token in ("build_native_corridor_iob.lua", "4_instance_seed.iob",
                      "native_system_runtime", "NativeCorridorRuntimeSession",
                      "native_corridor_private_fast_adjust_family"):
            self.assertIn(token, self.source)
        self.assertIn("$privateIobSeed=Join-Path $temporarySolverDir '4_instance_seed.iob'", self.source)
        self.assertIn("foreach($seedIndex in 2..4)", self.source)
        self.assertIn("New-Item -ItemType HardLink", self.source)
        self.assertNotIn("Get-FileHash -LiteralPath $privateSeedPlaceholder", self.source)
        self.assertIn("$nativeControllerForIob=[IO.Path]::GetFullPath([string]$nativeRuntime.receipt.controller_path)", self.source)
        self.assertIn("$privateIobSeed,$iobAnalyzerInput,$nativeControllerForIob", self.source)

    def test_standalone_n1_can_open_one_existing_native_checkpoint(self):
        self.assertIn("[string]$NativeRuntimeCheckpoint=''", self.source)
        self.assertIn(
            "Supply NativeCorridorRuntimeSession or NativeRuntimeCheckpoint, not both.",
            self.source,
        )
        self.assertIn("directory=[IO.Path]::GetFullPath([string]$checkpoint.directory)", self.source)
        self.assertIn("checkpoint_path=$nativeRuntimeCheckpointPath", self.source)

    def test_checkpoint_is_opened_before_capacity_peak_is_computed(self):
        opened = self.source.index("Open-NativeCorridorRuntimeCheckpoint")
        peak = self.source.index("$nativeFamilyPeakBytes=10*")
        self.assertLess(opened, peak)
        self.assertIn("$NativeCorridorRuntimeSession.resident_bytes-gt0", self.source)

    def test_global_fallback_identity_is_reused_without_an_extra_full_hash(self):
        self.assertIn(
            "$voltageSourceHash=[string]$globalFallbackRecord.sha256", self.source
        )
        self.assertNotIn(
            "Get-FileHash -LiteralPath $globalFallbackAnalyzer", self.source
        )

    def test_shared_runtime_retains_small_gui_workbench_under_compact_policy(self):
        for token in (
            "[switch]$RetainGuiWorkbench",
            "$trajectoryRetentionClass=if($null-eq$trajectoryRecording){'compact'}",
            "$retainGuiWorkbenchFiles=($null-ne$NativeCorridorRuntimeSession)-or$RetainGuiWorkbench",
            "Join-Path $artifactSolverDir 'gui_workbench'",
            "Retained GUI workbench native checkpoint controller is missing.",
            "PA payloads have already been bound through the runtime and published",
            "pa_dependencies=$guiPaDependencies",
            "Get-ChildItem -LiteralPath $temporarySolverDir -File -Filter 'trj*.tmp'",
        ):
            self.assertIn(token, self.source)
        # Prepared replay retains explicit trajectory observations; ordinary
        # OA GUI retention must continue to use the compact default instead.
        oa_execution = self.source.split("\nforeach($value in @($Prism1VoltageV,$Prism2VoltageV))", 1)[1]
        self.assertNotIn("-RetentionClass solver_review", oa_execution)
        self.assertIn("-RetentionClass $trajectoryRetentionClass -RetentionReason $trajectoryRetentionReason", oa_execution)
        self.assertIn("if($retainGuiWorkbenchFiles){", self.source)
        self.assertNotIn("Join-Path $temporarySolverDir 'pa_inputs'", self.source)
        self.assertNotIn("simion_pa_links_", self.source)
        self.assertNotIn("iobInputCopyDir", self.source)
        self.assertIn("$privateIobSeed,", self.source)
        self.assertIn(
            "if(-not$staticFieldRequested-and$RetainGuiWorkbench-and$null-eq$NativeCorridorRuntimeSession)",
            self.source,
        )
        self.assertIn(
            "standalone retention would duplicate the complete PA family",
            self.source,
        )

    def test_retained_gui_rebinds_shared_runtime_to_persistent_checkpoint(self):
        self.assertIn(
            "Join-Path ([string]$NativeCorridorRuntimeSession.directory) 'mrtof_analyzer_corridor.pa0'",
            self.source,
        )
        self.assertIn("-Stage 'rebind_retained_gui_iob'", self.source)
        self.assertIn("$nativeRuntime.controller_path=$stableNativeController", self.source)
        self.assertIn(
            "$privateIobSeed,$globalFallbackAnalyzer,$guiNativeController,$persistentAcceleratorController,$sourceDetector",
            self.source,
        )
        self.assertIn("persistent_controller_path", self.source)
        self.assertIn("$iobAcceleratorInput=$persistentAcceleratorController", self.source)
        self.assertIn("accelerator_controller=$persistentAcceleratorController", self.source)
        accelerator_block = self.source.split("$failureStage='prepare_accelerator_runtime_family'", 1)[1].split(
            "$nativeOrigins=", 1,
        )[0]
        self.assertNotIn("New-NativeFastAdjustRuntimeFamily", accelerator_block)
        self.assertNotIn("Remove-ShortPaCopy -Path $projectedPa", self.source)
        self.assertIn(
            "Remove-IobSeedPlaceholderCompanions -Directory $temporarySolverDir -Count 4",
            self.source,
        )
        self.assertNotIn(
            "shared runtime sessions are not portable GUI dependencies", self.source
        )
        self.assertNotIn(
            "Get-ChildItem -LiteralPath $temporarySolverDir -Recurse -File", self.source
        )

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_gui_retention_condition_covers_native_and_static_modes(self):
        assignment = next(
            line for line in self.source.splitlines()
            if line.startswith("$retainGuiWorkbenchFiles=")
        )
        command = (
            "foreach($native in @($false,$true)){foreach($staticFieldRequested in @($false,$true)){"
            "foreach($RetainGuiWorkbench in @($false,$true)){"
            "$NativeCorridorRuntimeSession=if($native){[pscustomobject]@{}}else{$null};"
            + assignment
            + ";[int]$retainGuiWorkbenchFiles}}}"
        )
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-Command", command],
            cwd=RUNNER.parents[3], capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([int(value) for value in result.stdout.split()], [0, 1, 0, 1, 1, 1, 1, 1])

    def test_bunch_batches_use_official_shared_iob_particle_override(self):
        self.assertIn("official_shared_iob__per_process_particles_override", self.source)
        self.assertIn("$batchIob=$temporaryIob", self.source)
        self.assertIn("$Record.iob,$Record.source_fly2", self.source)
        self.assertNotIn("build_native_batch_iob_", self.source)
        self.assertNotIn("batch_iob_bundle_portability_receipt", self.source)
        self.assertNotIn("batchPaCopyDirectories", self.source)
        self.assertIn("shared_native_corridor_runtime__four_instances__no_refine", self.source)
        self.assertNotIn("build_local_refinement_iob.lua", self.source)
        self.assertNotIn("build_three_component_iob.lua", self.source)

    def test_dispatch_identity_reuses_verified_component_and_bank_receipts(self):
        self.assertIn(
            "frontend_pa0_sha256=$(if($staticFieldRequested){[string]$staticFieldBinding.records.scalar_pa.sha256}else{[string]$nativeBankCache.generation_sha256})",
            self.source,
        )
        self.assertIn("accelerator_overlay_generation_sha256=[string]$providerAccelerator.pa_family.generation_sha256", self.source)
        self.assertIn("reflectron_pa0_sha256=[string]$nativeSystemRuntimeRecords['detector'].sha256", self.source)
        self.assertNotIn("Get-FileHash -LiteralPath $sourceAccelerator", self.source)
        self.assertNotIn("Get-FileHash -LiteralPath $sourceDetector", self.source)

    def test_static_pa_assets_are_guarded_once_and_not_materialized_per_trial(self):
        self.assertIn("$requiredBytes+=$nativeFamilyPeakBytes", self.source)
        self.assertNotIn("iobProjectionBytes", self.source)
        self.assertIn(
            "Protect-ImmutablePaSource -Source $globalFallbackAnalyzer", self.source
        )
        self.assertIn("Protect-ImmutablePaSource -Source $sourceDetector", self.source)
        self.assertIn("$iobAnalyzerInput=$globalFallbackAnalyzer", self.source)
        self.assertIn("$iobDetectorInput=$sourceDetector", self.source)
        self.assertNotIn("function Copy-IobPaInput", self.source)
        self.assertNotIn("New-ShortPaCopy -Source $sourceDetector", self.source)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_static_capacity_protects_response_layers_and_keeps_plain_default(self):
        start = self.source.index("  $protectedPaths=@($package.artifact_run_dir,$nativeCorridorRun,$nativeBankGeneration)")
        end = self.source.index("  $capacitySession=$sessionUpdate.session", start)
        block = self.source[start:end]
        base = {"export_manifest": "base/manifest.json", "collision_geometry": "collision/geometry.json",
                "sources": {"scalar_pa": "base/v.pa", "valid_pa": "base/mask.pa"},
                "instances": [{"pa_path": "collision/collision.pa", "manifest": "collision/manifest.json"}],
                "refinement_windows": [{"export_manifest": "base/window/manifest.json",
                                        "sources": {"scalar_pa": "base/window/v.pa", "valid_pa": "base/window/mask.pa"}}]}
        ordinary = {"run", "binding.json", "collision/geometry.json", "collision/collision.pa",
                    "collision/manifest.json", "base/manifest.json", "base/v.pa", "base/mask.pa",
                    "base/window/manifest.json", "base/window/v.pa", "base/window/mask.pa"}
        with TemporaryDirectory() as directory:
            for combined in (False, True, "native", "native_no_surface"):
                with self.subTest(combined=combined):
                    binding = json.loads(json.dumps(base))
                    expected = set(ordinary)
                    mode = "comsol_static_scalar_v"
                    if combined in ("native", "native_no_surface"):
                        mode = "native_static_pa"
                        binding = {"mode": mode, "manifest": "base/manifest.json",
                                   "sources": {"scalar_pa": "base/v.pa", "surface": "base/v.pa-surf"},
                                   "instances": base["instances"],
                                   "refinement_windows": [{"manifest": "base/window/manifest.json",
                                       "sources": {"scalar_pa": "base/window/v.pa",
                                                   "surface": "base/window/v.pa-surf"}}]}
                        expected = {"run", "binding.json", "collision/collision.pa", "collision/manifest.json",
                                    "base/manifest.json", "base/v.pa", "base/v.pa-surf",
                                    "base/window/manifest.json", "base/window/v.pa", "base/window/v.pa-surf"}
                        if combined == "native_no_surface":
                            binding["sources"]["surface"] = None
                            binding["refinement_windows"][0]["sources"]["surface"] = None
                            expected -= {"base/v.pa-surf", "base/window/v.pa-surf"}
                    if combined is True:
                        binding["response_terms"] = []
                        for name in ("baseline", "s1", "s2"):
                            component = {"export_manifest": f"{name}/manifest.json",
                                         "sources": {"scalar_pa": f"{name}/v.pa", "valid_pa": f"{name}/mask.pa"},
                                         "refinement_windows": [{"export_manifest": f"{name}/local/manifest.json",
                                                                 "sources": {"scalar_pa": f"{name}/local/v.pa", "valid_pa": f"{name}/local/mask.pa"}}]}
                            binding["response_terms"].append({"coefficient": 0. if name == "s2" else 1.,
                                                              "binding_path": f"{name}/binding.json", "binding": component})
                            expected.update({f"{name}/binding.json", component["export_manifest"],
                                             *component["sources"].values(),
                                             component["refinement_windows"][0]["export_manifest"],
                                             *component["refinement_windows"][0]["sources"].values()})
                    path = Path(directory) / "binding.json"
                    path.write_text(json.dumps(binding), encoding="utf-8")
                    quoted = "'" + str(path).replace("'", "''") + "'"
                    command = (
                        "$ErrorActionPreference='Stop';Set-StrictMode -Version Latest\n"
                        f"$staticFieldMode='{mode}';$staticFieldRequested=$true;$package=@{{artifact_run_dir='run'}};"
                        "$FieldBindingPath='binding.json';$nativeCorridorRun=$null;$nativeBankGeneration=$null;"
                        "$nativeBankKey=$null;$requiredBytes=0;$ownsCapacitySession=$false;$trajectoryRecording=$null;"
                        "$capacitySession=[pscustomobject]@{committed_new_bytes=0};$python='mock';$repoRoot='repo'\n"
                        f"$staticFieldBinding=Get-Content -LiteralPath {quoted} -Raw|ConvertFrom-Json -Depth 100\n"
                        "function Update-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session,$ProtectedPaths,$ProtectedCacheKeys,$RemainingCommittedNewBytes)"
                        " [Console]::WriteLine((@{paths=@($ProtectedPaths);keys=@($ProtectedCacheKeys)}|ConvertTo-Json -Compress));"
                        " return @{session=$Session}}\n" + block
                    )
                    result = subprocess.run(["pwsh", "-NoProfile", "-Command", command],
                                            cwd=RUNNER.parent, capture_output=True, text=True,
                                            encoding="utf-8", errors="replace", timeout=30)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    actual = json.loads(result.stdout)
                    self.assertEqual(set(actual["paths"]), expected)
                    self.assertEqual(actual["keys"], [])

    def test_first_batch_observation_keeps_repository_scheduler_contract(self):
        self.assertIn("Invoke-SimionBatchPhase -DispatchPlanPath", self.source)
        self.assertNotIn("WaitForNaturalCompletionAfterObservation", self.source)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_native_static_guards_gui_and_provenance_need_no_comsol_export(self):
        guard_start = self.source.index("    $guardPaths=@($staticFieldBinding.instances")
        guard = self.source[guard_start:self.source.index("    foreach($path in", guard_start)]
        gui_start = self.source.index("      $guiPaDependencies=@($staticFieldBinding.instances")
        gui = self.source[gui_start:self.source.index("      $guiWorkbenchOutputs+=", gui_start)]
        provenance_start = self.source.index("  if($staticFieldRequested){\n    if($staticFieldMode-eq'native_static_pa')")
        provenance = self.source[provenance_start:self.source.index("  $config.parameters.prism_1_voltage_v=", provenance_start)]
        binding = {"manifest": "native/manifest.json", "sources": {
            "scalar_pa": "native/v.pa", "surface": "native/v.pa-surf", "geometry_authority": "native/geometry.json"},
            "records": {"scalar_pa": {"path": "native/v.pa"}, "surface": {"path": "native/v.pa-surf"}},
            "instances": [{"pa_path": f"collision/{i}.pa", "manifest": f"collision/{i}/manifest.json"} for i in range(4)],
            "refinement_windows": [{"manifest": "local/manifest.json", "sources": {
                "scalar_pa": "local/v.pa", "surface": "local/v.pa-surf"},
                "records": {"scalar_pa": {"path": "local/v.pa"}, "surface": {"path": "local/v.pa-surf"}}}]}
        with TemporaryDirectory() as directory:
            path = Path(directory) / "binding.json"
            path.write_text(json.dumps(binding), encoding="utf-8")
            quote = "'" + str(path).replace("'", "''") + "'"
            command = ("$ErrorActionPreference='Stop';Set-StrictMode -Version Latest;"
                       "$staticFieldRequested=$true;$staticFieldMode='native_static_pa';$requiresNativeExecution=$true;"
                       "$config=@{provenance=@{upstream_manifest_verification=@{native_system_runtime='old'}}};"
                       f"$staticFieldBinding=Get-Content -Raw -LiteralPath {quote}|ConvertFrom-Json -Depth 100\n"
                       + guard + gui + provenance +
                       "@{guard=@($guardPaths);gui=@($guiPaDependencies);provenance=$config.provenance}|ConvertTo-Json -Depth 30 -Compress")
            result = subprocess.run(["pwsh", "-NoProfile", "-Command", command], cwd=RUNNER.parent,
                                    capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual(set(value["guard"]), {*(f"collision/{i}.pa" for i in range(4)),
                "native/v.pa", "native/v.pa-surf", "local/v.pa", "local/v.pa-surf"})
            self.assertEqual(len(value["gui"]), 8)
            upstream = value["provenance"]["upstream_manifest_verification"]
            self.assertNotIn("native_system_runtime", upstream)
            self.assertEqual(upstream["static_field"]["manifest"], "native/manifest.json")
            self.assertNotIn("export_manifest", upstream["static_field"])
            self.assertEqual(upstream["geometry"]["instances"], binding["instances"])
            binding["refinement_windows"][0]["sources"]["surface"] = None
            binding["refinement_windows"][0]["records"]["surface"] = None
            path.write_text(json.dumps(binding), encoding="utf-8")
            result = subprocess.run(["pwsh", "-NoProfile", "-Command", command], cwd=RUNNER.parent,
                                    capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            value = json.loads(result.stdout)
            self.assertNotIn(None, value["guard"])
            self.assertNotIn("local/v.pa-surf", value["guard"])
            self.assertIn("native/v.pa-surf", value["guard"])
            self.assertEqual(len(value["gui"]), 7)

    def test_first_completed_batch_publishes_existing_controlled_aberration_report(self):
        self.assertIn("function Publish-MrtofFirstBatchAberration", self.source)
        self.assertIn("--first-batch-log',$Record.stdout", self.source)
        self.assertIn("--source-receipt',$bunchSourceLocal", self.source)
        self.assertIn("Publish-MrtofFirstBatchAberration -Record", self.source)
        self.assertIn("$manifestOutputs+=$earlyAberrationReport", self.source)

    def test_bunch_batches_publish_common_whole_batch_checkpoints(self):
        for token in (
            "[string]$BatchContinuationRunPath=''",
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_continuation",
            "simion_whole_unit_replay_plan",
            "continuation requires a sealed whole-batch log and owner exit evidence",
            "-OnProcessCompleted $checkpointAction",
            "-Status checkpoint",
        ):
            self.assertIn(token, self.source)
        self.assertIn("$replayBatchIndexes-contains$index", self.source)
        self.assertIn("$replayBatchIndexes=@(", self.source)
        self.assertIn(
            "$replanState.replayIndexes=@($replanned.batches|ForEach-Object{[int]$_.index})",
            self.source,
        )

    def test_failure_removes_only_disposable_trajectory_cache_before_publication(self):
        catch = self.source.index("}catch{")
        failed = self.source.index("Complete-RunArtifactPowerShellOwner -Context $owner", catch)
        cache_cleanup = self.source.index(
            "Get-ChildItem -LiteralPath $temporarySolverDir -File -Filter 'trj*.tmp'",
            catch,
        )
        self.assertLess(cache_cleanup, failed)

    def test_terminal_publication_is_independent_of_payload_seal(self):
        # Real retention/publication/repeat recovery now runs through both CLIs
        # in test_workflow_finalization_recovery; this protects production wiring.
        self.assertNotIn("function Publish-OaMrFailureManifest", self.source)
        self.assertNotIn("Apply-RunArtifactRetention", self.source)
        self.assertNotIn("--action','seal-stopped-payload", self.source)
        self.assertIn("Initialize-RunArtifactPowerShellOwner", self.source)
        self.assertIn("-OwnCapacitySession:$ownsCapacitySession", self.source)
        self.assertIn("-WritersStopped $true -WriterCompletion", self.source)
        self.assertIn("-OriginalFailure $failureRecord", self.source)
        self.assertLess(self.source.index("$release=Exit-HostResourceStage"),
                        self.source.index("Complete-RunArtifactPowerShellOwner -Context $owner"))

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_closeout_preserves_primary_error_and_isolates_safe_owner_actions(self):
        """Run the actual catch/finally; only external owners are inert fixtures."""
        command = r"""
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile('integrations/workflows/oa_mr/execute.ps1',[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$ownerTry=@($ast.EndBlock.Statements|Where-Object{$_-is[Management.Automation.Language.TryStatementAst]})[-1]
$tail=$ownerTry.CatchClauses[0].Extent.Text+'finally'+$ownerTry.Finally.Extent.Text
function Invoke-Fixture {
 param($Fault,$Primary,$Stopped,$Owned,$Tail)
 $script:fault=$Fault;$script:events=[Collections.Generic.List[string]]::new()
 $terminalPublicationAttempted=-not$Primary;$terminalPublicationClosed=-not$Primary
 $terminalStatus='success';$failureStage='science';$failureRecord=$null
 $closeoutErrors=[Collections.Generic.List[object]]::new();$writerCompletion=[pscustomobject]@{stopped=$Stopped}
 $trajectoryPayloadNeedsSeal=$Owned-and-not$Primary;$hostOutcome='failed';$deferredHostCompletionNotification=$false
 $ownsHostResourceLease=$Owned;$resourceLease=@{inherited=$false;token='fixture-token'}
 $ownsCapacitySession=$Owned;$capacitySession=@{status='active'}
 $temporarySolverDir=$null;$temporaryAcceleratorRuntimeSession=@{};$batchRuntimeRoot=[string]$PWD
 $retainGuiWorkbenchFiles=$false;$runConfig=Join-Path $PWD 'README.md';$python='inert';$repoRoot=[string]$PWD
 $artifactRoot='inert';$projectId='instrument_assembly';$package=@{artifact_run_dir='inert'};$RunId='inert';$resultDir='inert'
 $trajectoryRetentionReason='fixture';$observed=@{status='inert'}
 $runClock=[Diagnostics.Stopwatch]::StartNew();$nativePhaseTimings=[ordered]@{};$runDir='inert';$owner=@{result_path='inert'};$ownerOutputs=@();$nativeOperations=[Collections.Generic.List[object]]::new();$resourceReleases=[Collections.Generic.List[object]]::new();$summary='inert'
 $guard1=[pscustomobject]@{};$guard1|Add-Member ScriptMethod Dispose {
  $script:events.Add('guard1');if($script:fault-in@('guard','multiple')){throw 'guard failed'}
 }
 $guard2=[pscustomobject]@{};$guard2|Add-Member ScriptMethod Dispose {$script:events.Add('guard2')}
 $staticPaGuards=@($guard1,$guard2)
 $continuationEvidenceGuards=@()
 function Write-RunJson {param($Path,$Value) if($Value.status-eq'unknown'){$script:events.Add('unknown_result')}elseif($Value.status-ne'failed'){throw 'bad failure result'}}
 function Get-Content {param($LiteralPath,[switch]$Raw) '{}'}
 function Get-ChildItem {param($LiteralPath,[switch]$Recurse,[switch]$File) @()}
 function Complete-RunArtifactPowerShellOwner {
  param($Context,$Status,$Summary,$OutputPaths,$WritersStopped,$WriterCompletion,$OriginalFailure)
  if(-not$WritersStopped){throw 'unknown writer retained'}
  $script:events.Add('publish');if($script:fault-eq'publish'){throw 'publish failed'}
  if($Owned){
   $script:events.Add('capacity');if($script:fault-in@('capacity','capacity_unreleased')){throw 'capacity failed'}
   $capacitySession.status='released'
   $script:events.Add('seal');if($script:fault-eq'seal'){throw 'seal failed'}
  }else{$script:events.Add('light')}
  return @{status=$Status;stage='complete';terminal_published=$true;capacity_finalized=$Owned;recovery_action=$null}
 }
 function Invoke-RunCapacityLifecycleAdapter {param($Python,$RepoRoot,$Action,$ArtifactRoot,$RunConfig) $script:events.Add('light')}
 function Suspend-NativeCorridorRuntimeSession {param($Session)
  $script:events.Add('runtime');if($script:fault-eq'runtime'){throw 'runtime failed'}
 }
 function Exit-HostResourceStage {param($Lease,[switch]$PassThru)
  $script:events.Add('host');if($script:fault-eq'host'){throw 'host failed'}
  if(-not$PassThru){throw 'Actual release receipt required'}
  return @{status=$(if($script:fault-eq'host_retained'){'acquired'}else{'released'});token=$Lease.token}
 }
 function Invoke-HostExecutionCompletionNotification {param($Outcome,$RunId) $script:events.Add('notify')}
 function Remove-TemporarySolverDirectory {param($Path)
  $script:events.Add('temp');if($script:fault-in@('temp','multiple')){throw 'temp failed'}
 }
 function Exit-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session)
  $script:events.Add('capacity');if($script:fault-eq'capacity'){throw 'capacity failed'}
  if($script:fault-ne'capacity_unreleased'){$Session.status='released'}
 }
 function Invoke-ProjectPython {param($Arguments)
  $script:events.Add('seal');if($script:fault-eq'seal'){throw 'seal failed'}
 }
 function Remove-RunPackageExecutionAlias {param($Package)
  $script:events.Add('alias');if($script:fault-in@('alias','multiple')){throw 'alias failed'}
 }
 function Write-Host {param($Object)}
 function Write-Warning {param($Message,$WarningAction)}
 $caught=$null;$secondary=@()
 $body=if($Fault-eq'observation_unknown'){"try{`$e=[Exception]::new('science failed');`$e.Data['simion_first_batch_writer_unknown']=`$true;throw `$e}"}elseif($Fault-eq'wave_stopped'){"try{`$e=[Exception]::new('science failed');`$e.Data['simion_wave_writer_completion_confirmed']=`$true;throw `$e}"}elseif($Primary){"try{throw 'science failed'}"}else{'try{}'}
 try{. ([scriptblock]::Create($body+$Tail))}catch{
  $caught=$_.Exception.Message
  if($_.Exception.Data.Contains('oa_mr_closeout_errors')){$secondary=@($_.Exception.Data['oa_mr_closeout_errors'])}
 }
 @{fault=$Fault;primary=$Primary;stopped=$Stopped;owned=$Owned;error=$caught;secondary=$secondary;
   calls=@($script:events);capacity_status=$capacitySession.status}
}
$rows=@(foreach($fault in @('none','publish','guard','runtime','host','host_retained','temp','capacity','capacity_unreleased','seal','alias','multiple')){
 Invoke-Fixture $fault $true $true $true $tail
})
$rows+=@(Invoke-Fixture 'guard' $false $true $true $tail)
$rows+=@(Invoke-Fixture 'none' $false $true $true $tail)
$rows+=@(Invoke-Fixture 'none' $true $false $true $tail)
$rows+=@(Invoke-Fixture 'observation_unknown' $true $true $true $tail)
$rows+=@(Invoke-Fixture 'wave_stopped' $true $false $true $tail)
$rows+=@(Invoke-Fixture 'none' $true $true $false $tail)
$rows|ConvertTo-Json -Depth 8 -Compress
"""
        result = subprocess.run(["pwsh", "-NoProfile", "-Command", command], cwd=REPO,
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rows = json.loads(result.stdout)
        for row in rows:
            with self.subTest(**{key: row[key] for key in ("fault", "primary", "stopped", "owned")}):
                calls = row["calls"]
                if row["primary"]:
                    self.assertEqual(row["error"], "science failed")
                elif row["fault"] == "none":
                    self.assertIsNone(row["error"])
                else:
                    self.assertIn("guard failed", row["error"])
                if (not row["stopped"] and row["fault"] != "wave_stopped") or row["fault"] == "observation_unknown":
                    self.assertEqual(calls, ["unknown_result"])
                    self.assertEqual(row["capacity_status"], "active")
                    continue
                for expected in ("guard1", "guard2", "runtime"):
                    self.assertIn(expected, calls)
                if not row["owned"]:
                    self.assertNotIn("host", calls)
                    self.assertNotIn("capacity", calls)
                    self.assertNotIn("seal", calls)
                    self.assertIn("light", calls)
                    self.assertIn("alias", calls)
                    continue
                self.assertIn("host", calls)
                if row["fault"] in ("host", "host_retained"):
                    self.assertFalse(set(calls) & {"temp", "capacity", "seal", "alias"})
                    self.assertEqual(row["capacity_status"], "active")
                else:
                    for expected in (("temp", "alias") if row["fault"] == "publish" else ("temp", "capacity", "alias")):
                        self.assertIn(expected, calls)
                    self.assertEqual("seal" in calls, row["fault"] not in
                                     ("publish", "capacity", "capacity_unreleased"))
                if row["fault"] not in ("none", "wave_stopped"):
                    self.assertTrue(row["secondary"])
                if row["fault"] == "multiple":
                    self.assertEqual([item["stage"] for item in row["secondary"]],
                                     ["guard_release", "temporary_directory", "execution_alias"], row["secondary"])

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_native_stop_fact_requires_actual_wait_even_for_nonzero_exit(self):
        """Small Python roots exercise the existing native helper without SIMION."""
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            command = r"""param($Python,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile('integrations/workflows/oa_mr/execute.ps1',[ref]$tokens,[ref]$errors)
$helper=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-SimionStage'},$true)
. ([scriptblock]::Create($helper.Extent.Text))
$simion=$Python;$solverDir=$Root;$logDir=$Root
function Register-HostResourceProcess {param($Lease,$ProcessId)
 if($script:inject){$script:child=[Diagnostics.Process]::GetProcessById($ProcessId);throw 'registration failed'}
}
function Write-Host {param($Object)}
$rows=@(foreach($case in @('zero','nonzero','unknown')){
 $script:inject=$case-eq'unknown';$script:child=$null;$writerCompletion=[pscustomobject]@{stopped=$true};$nativeOperations=[Collections.Generic.List[object]]::new();$nativePhaseTimings=[ordered]@{}
 $code=if($case-eq'unknown'){'import time; time.sleep(0.25)'}elseif($case-eq'nonzero'){'raise SystemExit(7)'}else{'pass'}
 $errorText=$null
 try{$null=Invoke-SimionStage -Stage $case -Arguments @('-B','-c',$code) -ResourceLease @{}}
 catch{$errorText=$_.Exception.Message}
 $fact=[bool]$writerCompletion.stopped
 # The test owns the deliberately unobserved root and waits for its natural end.
 if($null-ne$script:child){try{$script:child.WaitForExit()}finally{$script:child.Dispose()}}
 @{case=$case;stopped=$fact;error=$errorText;observation=$nativeOperations[0].observation}
})
$rows|ConvertTo-Json -Compress
"""
            # Use the actual interpreter root, not the Windows venv launcher shim.
            invocation = "& {" + command + "} " + " ".join(
                "'" + str(value).replace("'", "''") + "'" for value in (sys._base_executable, root))
            result = subprocess.run(["pwsh", "-NoProfile", "-Command", invocation], cwd=REPO,
                                    capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            rows = {row["case"]: row for row in json.loads(result.stdout)}
            self.assertEqual([rows[key]["stopped"] for key in ("zero", "nonzero", "unknown")],
                             [True, True, False])
            self.assertIsNone(rows["zero"]["error"])
            self.assertGreater(rows["zero"]["observation"]["process_id"], 0)
            self.assertGreater(rows["zero"]["observation"]["process_started_at_utc_ticks"], 0)
            self.assertEqual(rows["nonzero"]["observation"]["returncode"], 7)
            self.assertFalse(rows["unknown"]["observation"]["exit_confirmed"])
            self.assertIn("SIMION stage failed", rows["nonzero"]["error"])
            self.assertIn("registration failed", rows["unknown"]["error"])

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_runtime_provider_forwards_existing_owned_native_callback(self):
        script = r'''
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $PWD 'projects/parallel_mirror_dual_stripe_mr_tof/simion/native_corridor_runtime_support.ps1')
$records=[Collections.Generic.List[object]]::new();$callback={throw 'must remain a callback'}
function New-NativeFastAdjustRuntimeFamily {
 param($GenerationDirectory,$ExpectedResponseIds,$NativeOperationObservations,$InvokeNativeOperation)
 if($GenerationDirectory-cne'sealed-field'-or($ExpectedResponseIds-join',')-cne'1,2,3,4,5,6,7,8'){throw 'physical namespace changed'}
 if(-not[object]::ReferenceEquals($records,$NativeOperationObservations)-or-not[object]::ReferenceEquals($callback,$InvokeNativeOperation)){throw 'actual native observer not forwarded'}
 @{marker='existing-common-owner'}
}
$result=New-NativeCorridorRuntimeFamily -BankGenerationDirectory sealed-field -CacheKey key -GenerationSha256 digest -DestinationDirectory unused -Python unused -RepoRoot $PWD -SimionExe unused -ResourceLease @{} -RunId fixture -NativeOperationObservations $records -InvokeNativeOperation $callback
if($result.marker-cne'existing-common-owner'){throw 'private native path used'}
'''
        process = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=REPO,
            capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)

    def test_compact_postprocess_does_not_transition_a_finished_solver_lease(self):
        self.assertNotIn("-Stage 'mrtof_postprocess'", self.source)

    def test_inherited_host_lease_is_reused_and_not_released_by_child(self):
        self.assertIn("[pscustomobject]$InheritedHostResourceLease=$null", self.source)
        self.assertIn("$resourceLease=$InheritedHostResourceLease", self.source)
        self.assertIn("$ownsHostResourceLease=$null-eq$InheritedHostResourceLease", self.source)
        self.assertIn("if($ownsHostResourceLease){", self.source)
        self.assertNotIn("Update-HostResourceStage -Lease $resourceLease -Stage 'mrtof_prepare'", self.source)
        self.assertEqual(
            self.source.count("Update-HostResourceStage -Lease $resourceLease -Stage 'mrtof_flight'"),
            2,
        )
        self.assertIn("if($writerCompletion.stopped-and$ownsHostResourceLease-and$null-ne$resourceLease)", self.source)

    def test_shared_host_lease_does_not_accumulate_transient_work_roots(self):
        self.assertIn("[bool]$RegisterHostProcess=$true", self.source)
        self.assertIn(
            "if($RegisterHostProcess-and-not$process.HasExited)", self.source
        )
        native_calls = [line.strip() for line in self.source.splitlines()
                        if line.strip().startswith("Invoke-SimionStage -Stage ")]
        self.assertEqual({line.split("'")[1] for line in native_calls}, {
            "build_temporary_iob", "native_two_prism_flight", "rebind_retained_gui_iob",
        })
        for call in native_calls:
            self.assertIn("-RegisterHostProcess $ownsHostResourceLease", call)
        self.assertNotIn(
            "a reserved process creation identity is unavailable", self.source
        )

    def test_provider_runtime_receipt_is_the_only_accelerator_input(self):
        self.assertIn("AcceleratorProviderReceiptPath", self.source)
        self.assertNotIn("AcceleratorRunPath", self.source)
        self.assertIn("orthogonal_accelerator_mrtof_runtime_receipt", self.source)
        self.assertIn("published_standalone_response_bank", self.source)
        self.assertIn("Provider consumed input byte count differs from its declared receipt.", self.source)
        self.assertIn("$acceleratorConsumerProjectionId='mrtof_accelerator_provider_receipt_v1'", self.source)
        self.assertIn("--consumer-projection-id $acceleratorConsumerProjectionId --consumed-output $acceleratorProviderReceipt", self.source)
        self.assertIn("@($providerAccelerator.provider_plan,$providerAccelerator.resolved_campaign)", self.source)
        self.assertNotIn("$providerAccelerator.pa_child_manifest", self.source)
        self.assertIn("$iobAcceleratorInput=$sourceAccelerator", self.source)
        self.assertNotIn("Copy-IobPaInput -Source $sourceAccelerator", self.source)

    def test_upstream_projections_bind_only_the_records_oa_mr_consumes(self):
        """Exercise the public verifier, not a runner-local manifest imitation."""
        verifier = REPO / "common/contracts/verify_run_manifest.py"
        projections = (
            ("bunch", "mrtof_bunch_source_materialization_v1", ("receipt", "states", "fly2")),
            ("mirror", "mrtof_mirror_summary_v1", ("summary",)),
            ("stripe", "mrtof_stripe_summary_v1", ("summary",)),
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for label, projection_id, consumed_names in projections:
                with self.subTest(label=label):
                    run = root / label
                    run.mkdir()
                    config = run / "run_config.json"
                    config.write_text(json.dumps({
                        "project": "parallel_mirror_dual_stripe_mr_tof",
                        "mode": "fixture", "parameters": {}, "provenance": {},
                    }), encoding="utf-8")
                    paths = {}
                    for name in (*consumed_names, "unconsumed"):
                        path = run / f"{name}.json"
                        path.write_text(json.dumps({"name": name, "revision": 1}), encoding="utf-8")
                        paths[name] = path
                    manifest = run / "run_manifest.json"
                    manifest.write_text(json.dumps({
                        "schema_version": 1, "run_id": label, "project": "parallel_mirror_dual_stripe_mr_tof",
                        "mode": "fixture", "status": "success", "run_config": file_record(config),
                        "inputs": {}, "outputs": [file_record(path) for path in paths.values()],
                    }), encoding="utf-8")
                    command = [sys.executable, str(verifier), str(manifest), "--require-status", "success",
                               "--require-project", "parallel_mirror_dual_stripe_mr_tof",
                               "--consumer-projection-id", projection_id]
                    for name in consumed_names:
                        command.extend(("--consumed-output", str(paths[name])))
                    # An unrelated producer record is deliberately not part of this consumer's authority.
                    paths["unconsumed"].write_text('{"changed": true}\n', encoding="utf-8")
                    passed = subprocess.run(command, cwd=REPO, capture_output=True, text=True,
                                             encoding="utf-8", timeout=30)
                    self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)
                    self.assertIn("SCOPE=consumer_projection", passed.stdout)
                    # Any output that this consumer does read remains fail-closed.
                    paths[consumed_names[0]].write_text('{"changed": true}\n', encoding="utf-8")
                    failed = subprocess.run(command, cwd=REPO, capture_output=True, text=True,
                                             encoding="utf-8", timeout=30)
                    self.assertNotEqual(failed.returncode, 0)
                    self.assertIn("changed", failed.stderr)
        self.assertIn("$bunchConsumerProjectionId='mrtof_bunch_source_materialization_v1'", self.source)
        self.assertIn("$mirrorConsumerProjectionId='mrtof_mirror_summary_v1'", self.source)
        self.assertIn("$stripeConsumerProjectionId='mrtof_stripe_summary_v1'", self.source)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell is required")
    def test_exit_only_skips_detector_gate_but_full_flight_calls_it(self):
        start = self.source.index("  $collectionGatePath=$null;$collectionGate=$null")
        end = self.source.index("  $observedResiduals=", start)
        block = self.source[start:end]
        with TemporaryDirectory() as directory:
            quoted = "'" + directory.replace("'", "''") + "'"
            for scope, expected_calls in (
                ("accelerator_safe_exit_envelope_only", 0),
                ("complete_three_dimensional_static_return", 1),
            ):
                with self.subTest(scope=scope):
                    command = (
                        "$ErrorActionPreference='Stop'; $isBunchFlight=$true; $calls=0\n"
                        f"$trial=@{{execution_scope='{scope}'}}; $resultDir={quoted}\n"
                        "$observation='unused'; function Invoke-ProjectPython { param($Arguments) "
                        "$script:calls++; '{}' | Set-Content -LiteralPath $Arguments[-1] }\n"
                        + block
                        + "\n@{calls=$calls; gate_is_null=($null-eq$collectionGate)}|ConvertTo-Json -Compress"
                    )
                    result = subprocess.run(
                        ["pwsh", "-NoProfile", "-Command", command],
                        cwd=RUNNER.parent,
                        capture_output=True, text=True, encoding="utf-8", timeout=30,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    actual = json.loads(result.stdout)
                    self.assertEqual(actual["calls"], expected_calls)
                    self.assertEqual(actual["gate_is_null"], expected_calls == 0)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell is required")
    def test_flight_scope_follows_execution_scope(self):
        scope_start = self.source.index("$isSafeExitOnly=")
        scope_end = self.source.index("\n", scope_start)
        label_start = self.source.index("$config.parameters.flight_scope=")
        label_end = self.source.index(";$config.parameters.execution_scope=", label_start)
        for scope in (
            "accelerator_safe_exit_envelope_only",
            "complete_three_dimensional_static_return",
        ):
            with self.subTest(scope=scope):
                command = (
                    "$ErrorActionPreference='Stop'; $config=@{parameters=@{}}; "
                    f"$trial=@{{execution_scope='{scope}'}}\n"
                    + self.source[scope_start:scope_end] + "\n"
                    + self.source[label_start:label_end] + "\n"
                    + "$config.parameters | ConvertTo-Json -Compress"
                )
                result = subprocess.run(
                    ["pwsh", "-NoProfile", "-Command", command],
                    cwd=RUNNER.parent,
                    capture_output=True, text=True, encoding="utf-8", timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)["flight_scope"], scope)

    def test_provider_small_inputs_are_frozen_and_consumed_locally(self):
        for variable, filename, option in (
            ("acceleratorProviderPlan", "accelerator_provider_plan.json", "--accelerator-provider-plan"),
            ("acceleratorResolvedCampaign", "accelerator_resolved_campaign.json", "--accelerator-resolved-campaign"),
        ):
            self.assertIn(f"${variable}Local=Copy-RequiredInput ${variable}", self.source)
            self.assertIn(f"'{option}',${variable}Local", self.source)
            self.assertIn(f"Join-Path $artifactSolverDir '{filename}'", self.source)
            capacity_line = next(line for line in self.source.splitlines() if "$requiredBytes+=[int64]" in line and "foreach" in line)
            self.assertIn(f"${variable}", capacity_line)

    def test_trajectory_contract_authority_precedes_its_derived_inputs(self):
        authority = "$trajectoryContractSource=$trajectoryContractInput"
        self.assertLess(
            self.source.index(authority),
            self.source.index("$selectedContract=$trajectoryContractSource"),
        )
        self.assertLess(
            self.source.index(authority),
            self.source.index("$acceleratorGeometryContract=$trajectoryContractSource"),
        )

    def test_optional_contract_controls_pose_and_trajectory_without_rebuilding_pa(self):
        self.assertIn("[string]$ContractPath=''", self.source)
        self.assertIn("$trajectoryContractInput=if([string]::IsNullOrWhiteSpace($ContractPath))", self.source)
        self.assertIn("$trajectoryContractSource=$trajectoryContractInput", self.source)

    def test_direct_trial_accepts_run_input_accelerator_y_pose(self):
        self.assertIn("[Nullable[double]]$AcceleratorYAnchorMm=$null", self.source)
        self.assertIn(
            "$resolvedContract.accelerator.focus_y_anchor.project_y_mm=[double]$AcceleratorYAnchorMm",
            self.source,
        )
        self.assertIn(
            "foreach($resolvedContractPath in @($contract,$acceleratorGeometry,$trajectoryContract))",
            self.source,
        )
        self.assertIn("$config.parameters.accelerator_y_anchor_mm", self.source)

if __name__ == "__main__":
    unittest.main()
