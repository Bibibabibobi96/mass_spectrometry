[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$GeometryReviewRunPath,
  [Parameter(Mandatory)][string]$MirrorRunPath,
  [Parameter(Mandatory)][string]$StripeRunPath,
  [Parameter(Mandatory)][string]$AcceleratorRunPath,
  [Parameter(Mandatory)][double]$Prism1VoltageV,
  [Parameter(Mandatory)][double]$Prism2VoltageV,
  [Nullable[double]]$Stripe1VoltageV=$null,
  [Nullable[double]]$Stripe2VoltageV=$null,
  [Nullable[double]]$Prism2ExtractionVoltageV=$null,
  [Nullable[double]]$Prism1ExtractionVoltageV=$null,
  [Nullable[double]]$PrismSwitchTimeUs=$null,
  [string]$ReferenceTransportRunPath='',
  [string]$LocalWorkbenchRunPath='',
  [switch]$ContinueMainDrift,
  [switch]$ConstrainXSymmetryPlane,
  [string]$TrajectoryProfileId='',
  [string]$RunId='',
  [string]$SimionExe='',
  [string]$PythonExe=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

function Copy-RequiredInput {
  param([string]$Source,[string]$Destination,[string]$Label)
  if(-not(Test-Path -LiteralPath $Source -PathType Leaf)){throw "$Label is missing: $Source"}
  Copy-VerifiedRunInput -Source $Source -Destination $Destination
}
function Invoke-ProjectPython {
  param([string[]]$Arguments)
  Push-Location -LiteralPath $repoRoot;$saved=$env:PYTHONPATH
  try{$env:PYTHONPATH=$repoRoot;& $python @Arguments;if($LASTEXITCODE-ne 0){throw "Python stage failed: $($Arguments -join ' ')"}}
  finally{$env:PYTHONPATH=$saved;Pop-Location}
}
function Invoke-SimionStage {
  param([string]$Stage,[string[]]$Arguments)
  Push-Location -LiteralPath $solverDir
  try{& $simion @Arguments 2>&1|Tee-Object -FilePath (Join-Path $logDir "$Stage.log");if($LASTEXITCODE-ne 0){throw "SIMION stage failed: $Stage"}}
  finally{Pop-Location}
}
function Remove-TemporarySolverDirectory {
  param([string]$Path)
  if([string]::IsNullOrWhiteSpace($Path)-or-not(Test-Path -LiteralPath $Path)){return}
  $resolved=[IO.Path]::GetFullPath($Path)
  $temporaryRoot=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([IO.Path]::DirectorySeparatorChar)+[IO.Path]::DirectorySeparatorChar
  if(-not$resolved.StartsWith($temporaryRoot,[StringComparison]::OrdinalIgnoreCase)){throw "Refusing to remove non-temporary solver directory: $resolved"}
  Remove-Item -LiteralPath $resolved -Recurse -Force
}

$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$simion=if($SimionExe){[IO.Path]::GetFullPath($SimionExe)}else{Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'}
if(-not(Test-Path -LiteralPath $python -PathType Leaf)){throw "Python executable is missing: $python"}
if(-not(Test-Path -LiteralPath $simion -PathType Leaf)){throw "SIMION executable is missing: $simion"}
foreach($value in @($Prism1VoltageV,$Prism2VoltageV)){if([double]::IsNaN($value)-or[double]::IsInfinity($value)){throw 'Prism voltages must be finite'}}
if (($null -eq $Stripe1VoltageV) -ne ($null -eq $Stripe2VoltageV)) { throw 'Stripe1VoltageV and Stripe2VoltageV must be supplied together.' }
if($null-ne$Prism2ExtractionVoltageV-and[string]::IsNullOrWhiteSpace($ReferenceTransportRunPath)){throw 'Prism extraction requires ReferenceTransportRunPath.'}
if($null-eq$Prism2ExtractionVoltageV-and-not[string]::IsNullOrWhiteSpace($ReferenceTransportRunPath)){throw 'ReferenceTransportRunPath is only valid for prism extraction.'}
foreach($value in @($Stripe1VoltageV,$Stripe2VoltageV)){if($null-ne$value-and([double]::IsNaN($value)-or[double]::IsInfinity($value))){throw 'Stripe voltages must be finite'}}
foreach($value in @($Prism1ExtractionVoltageV,$Prism2ExtractionVoltageV,$PrismSwitchTimeUs)){if($null-ne$value-and([double]::IsNaN($value)-or[double]::IsInfinity($value))){throw 'Prism switching parameters must be finite'}}
if($null-ne$Prism1ExtractionVoltageV-and$null-eq$Prism2ExtractionVoltageV){throw 'Prism1ExtractionVoltageV requires a P2 extraction switch.'}
if($null-ne$PrismSwitchTimeUs-and$PrismSwitchTimeUs-le 0){throw 'PrismSwitchTimeUs must be positive.'}
$geometryRun=(Resolve-Path -LiteralPath $GeometryReviewRunPath).Path
$mirrorRun=(Resolve-Path -LiteralPath $MirrorRunPath).Path
$stripeRun=(Resolve-Path -LiteralPath $StripeRunPath).Path
$acceleratorRun=(Resolve-Path -LiteralPath $AcceleratorRunPath).Path
$referenceRun=if([string]::IsNullOrWhiteSpace($ReferenceTransportRunPath)){$null}else{(Resolve-Path -LiteralPath $ReferenceTransportRunPath).Path}
$localWorkbenchRun=if([string]::IsNullOrWhiteSpace($LocalWorkbenchRunPath)){$null}else{(Resolve-Path -LiteralPath $LocalWorkbenchRunPath).Path}
$geometrySimion=Join-Path $geometryRun 'simion'
$acceleratorSimion=Join-Path $acceleratorRun 'simion'
$geometryManifest=Join-Path $geometryRun 'run_manifest.json'
$mirrorManifest=Join-Path $mirrorRun 'run_manifest.json'
$stripeManifest=Join-Path $stripeRun 'run_manifest.json'
$acceleratorManifest=Join-Path $acceleratorRun 'run_manifest.json'
$referenceManifest=if($null-eq$referenceRun){$null}else{Join-Path $referenceRun 'run_manifest.json'}
$localWorkbenchManifest=if($null-eq$localWorkbenchRun){$null}else{Join-Path $localWorkbenchRun 'run_manifest.json'}
if($null-ne$localWorkbenchRun-and$null-ne$Prism2ExtractionVoltageV){throw 'Local replacement trials are static-injection voltage-definition trials and cannot switch prism voltages.'}
foreach($manifest in @($geometryManifest,$mirrorManifest,$stripeManifest,$acceleratorManifest,$referenceManifest,$localWorkbenchManifest)){
  if($null-eq$manifest){continue}
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $manifest --require-status success
  if($LASTEXITCODE-ne 0){throw "Upstream run manifest is not verified success: $manifest"}
}
if([string]::IsNullOrWhiteSpace($RunId)){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__sim__simion__two-prism-trial-n1'}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
. (Join-Path $PSScriptRoot 'analyzer_local_family_support.ps1')
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'finite_3d_two_prism_voltage_trial' -Software @('SIMION 2020','Python 3.11') `
  -RetentionContractEnabled -RetentionClass compact `
  -AdditionalDirectories @('simion') -UseShortExecutionPath
$runDir=$package.run_dir;$resultDir=$package.result_dir;$logDir=$package.log_dir;$solverDir=Join-Path $runDir 'simion'
$runConfig=$package.run_config;$summary=$package.summary;$artifactRoot=Join-Path $workspaceRoot 'artifacts'
$terminalized=$false;$failureStage='preflight';$lease=$null;$hostOutcome='failed';$temporarySolverDir=$null
try{
  $sourceAnalyzer=Join-Path $geometrySimion 'mrtof_analyzer.pa0'
  $sourceAccelerator=Join-Path $acceleratorSimion 'mrtof_accelerator.pa0'
  $sourceDetector=Join-Path $geometrySimion 'mrtof_detector.pa#'
  $localWorkbenchConfig=$null;$localFamilies=@();$localBaseMaterialization=$null
  $localCacheSentinelPaths=@();$localCacheSentinelHashes=@()
  if($null-ne$localWorkbenchRun){
    $localWorkbenchConfig=Get-Content -Raw -LiteralPath (Join-Path $localWorkbenchRun 'run_config.json')|ConvertFrom-Json -Depth 40
    if($localWorkbenchConfig.mode-ne'analyzer_local_replacement_workbench'){throw 'LocalWorkbenchRunPath is not a local replacement workbench.'}
    $sourceAnalyzer=[string]$localWorkbenchConfig.inputs.global_analyzer_pa0
    $sourceAccelerator=Join-Path $localWorkbenchRun 'simion\mrtof_accelerator.pa0'
    $sourceDetector=Join-Path $localWorkbenchRun 'simion\mrtof_detector.pa#'
    $localBaseMaterialization=Get-Content -Raw -LiteralPath (Join-Path $localWorkbenchRun 'inputs\two_prism_trial_materialization.json')|ConvertFrom-Json -Depth 30
    $familySpecs=@(
      @('mirror_turn_negative','negative_mirror'),@('stripe_mirror_bridge_negative','negative_bridge'),
      @('central_transport','central'),@('stripe_mirror_bridge_positive','positive_bridge'),
      @('mirror_turn_positive','positive_mirror')
    )
    [double]$localScale=$localWorkbenchConfig.parameters.local_mesh_mm_per_gu[0]
    for($familyIndex=0;$familyIndex-lt$familySpecs.Count;$familyIndex++){
      $familyRun=Split-Path -Parent ([string]$localWorkbenchConfig.inputs.local_family_manifests[$familyIndex])
      $family=Get-VerifiedAnalyzerLocalFamily -SourceRunPath $familyRun -ExpectedRegion $familySpecs[$familyIndex][0] -ExpectedScale $localScale -Label $familySpecs[$familyIndex][1] -PythonExe $python -RepoRoot $repoRoot
      $family.frozen_identity=$family.identity_source
      Resolve-AnalyzerLocalFamilyCacheGeneration -Family $family -PythonExe $python -RepoRoot $repoRoot -CacheRoot (Join-Path $artifactRoot 'common\simion\pa_family_cache')|Out-Null
      Assert-AnalyzerLocalFamilyCacheReadOnly -Family $family
      $sentinel=Join-Path $family.generation_directory ("{0}.pa#"-f([string]$family.contract.family_prefix))
      $localCacheSentinelPaths+=$sentinel
      $localFamilies+=$family
    }
    $localCacheSentinelHashes=@($localCacheSentinelPaths|ForEach-Object{(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash})
  }
  $reviewedContract=Join-Path $geometrySimion 'simion_prototype_contract.json'
  $selectedContract=Join-Path $acceleratorSimion 'accelerator_focus_voltage_trial.json'
  $trajectoryContractSource=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\config\simion_candidate_two_zone.json'
  $mirrorSummary=Join-Path $mirrorRun 'summary.json'
  $stripeSummary=Join-Path $stripeRun 'summary.json'
  $acceleratorReceipt=Join-Path $acceleratorRun 'results\accelerator_focus_voltage_trial_receipt.json'
  $referenceReceiptSource=if($null-eq$referenceRun){$null}else{Join-Path $referenceRun 'results\two_prism_trial_materialization.json'}
  $referenceLogSource=if($null-eq$referenceRun){$null}else{Join-Path $referenceRun 'logs\native_two_prism_flight.log'}
  $trialTool=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\two_prism_simion_trial.py'
  $voltageizerSource=Join-Path $PSScriptRoot 'voltageize_analyzer_pa0.lua'
  $iobBuilderSource=Join-Path $PSScriptRoot 'build_three_component_iob.lua'
  $localIobBuilderSource=Join-Path $PSScriptRoot 'build_local_refinement_iob.lua'
  $basisAdjusterSource=Join-Path $repoRoot 'common\simion\adjust_operating_pa_from_basis.lua'
  $basisVoltageSource=Join-Path $repoRoot 'common\simion\measure_pa_basis_voltage.lua'
  $iobSeedSource=Join-Path $repoRoot 'common\simion\assets\iob_instance_seeds\3_instance_seed.iob'
  $localIobSeedSource=Join-Path $repoRoot 'common\simion\assets\iob_instance_seeds\8_instance_seed.iob'
  $placeholderSources=@(1..8|ForEach-Object{Join-Path $repoRoot ('common\simion\assets\iob_instance_seeds\iob_seed_placeholder_{0:D2}.pa0'-f$_)})
  $programSource=Join-Path $PSScriptRoot 'mrtof_candidate.lua'
  $counterSource=Join-Path $PSScriptRoot 'mirror_cycle_counter.lua'
  $mapSource=Join-Path $PSScriptRoot 'candidate_voltage_map.lua'
  $launcherSource=Join-Path $PSScriptRoot 'run_iob_flight.lua'
  foreach($path in @($sourceAnalyzer,$sourceAccelerator,$sourceDetector,$reviewedContract,$selectedContract,$trajectoryContractSource,$mirrorSummary,$stripeSummary,$acceleratorReceipt,$trialTool,$voltageizerSource,$iobBuilderSource,$localIobBuilderSource,$basisAdjusterSource,$basisVoltageSource,$iobSeedSource,$localIobSeedSource,$placeholderSources,$programSource,$counterSource,$mapSource,$launcherSource)){
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Required P1/P2 trial input is missing: $path"}
  }
  $failureStage='capacity_preflight'
  $requiredBytes=[int64]0
  foreach($path in @($reviewedContract,$selectedContract,$trajectoryContractSource,$mirrorSummary,$stripeSummary,$acceleratorReceipt,$trialTool,$voltageizerSource,$iobBuilderSource,$localIobBuilderSource,$basisAdjusterSource,$basisVoltageSource,$iobSeedSource,$localIobSeedSource,$placeholderSources,$programSource,$counterSource,$mapSource,$launcherSource)){$requiredBytes+=[int64](Get-Item -LiteralPath $path).Length}
  if($null-ne$localWorkbenchRun){
    # Reserve one output PA0, one private operating base and at most four
    # standalone response copies per local region.  The response bytes come
    # from a complete verified family, but a temporary `.pa` suffix removes
    # SIMION's `.paN` family association without another Refine.
    $capacityLocalNames=@('local_negative_mirror.pa0','local_negative_bridge.pa0','local_central.pa0','local_positive_bridge.pa0','local_positive_mirror.pa0')
    for($familyIndex=0;$familyIndex-lt$localFamilies.Count;$familyIndex++){
      $family=$localFamilies[$familyIndex]
      $prefix=[string]$family.contract.family_prefix
      $requiredBytes+=[int64](Get-Item -LiteralPath (Join-Path $family.generation_directory "$prefix.pa0")).Length
      foreach($responseId in 5..8){
        $requiredBytes+=[int64](Get-Item -LiteralPath (Join-Path $family.generation_directory ("{0}.pa{1}"-f$prefix,$responseId))).Length
      }
      $requiredBytes+=[int64](Get-Item -LiteralPath (Join-Path $localWorkbenchRun "simion\$($capacityLocalNames[$familyIndex])")).Length
    }
  }
  $protectedPaths=@($package.artifact_run_dir)
  if($null-ne$localWorkbenchRun){$protectedPaths+=@($localWorkbenchRun)+@($localFamilies.generation_directory)}
  $startup=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -RequiredHeadroomBytes $requiredBytes -ProtectedPaths $protectedPaths
  $startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json';Write-RunJson -Path $startupPath -Depth 14 -Value $startup
  $failureStage='freeze_small_inputs'
  $contract=Copy-RequiredInput $selectedContract (Join-Path $solverDir 'accelerator_focus_voltage_trial.json') 'selected-energy contract'
  $trajectoryContract=Copy-RequiredInput $trajectoryContractSource (Join-Path $solverDir 'trajectory_numerics_contract.json') 'trajectory numerics contract'
  $reviewed=Copy-RequiredInput $reviewedContract (Join-Path $solverDir 'simion_prototype_contract.json') 'reviewed geometry contract'
  $mirrorLocal=Copy-RequiredInput $mirrorSummary (Join-Path $solverDir 'mirror_exact_k_summary.json') 'exact-K mirror summary'
  $stripeLocal=Copy-RequiredInput $stripeSummary (Join-Path $solverDir 'dual_stripe_exact_k_summary.json') 'exact-K Stripe summary'
  $acceleratorLocal=Copy-RequiredInput $acceleratorReceipt (Join-Path $solverDir 'accelerator_focus_voltage_trial_receipt.json') 'accelerator voltage receipt'
  $referenceLocal=$null;$referenceLogLocal=$null
  if($null-ne$referenceRun){
    $referenceLocal=Copy-RequiredInput $referenceReceiptSource (Join-Path $solverDir 'reference_transport_materialization.json') 'reference transport receipt'
    $referenceLogLocal=Copy-RequiredInput $referenceLogSource (Join-Path $logDir 'reference_transport.log') 'reference transport log'
  }
  foreach($pair in @(
    @($programSource,'mrtof_three_component_candidate.lua'),@($counterSource,'mrtof_three_component_candidate.mirror_cycle_counter.lua'),
    @($mapSource,'mrtof_three_component_candidate.voltage_map.lua'),@($launcherSource,'run_iob_flight.lua'),
    @($iobBuilderSource,'build_three_component_iob.lua'),@($localIobBuilderSource,'build_local_refinement_iob.lua'),
    @($basisAdjusterSource,'adjust_operating_pa_from_basis.lua'),@($basisVoltageSource,'measure_pa_basis_voltage.lua'),
    @($iobSeedSource,'3_instance_seed.iob'),@($localIobSeedSource,'8_instance_seed.iob'),
    @($placeholderSources[0],'iob_seed_placeholder_01.pa0'),@($placeholderSources[1],'iob_seed_placeholder_02.pa0'),
    @($placeholderSources[2],'iob_seed_placeholder_03.pa0'),@($placeholderSources[3],'iob_seed_placeholder_04.pa0'),
    @($placeholderSources[4],'iob_seed_placeholder_05.pa0'),@($placeholderSources[5],'iob_seed_placeholder_06.pa0'),
    @($placeholderSources[6],'iob_seed_placeholder_07.pa0'),@($placeholderSources[7],'iob_seed_placeholder_08.pa0'),
    @($voltageizerSource,'voltageize_analyzer_pa0.lua'),
    @($trialTool,'two_prism_simion_trial.py'))){
    Copy-RequiredInput $pair[0] (Join-Path $solverDir $pair[1]) $pair[1]|Out-Null
  }
  $fly2Input=Join-Path $solverDir 'downstream_trial_source.input.fly2'
  $sidecar=Join-Path $solverDir 'mrtof_three_component_candidate.operating_point.lua'
  $trialReceipt=Join-Path $resultDir 'two_prism_trial_materialization.json'
  $failureStage='materialize_trial'
  $materializeArguments=@('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial','materialize',
    '--contract',$contract,'--trajectory-contract',$trajectoryContract,'--reviewed-contract',$reviewed,'--mirror-summary',$mirrorLocal,'--stripe-summary',$stripeLocal,
    '--accelerator-receipt',$acceleratorLocal,'--prism-1-v',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$Prism1VoltageV)),
    '--prism-2-v',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$Prism2VoltageV)),
    '--fly2',$fly2Input,'--sidecar',$sidecar,'--receipt',$trialReceipt)
  if($null-ne$Stripe1VoltageV){
    $materializeArguments+=@('--stripe-1-v',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$Stripe1VoltageV)),
      '--stripe-2-v',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$Stripe2VoltageV)))
  }
  if($ContinueMainDrift){$materializeArguments+='--continue-main-drift'}
  if($null-ne$Prism2ExtractionVoltageV){
    $materializeArguments+=@('--prism-2-extraction-v',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$Prism2ExtractionVoltageV)),
      '--reference-transport-receipt',$referenceLocal,'--reference-transport-log',$referenceLogLocal)
    if($null-ne$PrismSwitchTimeUs){$materializeArguments+=@('--prism-switch-time-us',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$PrismSwitchTimeUs)))}
    if($null-ne$Prism1ExtractionVoltageV){$materializeArguments+=@('--prism-1-extraction-v',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$Prism1ExtractionVoltageV)))}
  }
  if($ConstrainXSymmetryPlane){$materializeArguments+='--constrain-x-symmetry-plane'}
  if(-not[string]::IsNullOrWhiteSpace($TrajectoryProfileId)){$materializeArguments+=@('--trajectory-profile-id',$TrajectoryProfileId)}
  Invoke-ProjectPython -Arguments $materializeArguments
  $trial=Get-Content -LiteralPath $trialReceipt -Raw -Encoding UTF8|ConvertFrom-Json
  $temporarySolverDir=Join-Path ([IO.Path]::GetTempPath()) ('mrtof_downstream_'+[guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Path $temporarySolverDir|Out-Null
  $temporaryAnalyzer=Join-Path $temporarySolverDir 'mrtof_analyzer.pa0'
  $temporaryIob=Join-Path $temporarySolverDir 'mrtof_three_component_candidate.iob'
  $temporaryP2Basis=$null;$temporaryP1Basis=$null
  $posePath=Join-Path $resultDir 'resolved_iob_pose.json'
  $poseCode="import json,sys; from pathlib import Path; from projects.parallel_mirror_dual_stripe_mr_tof.analysis.split_candidate_geometry import resolve_split_iob_origins; p=Path(sys.argv[1]); c=json.loads(p.read_text(encoding='utf-8')); Path(sys.argv[2]).write_text(json.dumps({'origins_mm':resolve_split_iob_origins(p),'mesh_mm_per_gu':c['simion']['component_mesh_mm_per_gu']},indent=2)+'\n',encoding='utf-8')"
  Invoke-ProjectPython -Arguments @('-c',$poseCode,$reviewed,$posePath)
  $pose=Get-Content -LiteralPath $posePath -Raw -Encoding UTF8|ConvertFrom-Json
  $originArguments=@()
  foreach($name in @('analyzer','accelerator','detector')){foreach($value in @($pose.origins_mm.$name)){$originArguments+=[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$value)}}
  $upstreamPaths=@($sourceAnalyzer,$sourceAccelerator,$sourceDetector)
  $upstreamHashes=@($upstreamPaths|ForEach-Object{(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash})
  if($null-ne$Prism2ExtractionVoltageV){
    $sourceP2Basis=[IO.Path]::ChangeExtension($sourceAnalyzer,'.pa17')
    $temporaryP2Basis=[IO.Path]::ChangeExtension($temporaryAnalyzer,'.pa17')
    Copy-RequiredInput $sourceP2Basis $temporaryP2Basis 'P2 electrode-17 basis array'|Out-Null
    if($null-ne$Prism1ExtractionVoltageV){
      $sourceP1Basis=[IO.Path]::ChangeExtension($sourceAnalyzer,'.pa16')
      $temporaryP1Basis=[IO.Path]::ChangeExtension($temporaryAnalyzer,'.pa16')
      Copy-RequiredInput $sourceP1Basis $temporaryP1Basis 'P1 electrode-16 basis array'|Out-Null
    }
  }
  $failureStage='voltageize_temporary_analyzer';$lease=Enter-HostExecutionLease -Role SIMION -RunId $RunId
  $voltageArguments=@('--nogui','--noprompt','lua',(Join-Path $solverDir 'voltageize_analyzer_pa0.lua'),$sourceAnalyzer,$temporaryAnalyzer)+@($trial.analyzer_electrode_voltages_v|ForEach-Object{[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$_)})
  Invoke-SimionStage -Stage 'voltageize_temporary_analyzer' -Arguments $voltageArguments
  $temporaryAnalyzerHash=(Get-FileHash -LiteralPath $temporaryAnalyzer -Algorithm SHA256).Hash
  $voltageReceipt=Join-Path $resultDir 'temporary_analyzer_voltageization_receipt.json'
  $localAdjustmentReceipts=@()
  if($null-ne$localWorkbenchRun){
    $failureStage='adjust_local_operating_replacements'
    $baseDownstream=@([double]$localBaseMaterialization.stripe_biases_v[0],[double]$localBaseMaterialization.stripe_biases_v[1],[double]$localBaseMaterialization.prism_voltages_v[0],[double]$localBaseMaterialization.prism_voltages_v[1])
    $targetDownstream=@([double]$trial.stripe_biases_v[0],[double]$trial.stripe_biases_v[1],[double]$trial.prism_voltages_v[0],[double]$trial.prism_voltages_v[1])
    $deltaVoltages=@();$changedIndices=@();for($index=0;$index-lt 4;$index++){$delta=[double]$targetDownstream[$index]-[double]$baseDownstream[$index];$deltaVoltages+=$delta;if([math]::Abs($delta)-gt 1e-15){$changedIndices+=$index}}
    $localNames=@('local_negative_mirror.pa0','local_negative_bridge.pa0','local_central.pa0','local_positive_bridge.pa0','local_positive_mirror.pa0')
    $temporaryLocalPaths=@()
    if($changedIndices.Count-eq 0){
      for($index=0;$index-lt$localFamilies.Count;$index++){$temporaryLocalPaths+=Join-Path $localWorkbenchRun "simion\$($localNames[$index])"}
    }else{
      $normalizationCsv=Join-Path $resultDir 'global_basis_voltage.csv'
      Invoke-SimionStage -Stage 'measure_global_basis_voltage' -Arguments @('--nogui','--noprompt','lua',(Join-Path $solverDir 'measure_pa_basis_voltage.lua'),[IO.Path]::ChangeExtension($sourceAnalyzer,'.pa2'),[IO.Path]::ChangeExtension($sourceAnalyzer,'.pa#'),2,$normalizationCsv)
      $basisVoltage=[double](Import-Csv -LiteralPath $normalizationCsv).basis_voltage_V
      $basisText=(@($changedIndices|ForEach-Object{[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$basisVoltage)})-join',')
      $deltaText=(@($changedIndices|ForEach-Object{[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$deltaVoltages[$_])})-join',')
      for($index=0;$index-lt$localFamilies.Count;$index++){
        $family=$localFamilies[$index]
        $prefix=[string]$family.contract.family_prefix
        # A copied `.paN` can retain SIMION family bookkeeping and write back
        # after the apparent solver exit.  Copy each verified response as an
        # ordinary standalone `.pa`; the source generation is also sealed
        # read-only at filesystem level.
        $privateBasisPaths=@()
        foreach($changedIndex in $changedIndices){
          $responseId=5+$changedIndex
          $basisSource=Join-Path $family.generation_directory ("{0}.pa{1}"-f$prefix,$responseId)
          $privateBasis=Join-Path $temporarySolverDir ("family{0}_response{1}.pa"-f($index+1),($changedIndex+1))
          Copy-VerifiedRunInput -Source $basisSource -Destination $privateBasis -VerificationAttempts 3|Out-Null
          $privateBasisPaths+=$privateBasis
        }
        $basisPaths=($privateBasisPaths-join'|')
        $privateOperatingBase=Join-Path $temporarySolverDir ("family{0}_operating_base.pa0"-f($index+1))
        Copy-VerifiedRunInput -Source (Join-Path $localWorkbenchRun "simion\$($localNames[$index])") -Destination $privateOperatingBase -VerificationAttempts 3|Out-Null
        $temporaryLocal=Join-Path $temporarySolverDir $localNames[$index]
        Invoke-SimionStage -Stage ("adjust_local_{0}"-f$family.label) -Arguments @('--nogui','--noprompt','lua',(Join-Path $solverDir 'adjust_operating_pa_from_basis.lua'),$privateOperatingBase,$temporaryLocal,$basisPaths,$basisText,$deltaText)
        $temporaryLocalPaths+=$temporaryLocal
        $localAdjustmentReceipts+=[ordered]@{region=$family.region;source_cache_generation=$family.generation_directory;private_standalone_basis_copies=$true;basis_voltage_v=$basisVoltage;downstream_voltage_deltas_v=@($deltaVoltages);temporary_output_sha256=(Get-FileHash -LiteralPath $temporaryLocal -Algorithm SHA256).Hash;refine_performed=$false}
      }
    }
  }
  Write-RunJson -Path $voltageReceipt -Depth 14 -Value ([ordered]@{schema_version=1;role='mrtof_temporary_analyzer_voltageization';status='success';method=if($null-eq$localWorkbenchRun){'SIMION_PA_object_fast_adjust_save_as'}elseif($localAdjustmentReceipts.Count-eq 0){'global_fast_adjust_plus_reused_local_baseline_pa0'}else{'global_fast_adjust_plus_nonzero_local_basis_deltas'};source_pa0=$sourceAnalyzer;source_sha256=$upstreamHashes[0];temporary_output_sha256=$temporaryAnalyzerHash;electrode_voltages_v=@($trial.analyzer_electrode_voltages_v);local_adjustments=$localAdjustmentReceipts;source_family_read_only=$true;refine_performed=$false;temporary_output_retained=$false})
  $failureStage='build_temporary_iob'
  if($null-eq$localWorkbenchRun){
    $buildArguments=@('--nogui','--noprompt','lua',(Join-Path $solverDir 'build_three_component_iob.lua'),'--',
      (Join-Path $solverDir '3_instance_seed.iob'),$temporaryAnalyzer,$sourceAccelerator,$sourceDetector,$temporaryIob,
      (Join-Path $solverDir 'mrtof_three_component_candidate.lua'),$fly2Input)+$originArguments+@('read_only_voltageized')
  }else{
    $localConfigSource=Join-Path $localWorkbenchRun 'simion\mrtof_local_replacement.local_refinement.lua'
    $localConfig=Copy-RequiredInput $localConfigSource (Join-Path $solverDir 'local_trial_refinement.lua') 'local replacement sidecar'
    $localOrigins=@();$localOrigins+=,@($pose.origins_mm.analyzer)
    foreach($family in $localFamilies){$localOrigins+=,@($family.contract.patch_origin_project_mm)}
    $localOrigins+=,@($pose.origins_mm.accelerator);$localOrigins+=,@($pose.origins_mm.detector)
    $localOriginArguments=@();foreach($origin in $localOrigins){foreach($value in $origin){$localOriginArguments+=[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$value)}}
    $buildArguments=@('--nogui','--noprompt','lua',(Join-Path $solverDir 'build_local_refinement_iob.lua'),'--',(Join-Path $solverDir '8_instance_seed.iob'),$temporaryAnalyzer)+$temporaryLocalPaths+@($sourceAccelerator,$sourceDetector,$temporaryIob,(Join-Path $solverDir 'mrtof_three_component_candidate.lua'),$fly2Input,$localConfig)+$localOriginArguments
  }
  Invoke-SimionStage -Stage 'build_temporary_iob' -Arguments $buildArguments
  $temporaryFly2=[IO.Path]::ChangeExtension($temporaryIob,'.fly2')
  if(-not(Test-RunFilesIdentical -Left $fly2Input -Right $temporaryFly2)){throw 'IOB companion Fly2 differs from the frozen downstream-trial source'}
  if(@(Compare-Object $upstreamHashes @($upstreamPaths|ForEach-Object{(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash})).Count-ne 0){throw 'Read-only IOB build changed an upstream PA'}
  if($localCacheSentinelPaths.Count-and@(Compare-Object $localCacheSentinelHashes @($localCacheSentinelPaths|ForEach-Object{(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash})).Count-ne 0){throw 'Temporary IOB build changed an immutable local PA cache sentinel'}
  $failureStage='native_two_prism_flight'
  Invoke-SimionStage -Stage 'native_two_prism_flight' -Arguments @('--nogui','--noprompt','lua',(Join-Path $solverDir 'run_iob_flight.lua'),$temporaryIob)
  if(@(Compare-Object $upstreamHashes @($upstreamPaths|ForEach-Object{(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash})).Count-ne 0){throw 'Runtime Fast Adjust changed an upstream PA'}
  if($localCacheSentinelPaths.Count-and@(Compare-Object $localCacheSentinelHashes @($localCacheSentinelPaths|ForEach-Object{(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash})).Count-ne 0){throw 'SIMION flight changed immutable local PA-family bookkeeping'}
  foreach($family in $localFamilies){Resolve-AnalyzerLocalFamilyCacheGeneration -Family $family -PythonExe $python -RepoRoot $repoRoot -CacheRoot (Join-Path $artifactRoot 'common\simion\pa_family_cache')|Out-Null}
  $rawLog=Join-Path $logDir 'native_two_prism_flight.log';$observation=Join-Path $resultDir 'two_prism_trial_observation.json'
  $failureStage='analyze_trial'
  Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial','analyze','--log',$rawLog,'--trial-receipt',$trialReceipt,'--output',$observation)
  $observed=Get-Content -LiteralPath $observation -Raw -Encoding UTF8|ConvertFrom-Json
  $observedResiduals=if($null-ne$observed.PSObject.Properties['residuals']){$observed.residuals}else{$null}
  $observedExtraction=if($null-ne$observed.PSObject.Properties['extraction_diagnostic']){$observed.extraction_diagnostic}else{$null}
  $summaryValue=[ordered]@{schema_version=1;role='mrtof_finite_3d_two_prism_voltage_trial';status='success';qualification='single_center_trial__not_an_operating_point';stripe_biases_v=@($trial.stripe_biases_v);prism_voltages_v=@($Prism1VoltageV,$Prism2VoltageV);transport_status=$observed.status;extraction_diagnostic=$observedExtraction;residuals=$observedResiduals;reason='The fixed reviewed geometry was flown once from the physical 5-eV pre-acceleration state. A detector hit proves only the prototype event chain; post-switch mirror turns and timing remain explicit and do not qualify a target-K operating point.'}
  Write-RunJson -Path $summary -Value $summaryValue
  $config=Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  Remove-TemporarySolverDirectory -Path $temporarySolverDir;$temporarySolverDir=$null
  $config.inputs=[ordered]@{geometry_run_manifest=$geometryManifest;mirror_run_manifest=$mirrorManifest;stripe_run_manifest=$stripeManifest;accelerator_run_manifest=$acceleratorManifest;reference_transport_run_manifest=$referenceManifest;local_workbench_run_manifest=$localWorkbenchManifest;trajectory_numerics_contract=$trajectoryContract;iob_builder=if($null-eq$localWorkbenchRun){Join-Path $solverDir 'build_three_component_iob.lua'}else{Join-Path $solverDir 'build_local_refinement_iob.lua'};read_only_analyzer_pa0=$sourceAnalyzer;read_only_accelerator_pa0=$sourceAccelerator;read_only_detector_pa=$sourceDetector;trial_materialization=$trialReceipt;frozen_source_fly2=$fly2Input}
  $config.parameters.prism_1_voltage_v=$Prism1VoltageV;$config.parameters.prism_2_voltage_v=$Prism2VoltageV;$config.parameters.stripe_biases_v=@($trial.stripe_biases_v);$config.parameters.continue_main_drift=[bool]$ContinueMainDrift;$config.parameters.pa_binding_mode=if($null-eq$localWorkbenchRun){'temporary_voltageized_analyzer__immutable_family'}elseif($localAdjustmentReceipts.Count-eq 0){'global_fast_adjust_plus_reused_local_baseline_pa0'}else{'global_fast_adjust_plus_nonzero_local_basis_deltas__no_refine'};$config.parameters.constrain_x_symmetry_plane=[bool]$ConstrainXSymmetryPlane;$config.parameters.trajectory_profile=$trial.trajectory_profile;$config.parameters.prism_switch=$trial.prism_switch;Write-RunJson -Path $runConfig -Value $config
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $failureStage='capacity_terminal';$maximum=[int64](Get-ChildItem -LiteralPath $package.artifact_run_dir -Recurse -File|Measure-Object Length -Sum).Sum
  $terminal=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -ProtectedPaths @($package.artifact_run_dir) -KnownMeasuredBytes ([int64]$startup.measured_after_bytes) -MaximumNewArtifactBytes $maximum
  $terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json';Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success -Software @('SIMION 2020','Python 3.11') -Outputs @($summary,$rawLog,$observation,$trialReceipt,$voltageReceipt,$posePath,$startupPath,$terminalPath,$retention)
  $terminalized=$true;$hostOutcome='success';Write-Host "MRTOF_TWO_PRISM_TRIAL=PASS RUN_ID=$RunId TRANSPORT=$($observed.status)"
}catch{
  if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_finite_3d_two_prism_voltage_trial' -Reason $_.Exception.Message -Software @('SIMION 2020','Python 3.11') -Status failed -FailureStage $failureStage;$terminalized=$true};throw
}finally{
  if(-not$terminalized-and(Test-Path -LiteralPath $runConfig -PathType Leaf)){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_finite_3d_two_prism_voltage_trial' -Reason 'Runner stopped before terminal evidence publication.' -Software @('SIMION 2020','Python 3.11') -Status interrupted -FailureStage $failureStage;$hostOutcome='interrupted'}
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome $hostOutcome -RunId $RunId};Remove-RunPackageExecutionAlias -Package $package
  if($null-ne$temporarySolverDir){Remove-TemporarySolverDirectory -Path $temporarySolverDir}
}
