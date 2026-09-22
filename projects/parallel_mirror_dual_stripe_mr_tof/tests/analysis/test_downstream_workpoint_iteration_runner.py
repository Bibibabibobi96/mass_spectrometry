"""Exercise the production stencil dispatcher without invoking a solver."""
from pathlib import Path
import hashlib
import json
import subprocess
from tempfile import TemporaryDirectory
import unittest


PROJECT = Path(__file__).resolve().parents[2]


class WorkpointBootstrapTests(unittest.TestCase):
    def test_recovery_anchor_binds_the_matching_child_materialization(self):
        script = r"""
param($Source,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[System.Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name-eq'Find-AcceptedRecoveryAnchorEvidence'},$true)
Invoke-Expression $node.Extent.Text
function Write-Json($Path,$Value){$Value|ConvertTo-Json -Depth 10|Set-Content -LiteralPath $Path}
function New-Child($Name,$Voltages){
  $dir=Join-Path $Root $Name;New-Item -ItemType Directory -Path $dir|Out-Null
  $observation=Join-Path $dir 'observation.json';$materialization=Join-Path $dir 'materialization.json'
  Write-Json $observation @{residuals=@{}};Write-Json $materialization @{stripe_biases_v=@($Voltages[0],$Voltages[1]);prism_voltages_v=@($Voltages[2],$Voltages[3])}
  return @{observation=$observation;materialization=$materialization;child_manifest=(Join-Path $dir 'run_manifest.json');child_manifest_sha256='identity';decision=(Join-Path $dir 'decision.json')}
}
$anchor=@(-1.,2.,3.,4.);$accepted=New-Child 'accepted' $anchor;$rejected=New-Child 'rejected' @(-1.1,2.,3.,4.)
# A later rejected decision still carries the accepted workpoint.  It must not
# redirect the anchor's observation/materialization identity.
Write-Json $accepted.decision @{observation_record=@{voltages_v=$anchor}}
Write-Json $rejected.decision @{accepted_workpoint=@{voltages_v=$anchor};observation_record=@{voltages_v=@(-1.1,2.,3.,4.)}}
$result=Find-AcceptedRecoveryAnchorEvidence -History @{} -Lineage @{children=@($accepted,$rejected)} -Anchor @{voltages_v=$anchor}
if($result.materialization-ne$accepted.materialization){throw 'Recovery anchor was rebound to a rejected child'}
Write-Output 'RECOVERY_ANCHOR_BINDING=PASS'
"""
        with TemporaryDirectory() as temporary:
            fixture = Path(temporary) / 'recovery-anchor.ps1'
            fixture.write_text(script, encoding='utf-8')
            result = subprocess.run(
                ['pwsh', '-NoProfile', '-File', str(fixture),
                 str(PROJECT / 'analysis/run_downstream_workpoint_iteration.ps1'), temporary],
                cwd=PROJECT, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=40,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('RECOVERY_ANCHOR_BINDING=PASS', result.stdout)

    def test_physical_gate_reverse_fallback_resume_and_voltage_binding(self):
        script = r"""
param($Source,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[System.Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
foreach($name in @('Get-WorkpointBootstrapEvidence','Save-WorkpointBootstrap','Invoke-WorkpointStencil')){
  $node=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name-eq$name},$true)
  Invoke-Expression $node.Extent.Text
}
$repoRoot=$Root;$project='fixture';$python='Invoke-MockPython';$frozenContract='frozen'
$capacitySession=@{lease_id='owner'};$nativeRuntimeSession=@{checkpoint_path=(Join-Path $Root 'family.json')}
[IO.File]::WriteAllText($nativeRuntimeSession.checkpoint_path,'{}')
function Invoke-MockPython {$global:LASTEXITCODE=0}
function Get-ManifestOutputPath {param($ManifestPath,$FileName) return (Join-Path (Split-Path $ManifestPath) $FileName)}
function Write-RunJson {param($Path,$Depth,$Value) $Value|ConvertTo-Json -Depth 30|Set-Content -LiteralPath $Path}
function Save-NativeWorkflowCheckpoint {param($Reason,$WorkflowOutcome) $script:checkpoints++}
function New-CenterTrialArguments {param($Voltages,$ChildRunId) return @{Voltages=$Voltages;ChildRunId=$ChildRunId}}
function New-FixtureChild {
  param($ChildRunId,$Voltages,[bool]$Valid)
  $dir=Join-Path $artifactRoot ('runs/'+$ChildRunId);New-Item -ItemType Directory -Path $dir -Force|Out-Null
  Write-RunJson (Join-Path $dir 'run_manifest.json') 30 @{status='success';run_id=$ChildRunId}
  $actual=@($Voltages);if($script:scenario-eq'wrong_voltage'){$actual[0]+=1}
  Write-RunJson (Join-Path $dir 'two_prism_trial_materialization.json') 30 @{stripe_biases_v=@($actual[0],$actual[1]);prism_voltages_v=@($actual[2],$actual[3])}
  $observation=@{status='full_drift_observed';prism_voltages_v=@($actual[2],$actual[3]);termination_diagnostic=@{physical_collision=(-not$Valid)};residuals=@{};static_return_diagnostic=@{status='detector_not_observed';event_contract_ok=$false}}
  if($Valid){$observation.residuals.Stripe_target_phase_y_minus_origin_mm=1.;$observation.static_return_diagnostic=@{status='detector_hit';event_contract_ok=$true}}
  Write-RunJson (Join-Path $dir 'two_prism_trial_observation.json') 30 $observation
  return Join-Path $dir 'run_manifest.json'
}
function Invoke-MockTrial {
  param($Voltages,$ChildRunId)
  $script:flights+=,@{id=$ChildRunId;voltages=@($Voltages)}
  $valid=$ChildRunId-notlike'*-stencil-2'
  if($script:scenario-eq'reverse_failure'-and$ChildRunId-like'*-stencil-2-reverse'){$valid=$false}
  if($script:scenario-eq'baseline_failure'-and$ChildRunId-like'*-baseline'){$valid=$false}
  $null=New-FixtureChild $ChildRunId $Voltages $valid
}
function Invoke-MockAudit {param($BaselineManifest,$Stripe1PerturbationManifest,$Stripe2PerturbationManifest,$Prism1PerturbationManifest,$Prism2PerturbationManifest,$ContractPath,$RunId,$PythonExe,$CapacityWorkflowSession)
  if($Stripe2PerturbationManifest-notlike'*-stencil-2-reverse*'){throw 'Invalid forward stencil reached audit'}
  $script:audits++
}
$trialRunner='Invoke-MockTrial';$auditRunner='Invoke-MockAudit'
foreach($script:scenario in @('reverse_success','reverse_failure','resume','baseline_failure','wrong_voltage')){
  $artifactRoot=Join-Path $Root $script:scenario;New-Item -ItemType Directory -Path $artifactRoot|Out-Null
  $RunId='new-parent';$script:flights=@();$script:audits=0;$script:checkpoints=0
  $bootstrap=[ordered]@{schema_version=1;seed_voltages_v=@(1.,2.,3.,4.);forward_steps_v=@(.1,.1,.1,.1);children=@()}
  if($script:scenario-eq'resume'){
    $bootstrap.children+=New-FixtureChild 'old-baseline' @(1.,2.,3.,4.) $true
    $bootstrap.children+=New-FixtureChild 'old-stencil-1' @(1.1,2.,3.,4.) $true
    $bootstrap.children+=New-FixtureChild 'old-stencil-2' @(1.,2.1,3.,4.) $false
  }
  $checkpoint=Join-Path $artifactRoot 'bootstrap.json';$failure=$null
  try{$null=Invoke-WorkpointStencil -Bootstrap $bootstrap -BootstrapPath $checkpoint}catch{$failure=$_.Exception.Message}
  if($script:scenario-in@('reverse_success','resume')){
    if($failure-or$script:audits-ne1-or$bootstrap.children.Count-ne5-or$bootstrap.signed_steps_v[1]-ne-.1){throw "Fallback failed: $failure"}
    if($script:scenario-eq'resume'-and($script:flights.Count-ne3-or$bootstrap.children[0]-notlike'*old-baseline*'-or$bootstrap.children[1]-notlike'*old-stencil-1*')){throw 'Resume reran valid children'}
    $invalid=@($bootstrap.attempts|Where-Object{-not$_.passed})
    if($invalid.Count-ne1-or-not$invalid[0].observation_sha256-or$bootstrap.children-contains$invalid[0].child_manifest){throw 'Invalid observation evidence was lost or accepted'}
    $before=$script:flights.Count
    $null=Invoke-WorkpointStencil -Bootstrap $bootstrap -BootstrapPath $checkpoint
    if($script:flights.Count-ne$before){throw 'Completed reverse attempt was repeated'}
  }elseif($script:scenario-eq'reverse_failure'){
    if(-not$failure-or$script:flights.Count-ne4-or$script:audits-ne0-or$bootstrap.children.Count-ne2-or$bootstrap.attempts.Count-ne4){throw 'Reverse failure did not stop immediately'}
  }elseif($script:scenario-eq'baseline_failure'){
    if(-not$failure-or$script:flights.Count-ne1-or$script:audits-ne0-or$bootstrap.children.Count-ne0){throw 'Invalid baseline allowed stencil'}
  }else{if($failure-notlike'*voltages differ*'-or$script:flights.Count-ne1-or$script:audits-ne0){throw 'Wrong materialized voltage was accepted'}}
  if($script:scenario-ne'wrong_voltage'-and($script:checkpoints-lt1-or-not(Test-Path $checkpoint))){throw 'Physical attempt was not checkpointed'}
}
'PHYSICAL_BOOTSTRAP=PASS'
"""
        with TemporaryDirectory() as temporary:
            fixture = Path(temporary) / 'physical.ps1'
            fixture.write_text(script, encoding='utf-8')
            result = subprocess.run(
                ['pwsh', '-NoProfile', '-File', str(fixture),
                 str(PROJECT / 'analysis/run_downstream_workpoint_iteration.ps1'), temporary],
                cwd=PROJECT, capture_output=True, text=True, timeout=40,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PHYSICAL_BOOTSTRAP=PASS', result.stdout)

    def test_resume_skips_completed_stencil_and_checkpoint_preserves_owner(self):
        script = r"""
param($Source,$Root)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$ast=[System.Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
foreach($name in @('Invoke-WorkpointStencil','Save-WorkpointBootstrap','Save-NativeWorkflowCheckpoint')){
  $node=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name-eq$name},$true)
  Invoke-Expression $node.Extent.Text
}
$RunId='new-parent';$artifactRoot=$Root;$repoRoot=$Root;$project='fixture';$python='Invoke-MockPython'
$frozenContract='frozen';$capacitySession=[pscustomobject]@{lease_id='new-lease'}
$script:flights=@();$script:audit=0;$script:checks=0;$script:events=@()
function Invoke-MockPython {$script:checks++;$global:LASTEXITCODE=0}
function Get-WorkpointBootstrapEvidence {param($Manifest,$Voltages) $script:checks++;return @{passed=$true;reasons=@();observation_sha256='A';materialization_sha256='B';child_manifest_sha256='C';child_manifest=$Manifest}}
function Get-ManifestOutputPath {param($ManifestPath,$FileName) return (Join-Path $Root 'materialization.json')}
[IO.File]::WriteAllText((Join-Path $Root 'materialization.json'),' {"stripe_biases_v":[1,2],"prism_voltages_v":[3,4]} ')
function New-CenterTrialArguments {param($Voltages,$ChildRunId) return @{Voltages=$Voltages;ChildRunId=$ChildRunId}}
function Invoke-MockTrial {param($Voltages,$ChildRunId) $script:flights+=,$ChildRunId}
function Invoke-MockAudit {param($BaselineManifest,$Stripe1PerturbationManifest,$Stripe2PerturbationManifest,$Prism1PerturbationManifest,$Prism2PerturbationManifest,$ContractPath,$RunId,$PythonExe,$CapacityWorkflowSession)
  if($BaselineManifest-ne'old-parent-baseline'){throw 'Completed baseline was discarded'}
  $script:audit++
}
function Write-RunJson {param($Path,$Depth,$Value) $script:events+=,@('json',$Path,$Value)}
$trialRunner='Invoke-MockTrial';$auditRunner='Invoke-MockAudit'
$bootstrap=[ordered]@{seed_voltages_v=@(1.,2.,3.,4.);forward_steps_v=@(.1,.1,.1,.1);children=@('old-parent-baseline')}
$null=Invoke-WorkpointStencil -Bootstrap $bootstrap -BootstrapPath 'unused'
if($script:flights.Count-ne4-or$script:flights[0]-ne'new-parent-stencil-1'-or$script:audit-ne1-or$script:checks-ne5){throw 'Resume duplicated a successful flight or reused failed ID'}
$package=@{result_dir=$Root;summary=(Join-Path $Root 'summary.json');run_config='current-config'}
$artifactWorkspaceRoot=$Root;$failureStage='bootstrap_center_1'
$nativeRuntimeSession=[pscustomobject]@{directory=$Root;owner_run_config='original-owner-config';owner_run_directory='original-owner';checkpoint_path=(Join-Path $Root 'family-receipt.json')}
[IO.File]::WriteAllText($nativeRuntimeSession.checkpoint_path,'{}')
function Invoke-RunCapacityLifecycleAdapter {param($Python,$RepoRoot,$Action,$ArtifactRoot,$RunConfig) $script:events+=,@('resident',$RunConfig)}
function Write-VerifiedRunManifest {param($Python,$RepoRoot,$RunConfig,$Status,$Software,$Outputs)
  if($Status-ne'checkpoint'-or$Outputs-notcontains$nativeRuntimeSession.checkpoint_path){throw 'Family was not checkpointed'}
  $script:events+=,@('manifest',$Status)
  Write-Output 'RUN_MANIFEST_VERIFY=PASS'
}
function Update-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session,$RemainingCommittedNewBytes)
  if($RemainingCommittedNewBytes-ne0-or$script:events[-1][0]-ne'resident'){throw 'Commitment dropped before resident update'}
  $script:events+=,@('commitment',0)
}
$script:events=@()
$checkpointOutput=@(Save-NativeWorkflowCheckpoint -Reason 'real child IOB failure')
if($checkpointOutput.Count-ne0){throw 'Checkpoint logging polluted the stencil return value'}
if($script:events[0][1]-ne'original-owner-config'-or-not(Test-Path $nativeRuntimeSession.checkpoint_path)){throw 'Old owner asset was lost'}
$summary=@($script:events|Where-Object{$_[0]-eq'json'})[0][2]
if($summary.reason-ne'real child IOB failure'-or$summary.external_interruption-or-not$summary.resume_requires_new_run_id){throw 'Handled failure provenance differs'}
$script:events=@()
Save-NativeWorkflowCheckpoint -Reason 'external interruption' -ExternalInterruption
$summary=@($script:events|Where-Object{$_[0]-eq'json'})[0][2]
if(-not$summary.external_interruption){throw 'External interruption was disguised'}
$script:events=@()
Save-NativeWorkflowCheckpoint -Reason 'success' -WorkflowOutcome workpoint_complete_downstream_pending -FinalDecision @{terminal_reason='success'}
$summary=@($script:events|Where-Object{$_[0]-eq'json'})[0][2]
if($summary.status-ne'checkpoint'-or$summary.workflow_outcome-ne'workpoint_complete_downstream_pending'-or
   $summary.final_decision.terminal_reason-ne'success'-or-not(Test-Path $nativeRuntimeSession.checkpoint_path)){throw 'Workpoint completion retired the pending downstream family'}
Write-Output 'RESUME_CHECKPOINT=PASS'
"""
        with TemporaryDirectory() as temporary:
            fixture = Path(temporary) / 'resume.ps1'
            fixture.write_text(script, encoding='utf-8')
            result = subprocess.run(
                ['pwsh', '-NoProfile', '-File', str(fixture),
                 str(PROJECT / 'analysis/run_downstream_workpoint_iteration.ps1'), temporary],
                cwd=PROJECT, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=40,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('RESUME_CHECKPOINT=PASS', result.stdout)

    def test_seed_projection_ignores_unused_pa_but_rejects_changed_receipt(self):
        repo = PROJECT.parents[1]
        script = r"""
param($Source,$repoRoot,$python,$SeedTrialManifest,$Inputs)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. (Join-Path $repoRoot 'common/contracts/run_artifact_support.ps1')
$ast=[System.Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name-eq'Get-ManifestOutputPath'},$true)
Invoke-Expression $node.Extent.Text
$project='parallel_mirror_dual_stripe_mr_tof'
$package=@{input_dir=$Inputs}
$sourceText=Get-Content -LiteralPath $Source -Raw
$start=$sourceText.IndexOf('$seedManifest=(Resolve-Path')
$end=$sourceText.IndexOf('$seedVoltages=', $start)
Invoke-Expression $sourceText.Substring($start,$end-$start)
if($seed.stripe_biases_v[0]-ne-24-or$seed.prism_voltages_v[1]-ne-195){throw 'Wrong seed voltages'}
if($seedProjection.assertion_scope-notlike'*other_historical_records_not_asserted'){throw 'Missing projection scope'}
Write-Output 'SEED_PROJECTION=PASS'
"""
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "inputs"
            inputs.mkdir()
            config = root / "run_config.json"
            config.write_text(json.dumps({"schema_version": 1, "project": "parallel_mirror_dual_stripe_mr_tof",
                                          "mode": "finite_3d_two_prism_voltage_trial"}))
            receipt = root / "two_prism_trial_materialization.json"
            receipt.write_text(json.dumps({"stripe_biases_v": [-24, 51], "prism_voltages_v": [196, -195]}))

            def record(path):
                return {"path": str(path), "bytes": path.stat().st_size,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper()}

            manifest = root / "run_manifest.json"
            manifest.write_text(json.dumps({
                "schema_version": 1, "status": "success", "project": "parallel_mirror_dual_stripe_mr_tof",
                "mode": "finite_3d_two_prism_voltage_trial", "run_config": record(config),
                "inputs": {"read_only_analyzer_pa": {"path": str(root / "missing_old.pa"), "bytes": 100, "sha256": "A" * 64}},
                "outputs": [record(receipt)],
            }))
            fixture = root / "fixture.ps1"
            fixture.write_text(script)
            command = ["C:/Program Files/PowerShell/7/pwsh.exe", "-NoProfile", "-File", str(fixture),
                       str(PROJECT / "analysis/run_downstream_workpoint_iteration.ps1"), str(repo),
                       str(repo / ".venv/Scripts/python.exe"), str(manifest), str(inputs)]
            good = subprocess.run(command, cwd=PROJECT, capture_output=True, text=True, encoding="utf-8", check=False, timeout=40)
            self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
            self.assertIn("SEED_PROJECTION=PASS", good.stdout)
            receipt.write_text("{}")
            bad = subprocess.run(command, cwd=PROJECT, capture_output=True, text=True, encoding="utf-8", check=False, timeout=40)
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn("Manifest output hash differs", bad.stdout + bad.stderr)
        source = (PROJECT / "analysis/run_downstream_workpoint_iteration.ps1").read_text()
        self.assertIn("$configuration.parameters.voltage_seed_consumer_projection=$seedProjection", source)
        self.assertIn("$configuration.inputs.voltage_seed_materialization=$frozenSeedMaterialization", source)

    def test_native_stencil_dispatch_and_failure_stop(self):
        script = r"""
param($Source,$Root)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$ast=[System.Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
foreach($name in @('New-CenterTrialArguments','Invoke-WorkpointStencil','Save-WorkpointBootstrap')){
  $node=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name-eq$name},$true)
  Invoke-Expression $node.Extent.Text
}
$GeometryReviewRunPath='geometry';$MirrorRunPath='mirror';$StripeRunPath='stripe';$AcceleratorProviderReceiptPath='provider-receipt'
$NativeSystemRuntimeBundlePath='native-system-bundle.json';$TrajectoryStepScale=1.;$AcceleratorSourceYOffsetMm=-1.7
$python='python';$capacitySession=[pscustomobject]@{lease_id='owner'}
$nativeRuntimeSession=[pscustomobject]@{lease_id='owner';directory=$null;runtime=$null;checkpoint_path=(Join-Path $Root 'not-yet-created.json')}
$NativeCorridorBankRunPath='native-bank'
$SimionExe='simion';$PulseAcceleratorUntilInitialExit=$true;$AcceleratorPulseSchedulePath=''
$TrajectoryProfileId='center_screening'
$artifactRoot=$Root;$RunId='auto';$frozenContract='frozen.json'
$script:flights=@();$script:audits=0;$script:failAt=0
function Write-RunJson {param($Path,$Depth,$Value)}
function Get-WorkpointBootstrapEvidence {param($Manifest,$Voltages) return @{passed=$true;reasons=@();observation_sha256='A';materialization_sha256='B';child_manifest_sha256='C';child_manifest=$Manifest}}
function Invoke-MockTrial {
  param($GeometryReviewRunPath,$MirrorRunPath,$StripeRunPath,$AcceleratorProviderReceiptPath,$Prism1VoltageV,$Prism2VoltageV,$Stripe1VoltageV,$Stripe2VoltageV,$NativeSystemRuntimeBundlePath,$TrajectoryStepScale,$AcceleratorSourceYOffsetMm,$RunId,$PythonExe,$CapacityWorkflowSession,$NativeCorridorBankRunPath,$NativeCorridorRuntimeSession,$SimionExe,[switch]$PulseAcceleratorUntilInitialExit,$TrajectoryProfileId)
  if($NativeCorridorBankRunPath-ne'native-bank'-or$NativeSystemRuntimeBundlePath-ne'native-system-bundle.json'-or$CapacityWorkflowSession.lease_id-ne'owner'){throw 'Lost field, native-system, or owner binding'}
  $script:flights+=,@($Stripe1VoltageV,$Stripe2VoltageV,$Prism1VoltageV,$Prism2VoltageV)
  if($script:failAt-eq$script:flights.Count){throw 'injected solver failure'}
}
function Invoke-MockAudit {
  param($BaselineManifest,$Stripe1PerturbationManifest,$Stripe2PerturbationManifest,$Prism1PerturbationManifest,$Prism2PerturbationManifest,$ContractPath,$RunId,$PythonExe,$CapacityWorkflowSession)
  $script:audits++
  if($script:flights.Count-ne5-or$ContractPath-ne'frozen.json'-or$CapacityWorkflowSession.lease_id-ne'owner'){throw 'Audit ran before the full stencil'}
  if($BaselineManifest-notlike'*auto-baseline*'-or$Prism2PerturbationManifest-notlike'*auto-stencil-4*'){throw 'Wrong lineage'}
}
$trialRunner='Invoke-MockTrial';$auditRunner='Invoke-MockAudit'
$bootstrap=[ordered]@{seed_voltages_v=@(-24.,51.,196.,-195.);forward_steps_v=@(.1,.1,.1,.1);children=@()}
$result=Invoke-WorkpointStencil -Bootstrap $bootstrap -BootstrapPath 'unused'
if($script:audits-ne1-or$result-notlike'*auto-jacobian*'){throw 'Missing automatic audit'}
for($i=0;$i-lt5;$i++){for($j=0;$j-lt4;$j++){
  $expected=$bootstrap.seed_voltages_v[$j]+$(if($i-eq($j+1)){.1}else{0})
  if([math]::Abs($script:flights[$i][$j]-$expected)-gt1e-12){throw 'Wrong independent perturbation'}
}}
$script:flights=@();$script:audits=0;$script:failAt=2;$bootstrap.children=@();$bootstrap.attempts=@()
try{$null=Invoke-WorkpointStencil -Bootstrap $bootstrap -BootstrapPath 'unused';throw 'Failure was swallowed'}
catch{if($_.Exception.Message-ne'injected solver failure'){throw}}
if($script:flights.Count-ne2-or$script:audits-ne0){throw 'Failed flight must stop downstream work'}
Write-Output 'BOOTSTRAP=PASS'
"""
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "fixture.ps1"
            path.write_text(script, encoding="utf-8")
            result = subprocess.run(
                ["C:/Program Files/PowerShell/7/pwsh.exe", "-NoProfile", "-File", str(path),
                 str(PROJECT / "analysis/run_downstream_workpoint_iteration.ps1"), temporary],
                cwd=PROJECT, capture_output=True, text=True, encoding='utf-8', errors='replace', check=False, timeout=40,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("BOOTSTRAP=PASS", result.stdout)

    def test_requires_and_forwards_native_system_runtime_bundle(self):
        source = (PROJECT / "analysis/run_downstream_workpoint_iteration.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("NativeCorridorBankRunPath requires NativeSystemRuntimeBundlePath.", source)
        self.assertIn("$arguments.NativeSystemRuntimeBundlePath=$NativeSystemRuntimeBundlePath", source)
        self.assertIn("native_system_runtime_bundle=(Resolve-Path -LiteralPath $NativeSystemRuntimeBundlePath).Path", source)

    def test_provider_receipt_is_preserved_through_workpoint_and_bunch_handoff(self):
        source = (PROJECT / "analysis/run_downstream_workpoint_iteration.ps1").read_text(encoding="utf-8-sig")
        bunch = (PROJECT / "analysis/run_native_corridor_bunch_screening.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("AcceleratorProviderReceiptPath", source)
        self.assertNotIn("AcceleratorRunPath", source)
        self.assertIn("accelerator_provider_receipt=(Resolve-Path -LiteralPath $AcceleratorProviderReceiptPath).Path", source)
        self.assertIn("$arguments.AcceleratorProviderReceiptPath=$AcceleratorProviderReceiptPath", source)
        self.assertIn("$problem.accelerator_provider_receipt", bunch)
        self.assertIn("$pilotArguments.AcceleratorProviderReceiptPath=$providerReceipt", bunch)
        self.assertIn("$cohortArguments.AcceleratorProviderReceiptPath=$providerReceipt", bunch)
        for obsolete in (
            "LocalWorkbenchRunPath", "LocalResponseFamilyRunPath",
            "LocalRegionOverrideWorkbenchRunPath", "LocalRegionOverrideRegions",
            "LocalHandoffSelectionRunPath", "RuntimeCentralStripeResponse",
            "BootstrapGlobalOperatingPa", "$useNativeCorridor",
        ):
            self.assertNotIn(obsolete, source)

    def test_iteration_parent_consumes_only_named_child_evidence(self):
        source = (PROJECT / "analysis/run_downstream_workpoint_iteration.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("mrtof_downstream_iteration_child_v1", source)
        self.assertIn("'--consumed-output',$observation", source)
        self.assertIn("'--consumed-output',$materialization", source)
        self.assertIn("'--consumed-output',$cacheIdentity", source)
        self.assertIn("'--consumed-output',$childProtectionPath", source)


if __name__ == "__main__":
    unittest.main()
