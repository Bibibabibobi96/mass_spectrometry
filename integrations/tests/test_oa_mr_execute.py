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
        source = RUNNER.read_text(encoding="utf-8")
        start = source.index("    if(-not[string]::IsNullOrWhiteSpace($BatchContinuationRunPath)){")
        stages = "  if($isBunchFlight){\n" + source[start:source.index("  # Static component guards remain live", start)]
        python_helper = source[source.index("function Format-InvariantNumber {"):source.index("function Invoke-SimionStage {")]
        pa_provenance = next(line for line in source.splitlines()
                             if line.strip().startswith("$config['provenance']['pa_bindings']="))
        final_inputs = source[source.index("  $flightInputs=[ordered]@{"):source.index("  foreach($entry in $flightInputs.GetEnumerator())")]
        for name in ("native_global_fallback_pa", "private_accelerator_controller_pa", "read_only_detector_pa"):
            self.assertNotIn(name + "=", final_inputs)
        for case in ("zero", "mixed", "fresh", "science_changed", "gui_missing", "mixed_missing"):
            with self.subTest(case=case), TemporaryDirectory() as directory:
                root = Path(directory)
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
                    trial_path.write_text(json.dumps(trial))
                for index, count in ((1, 1), (2, 2)):
                    if index == 2 and case in ("mixed", "mixed_missing"):
                        continue
                    (parent / "logs" / f"native_two_prism_flight__batch{index:02d}.log").write_text(
                        "".join(f"MRTOF_EVENT terminal ion={i} splat=1 t_us=2 turns=0 x_mm=0 y_mm=0 z_mm=0 vx_mm_us=0 vy_mm_us=0 vz_mm_us=0 central_crossings=0\n" for i in range(1, count+1))
                        + f"status,Fly completed. {count} splats\nIOB_FLIGHT: PASS iob=fixture.iob\n")
                fixture._seal_oa_parent(parent)
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
                dispatch_path.write_text('{"estimation":{"kind":"observed"}}')
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
$runDir=$Current;$runConfig=Join-Path $Current run_config.json
$resultDir=Join-Path $Current results;$logDir=Join-Path $Current logs;$solverDir=Join-Path $Current inputs
$artifactSolverDir=$solverDir;$package=@{input_dir=$solverDir;artifact_run_dir=$Current}
$checkpointConfig=Get-Content $runConfig -Raw|ConvertFrom-Json -AsHashtable
$trial=Get-Content $checkpointConfig.inputs.trial_materialization -Raw|ConvertFrom-Json -Depth 100
$staticFieldLocal=$checkpointConfig.inputs.static_field_binding;$FieldBindingPath=$staticFieldLocal
$staticFieldBinding=Get-Content $Metadata -Raw|ConvertFrom-Json -Depth 100
$staticFieldRequested=$true;$staticFieldMode='native_static_pa';$isBunchFlight=$true
$BatchContinuationRunPath=if($Case-eq'fresh'){''}else{$Parent}
$batchPlanPath=Join-Path $resultDir simion_execution_batch_plan.json
$runtimeDispatchPlanPath=Join-Path $resultDir dispatch.json
$dispatchRequestPath=$null;$resourceProfilesPath=$null;$batchContinuationPlan=$null;$batchContinuationPlanPath=$null
$batchResourceUsagePath=Join-Path $logDir usage.json
$batchRuntimeRoot=$null;$batchRecords=@{};$checkpointOutputs=[Collections.Generic.List[string]]::new()
$staticPaGuards=[Collections.Generic.List[IO.FileStream]]::new()
$bunchSourceLocal=$SourceReceipt;$bunchSourceContract=Get-Content $SourceReceipt -Raw|ConvertFrom-Json
$bunchSelectionRequested=$false;$RetainGuiWorkbench=$Case-eq'gui_missing';$retainGuiWorkbenchFiles=$RetainGuiWorkbench
$ownsHostResourceLease=$false;$resourceLease=@{};$ownsCapacitySession=$false
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
  ''|Set-Content -LiteralPath $spec.stderr
  @{exit_code=0}
 })
 return @{resource_budget_exceeded=$false;processes=$records}
}
""" + python_helper + "\ntry{\n" + stages + r"""
 $config=Get-Content $runConfig -Raw|ConvertFrom-Json -AsHashtable
 if(-not$config.Contains('provenance')){$config['provenance']=[ordered]@{}}
""" + pa_provenance + r"""
 Write-RunJson -Path $runConfig -Depth 100 -Value $config
 $summary=Join-Path $resultDir summary.json
 Write-RunJson -Path $summary -Value @{status='success';qualification='inert_vendor_fixture__workflow_mechanism_only'}
 Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success -Software @('inert vendor fixture') -Outputs @($summary,$rawLog,$batchMergeReceipt)|Out-Null
 @{vendor=@($script:vendor);replay=@($replayBatchIndexes);shared_session=$NativeCorridorRuntimeSession;records=@($batchRecords.Values|ForEach-Object{@{index=$_.index;offset=$_.offset;count=$_.count;log=$_.stdout}})}|ConvertTo-Json -Depth 20 -Compress
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
                final_config = json.loads(config_path.read_text(encoding="utf-8-sig"))
                self.assertEqual(final_config["provenance"]["pa_bindings"]["identity_authority_input"], "static_field_binding")
                self.assertEqual(final_config["provenance"]["pa_bindings"]["payload_consumed"], bool(expected))
                if case != "fresh":
                    self.assertEqual(manifest["inputs"]["reused_batch_001_log"]["path"],
                                     str(parent / "logs/native_two_prism_flight__batch01.log"))
                    self.assertFalse(any(Path(r["path"]).is_relative_to(parent) for r in manifest["outputs"]))
                merged = (current / "logs/native_two_prism_flight.log").read_text()
                self.assertIn("terminal ion=3", merged)
                self.assertIn("Fly completed. 3 splats", merged)

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
foreach($staticFieldRequested in @($false,$true)){
 $solverDir=Join-Path $Root $(if($staticFieldRequested){'static'}else{'native'})
 New-Item -ItemType Directory -Path $solverDir|Out-Null
 $providerSimionRoot=Join-Path $script:pythonRoot 'projects/parallel_mirror_dual_stripe_mr_tof/simion'
 $contract='contract';$acceleratorGeometry='geometry';$trajectoryContract='numerics';$reviewed='reviewed'
 $mirrorLocal='mirror';$stripeLocal='stripe';$acceleratorLocal='accelerator'
 $acceleratorProviderPlanLocal='provider';$compositionPlanLocal='composition-plan';$localScopeLocal=$null;$acceleratorResolvedCampaignLocal='campaign'
 $Prism1VoltageV=190.;$Prism2VoltageV=-186.;$AcceleratorSourceYOffsetMm=0.
 $Stripe1VoltageV=$null;$fixedMirrorStripeAuthorityLocal=$null;$mirrorVoltageVariationLocal=$null
 $bunchSourceLocal=$null;$bunchSelectionRequested=$false;$TrajectoryStepScale=1.
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
$repoRoot=$Repo;$runDir=$Root;$projectId='instrument_assembly';$ContractPath=''
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
 & $Python -B -s -c "import json; from pathlib import Path; from common.contracts.particle_count_policy import validate_standard_particle_count; from projects.parallel_mirror_dual_stripe_mr_tof.analysis.accelerator_component_requirements import build_two_zone_accelerator_requirements; validate_standard_particle_count(100); c=json.loads(Path('projects/parallel_mirror_dual_stripe_mr_tof/config/simion_candidate_two_zone.json').read_text()); assert build_two_zone_accelerator_requirements(c)['variant_id']=='two_zone'"
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
        start = source.index("    $finalBatchPlan=Get-Content")
        block = source[start:source.index(
            "    if($pendingSpecs.Count-eq0-and$existingRecords.Count-eq0){", start)]
        initial = {"inputs": {"simion_execution_batch_plan": "frozen-plan.json"},
                   "parameters": {"unchanged": "frozen source and field"}}
        cases = (
            ("exact", None, [1, 2], [1, 2], initial, False, [1, 2], 0),
            ("formal_index_zero", 0, [0, 1, 2], [0, 1, 2], initial, False, [1, 2], 1),
            ("continuation_replay", None, [1, 2], [2], initial, False, [2], 0),
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
                        "try {\n" + block + "\n} catch {"
                        "@{error=$_.Exception.Message;writes=$script:writes;manifests=$script:manifests}"
                        "|ConvertTo-Json -Compress;exit 1};"
                        "@{writes=$script:writes;manifests=$script:manifests;pending=@($pendingSpecs)}"
                        "|ConvertTo-Json -Compress"
                    )
                    result = subprocess.run(
                        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
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
                            expected = {**initial, "inputs": {"simion_execution_batch_plan": str(batch_plan)}}
                            self.assertEqual(json.loads(run_config.read_text(encoding="utf-8-sig")), expected)
                        else:
                            self.assertEqual(run_config.read_bytes() if run_config.exists() else None, before)

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
        end = source.index("  $retention=Apply-RunArtifactRetention", start)
        block = source[start:end]
        self.assertGreater(start, source.rindex("Write-RunJson -Path $runConfig -Value $config", 0, start))
        self.assertLess(end, source.rindex("Write-VerifiedRunManifest"))
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
        self.assertIn("Start-ObservedFormalProcess -DispatchPlanPath", self.source)
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
            "continuation requires one sealed whole-batch log",
            "-OnProcessCompleted $checkpointAction",
            "-Status checkpoint",
        ):
            self.assertIn(token, self.source)
        self.assertIn("$replayBatchIndexes-contains$index", self.source)
        self.assertIn("$replayBatchIndexes=@(", self.source)
        self.assertIn(
            "$replayBatchIndexes=@($replanned.batches|ForEach-Object{[int]$_.index})",
            self.source,
        )

    def test_failure_removes_only_disposable_trajectory_cache_before_publication(self):
        catch = self.source.index("}catch{")
        failed = self.source.index("Publish-OaMrFailureManifest -Status failed", catch)
        cache_cleanup = self.source.index(
            "Get-ChildItem -LiteralPath $temporarySolverDir -File -Filter 'trj*.tmp'",
            catch,
        )
        self.assertLess(cache_cleanup, failed)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_terminal_publication_is_independent_of_payload_seal(self):
        source = RUNNER.read_text(encoding="utf-8")
        start = source.index("  # The public writer publishes and reads back identities once.")
        tail = source[start:]
        catch = tail.index("}catch{\n  $failureRecord=$_")
        publication, cleanup = tail[:catch], tail[catch:]
        capacity_publication = source[source.index("  $sourceTimingDiagnostic=$null;"):start]
        helper_start = source.index("function Publish-OaMrFailureManifest {")
        helper = source[helper_start:source.index("function Remove-TemporarySolverDirectory", helper_start)]
        for owned, failure in ((True, "none"), (True, "writer"), (True, "seal"),
                               (True, "science"), (True, "failure_writer"), (True, "terminal_capacity"),
                               (False, "none"), (False, "light")):
            with self.subTest(owned=owned, failure=failure), TemporaryDirectory() as temporary:
                root = Path(temporary)
                script = root / "fixture.ps1"
                script.write_text(r"""param($Source,$Root,$Owned,$Failure)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ownsCapacitySession=$Owned-eq'True';$ownsHostResourceLease=$false
$trajectoryRecording=$null;$trajectoryRetentionReason='';$trajectoryPayloadNeedsSeal=$false
$terminalPublicationAttempted=$false;$terminalStatus='interrupted';$deferredHostCompletionNotification=$false
$python='python';$repoRoot='repo';$runDir=$Root;$resultDir=$Root;$logDir=$Root
$runConfig=Join-Path $Root run_config.json;$summary=Join-Path $Root summary.json
'{}'|Set-Content $runConfig
$manifestPath=Join-Path $Root run_manifest.json
'{"status":"checkpoint"}'|Set-Content $manifestPath
$package=@{artifact_run_dir=$Root};$artifactRoot='artifacts';$projectId='instrument_assembly'
$RunId='fixture';$failureStage='analysis';$observed=@{status='bunch_observed'};$hostOutcome='failed'
$capacitySession=@{status='active'};$resourceLease=$null
$isBunchFlight=$false;$staticFieldRequested=$false;$nativeBankKey='fixture'
$staticPaGuards=@();$temporaryAcceleratorRuntimeSession=$null;$temporarySolverDir=$null;$batchRuntimeRoot=$null
$retainGuiWorkbenchFiles=$false;$manifestOutputs=@();$script:calls=[Collections.Generic.List[string]]::new()
function Write-Host {param($Object)}
function Write-RunJson {param($Path,$Value) $script:calls.Add('summary:'+$Value.status)}
function Write-VerifiedRunManifest {param($Python,$RepoRoot,$RunConfig,$Status,$Software,$Outputs,[switch]$DeferCapacityFinalization)
 if(-not$DeferCapacityFinalization){throw 'terminal writer must defer capacity finalization'}
 $script:calls.Add('writer:'+$Status)
 if($Failure-in@('writer','failure_writer')){throw 'writer failed'}
 @{status=$Status}|ConvertTo-Json|Set-Content $manifestPath
}
function Complete-FailedRun {throw 'failure must not invoke light finalizer'}
function Apply-RunArtifactRetention {param($Python,$RepoRoot,$RunConfig) return 'retention'}
function Update-ArtifactWorkflowCapacitySession {
 param($Python,$RepoRoot,$Session,$ProtectedCacheKeys,$RemainingCommittedNewBytes)
 $script:calls.Add('capacity')
 throw 'terminal capacity failed'
}
function Invoke-RunCapacityLifecycleAdapter {param($Python,$RepoRoot,$Action,$ArtifactRoot,$RunConfig)
 $script:calls.Add('light:'+ $Action);if($Failure-eq'light'){throw 'light capacity failed'}
}
function Remove-RunPackageExecutionAlias {param($Package)}
function Exit-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session) $script:calls.Add('release')}
function Invoke-ProjectPython {param($Arguments)
 $script:calls.Add('seal')
 if($Arguments-notcontains'seal-stopped-payload'-or$Arguments[-1]-eq''){throw 'wrong seal authority or missing reason'}
 if($Failure-eq'seal'){throw 'seal failed'}
}
""" + helper + "\n$caught=$false;try{try{\n" +
                    ("throw 'science failed'\n" if failure in ("science", "failure_writer") else
                     (capacity_publication if failure == "terminal_capacity" else "") + publication) +
                    cleanup + "\n}catch{$caught=$true};@{calls=@($script:calls);caught=$caught;status=$terminalStatus;manifest=(Get-Content $manifestPath -Raw|ConvertFrom-Json).status}|ConvertTo-Json -Compress",
                    encoding="utf-8")
                result = subprocess.run(["pwsh", "-NoProfile", "-File", str(script), str(RUNNER), str(root), str(owned), failure],
                                        cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                observed = json.loads(result.stdout)
                expected_status = "failed" if failure in ("science", "failure_writer", "writer", "terminal_capacity") else "success"
                writers = [x for x in observed["calls"] if x.startswith("writer:")]
                expected_writers = (["writer:success", "writer:failed"] if failure == "writer"
                                    else ["writer:" + expected_status])
                self.assertEqual(writers, expected_writers)
                if failure == "terminal_capacity":
                    self.assertLess(observed["calls"].index("capacity"), observed["calls"].index("writer:failed"))
                    self.assertNotIn("writer:success", observed["calls"])
                self.assertEqual(observed["status"], expected_status)
                self.assertEqual(observed["manifest"], "checkpoint" if failure in ("writer", "failure_writer") else expected_status)
                self.assertEqual(observed["caught"], failure != "none")
                self.assertEqual("release" in observed["calls"], owned)
                self.assertEqual("seal" in observed["calls"], owned and failure not in ("writer", "failure_writer"))
                if "seal" in observed["calls"]:
                    self.assertLess(observed["calls"].index("release"), observed["calls"].index("seal"))
                if not owned:
                    self.assertIn("light:finalize-ready", observed["calls"])

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
        self.assertIn("if($ownsHostResourceLease-and$null-ne$resourceLease)", self.source)

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
