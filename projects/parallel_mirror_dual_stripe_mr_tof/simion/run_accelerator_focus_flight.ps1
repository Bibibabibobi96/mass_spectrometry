[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$GeometryReviewRunPath,
  [Parameter(Mandatory)][string]$AcceleratorFamilyRunPath,
  [Parameter(Mandatory)][string]$StandaloneComponentRunPath,
  [ValidateSet('accelerator_focus_center_fly2','accelerator_focus_bunch_fly2')][string]$SourceKey='accelerator_focus_center_fly2',
  [string]$BaselineContractPath='',
  [string]$TrajectoryProfileId='',
  [string]$FocusCalibrationRunPath='',
  [string]$EnergyCalibrationRunPath='',
  [Nullable[double]]$FirstGapDropV=$null,
  [string]$ExactKRunManifest='',
  [Nullable[double]]$SelectedNetGainCenterV=$null,
  [double]$Finite3dGainCorrectionV=0.0,
  [string]$RunId='',
  [string]$SimionExe='',
  [string]$PythonExe=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

function Copy-RequiredInput {
  param([string]$Source,[string]$Destination,[string]$Label)
  if(-not(Test-Path -LiteralPath $Source -PathType Leaf)){throw "$Label is missing: $Source"}
  Copy-VerifiedRunInput -Source $Source -Destination $Destination -VerificationAttempts 3
}
function Invoke-ProjectPython {
  param([string[]]$Arguments)
  Push-Location -LiteralPath $repoRoot
  $saved=$env:PYTHONPATH
  try{$env:PYTHONPATH=$repoRoot;& $python @Arguments;if($LASTEXITCODE -ne 0){throw "Python failed: $($Arguments -join ' ')"}}
  finally{$env:PYTHONPATH=$saved;Pop-Location}
}
function Invoke-SimionStage {
  param([Parameter(Mandatory)][string]$Stage,[Parameter(Mandatory)][string[]]$Arguments)
  Push-Location -LiteralPath $solverDir
  try{& $simion @Arguments 2>&1|Tee-Object -FilePath (Join-Path $logDir "$Stage.log");if($LASTEXITCODE-ne0){throw "SIMION stage failed: $Stage"}}
  finally{Pop-Location}
}
function Format-InvariantNumber {
  param([double]$Value)
  [string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$Value)
}
function Assert-ManifestOutputIdentity {
  param([Parameter(Mandatory)]$Manifest,[Parameter(Mandatory)][string]$Path,[Parameter(Mandatory)][string]$Label)
  $resolved=(Resolve-Path -LiteralPath $Path).Path
  $records=@($Manifest.outputs|Where-Object{[string]::Equals([IO.Path]::GetFullPath([string]$_.path),$resolved,[StringComparison]::OrdinalIgnoreCase)})
  if($records.Count-ne1){throw "$Label is not uniquely frozen by its verified run manifest: $resolved"}
  $item=Get-Item -LiteralPath $resolved -Force;$hash=(Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash
  if([int64]$records[0].bytes-ne[int64]$item.Length-or[string]$records[0].sha256-ne$hash){throw "$Label differs from its manifest identity: $resolved"}
}
function ConvertTo-ArtifactRunPath {
  param([Parameter(Mandatory)][string]$Path)
  $full=[IO.Path]::GetFullPath($Path)
  $executionRoot=[IO.Path]::GetFullPath([string]$package.run_dir).TrimEnd([char[]]@(92,47))
  $artifactRunRoot=[IO.Path]::GetFullPath([string]$package.artifact_run_dir).TrimEnd([char[]]@(92,47))
  if($full.Equals($executionRoot,[StringComparison]::OrdinalIgnoreCase)){return $artifactRunRoot}
  if($full.StartsWith($executionRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){
    return $artifactRunRoot+$full.Substring($executionRoot.Length)
  }
  return $full
}

$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$simion=if($SimionExe){[IO.Path]::GetFullPath($SimionExe)}else{Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'}
if(-not(Test-Path -LiteralPath $simion -PathType Leaf)){throw "SIMION executable is missing: $simion"}
$baselinePath=if($BaselineContractPath){(Resolve-Path -LiteralPath $BaselineContractPath).Path}else{Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\config\simion_candidate_two_zone.json'}
$baseline=Get-Content -LiteralPath $baselinePath -Raw -Encoding UTF8|ConvertFrom-Json
$exactKManifestPath=if($ExactKRunManifest){(Resolve-Path -LiteralPath $ExactKRunManifest).Path}else{''}
if($exactKManifestPath -and $null-ne$SelectedNetGainCenterV){throw 'exact-K manifest binding and a manual selected net-gain centre are mutually exclusive'}
if(-not $exactKManifestPath -and $null-eq$SelectedNetGainCenterV){throw 'provide an exact-K manifest or one explicit selected net-gain centre'}
if($null-ne$SelectedNetGainCenterV -and (-not([double]::IsFinite([double]$SelectedNetGainCenterV)) -or [double]$SelectedNetGainCenterV -le 0)){throw 'selected net-gain centre must be finite and positive'}
if(-not([double]::IsFinite($Finite3dGainCorrectionV))){throw 'finite-3D gain correction must be finite'}
$countKey=if($SourceKey-eq'accelerator_focus_center_fly2'){'center_particle_count'}else{'candidate_bunch_particle_count'}
$expectedCount=[int]$baseline.particle_source.$countKey
if($expectedCount -le 0){throw 'accelerator focus source has invalid particle count'}
$geometryRun=(Resolve-Path -LiteralPath $GeometryReviewRunPath).Path
$geometrySimion=Join-Path $geometryRun 'simion'
$geometryResults=Join-Path $geometryRun 'results'
$sourceManifestPath=Join-Path $geometrySimion 'prototype_input_manifest.json'
$acceleratorFamilyRun=(Resolve-Path -LiteralPath $AcceleratorFamilyRunPath).Path
$standaloneComponentRun=(Resolve-Path -LiteralPath $StandaloneComponentRunPath).Path
if($FocusCalibrationRunPath -and $null-ne$FirstGapDropV){throw 'calibration evidence and a manual first-gap override are mutually exclusive'}
if($FocusCalibrationRunPath -and $Finite3dGainCorrectionV-ne0.0){throw 'focus-calibration replay and a finite-3D gain correction are mutually exclusive'}
if($EnergyCalibrationRunPath -and $Finite3dGainCorrectionV-ne0.0){throw 'energy-calibration evidence and a manual finite-3D gain correction are mutually exclusive'}
if($FocusCalibrationRunPath -and $EnergyCalibrationRunPath){throw 'focus-calibration replay and a finite-3D gain correction are mutually exclusive'}
$calibrationRun=if($FocusCalibrationRunPath){(Resolve-Path -LiteralPath $FocusCalibrationRunPath).Path}else{''}
$energyCalibrationRun=if($EnergyCalibrationRunPath){(Resolve-Path -LiteralPath $EnergyCalibrationRunPath).Path}else{''}
if([string]::IsNullOrWhiteSpace($RunId)){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+"__sim__simion__mrtof-accelerator-focus-n$expectedCount"}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
. (Join-Path $repoRoot 'common\simion\short_pa_path_support.ps1')
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'two_zone_accelerator_first_time_focus' -Software @('SIMION 2020','Python 3.11') `
  -RetentionContractEnabled -RetentionClass solver_review -RetentionReason 'Independent accelerator z=0 first-time-focus evidence.' `
  -AdditionalDirectories @('simion') -UseShortExecutionPath
$runDir=$package.run_dir;$inputDir=$package.input_dir;$resultDir=$package.result_dir;$logDir=$package.log_dir;$solverDir=Join-Path $runDir 'simion'
$runConfig=$package.run_config;$summary=$package.summary;$artifactRoot=Join-Path $workspaceRoot 'artifacts';$cacheRoot=Join-Path $artifactRoot 'common\simion\pa_family_cache'
$terminalized=$false;$failureStage='preflight';$hostExecutionOutcome='failed';$lease=$null
$basisLinkDir=$null;$operatingBuildDir=$null
try{
  $lease=Enter-HostExecutionLease -Role SIMION -Stage prepare -RunId $RunId
  foreach($upstream in @(
    @($acceleratorFamilyRun,'accelerator_pa_family_build','accelerator family'),
    @($standaloneComponentRun,'analyzer_local_replacement_workbench','standalone component workbench')
  )){
    & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') (Join-Path $upstream[0] 'run_manifest.json') --require-status success --require-project $projectId --require-mode $upstream[1]
    if($LASTEXITCODE-ne0){throw "$($upstream[2]) manifest verification failed"}
  }
  $selectedEnergySource=if($exactKManifestPath){'verified_exact_k_manifest'}else{'explicit_component_diagnostic'}
  if($exactKManifestPath){
    & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $exactKManifestPath --require-status success --require-project $projectId --require-mode analytic_mirror_exact_k_operating_point
    if($LASTEXITCODE-ne0){throw 'exact-K manifest verification failed'}
    $exactKManifest=Get-Content -LiteralPath $exactKManifestPath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 40
    $exactKSummaryRecords=@($exactKManifest.outputs|Where-Object{[IO.Path]::GetFileName([string]$_.path)-eq'summary.json'})
    if($exactKSummaryRecords.Count-ne1){throw 'exact-K manifest must publish exactly one summary.json'}
    $exactKSummaryPath=[IO.Path]::GetFullPath([string]$exactKSummaryRecords[0].path)
    Assert-ManifestOutputIdentity -Manifest $exactKManifest -Path $exactKSummaryPath -Label 'exact-K summary'
    $exactKSummary=Get-Content -LiteralPath $exactKSummaryPath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 40
    if($exactKSummary.status-ne'native_stripe_on_exact_k_system_point_found__3d_validation_pending'){
      throw 'exact-K summary is not the active Stripe-on operating-point authority'
    }
    $SelectedNetGainCenterV=[double]$exactKSummary.selected_operating_point.energy_per_charge_v
    if(-not([double]::IsFinite([double]$SelectedNetGainCenterV)) -or [double]$SelectedNetGainCenterV-le0){throw 'exact-K selected axial energy must be finite and positive'}
  }
  $selectedEnergyText=([double]$SelectedNetGainCenterV).ToString('R',[Globalization.CultureInfo]::InvariantCulture)
  if($calibrationRun){
    $calibrationManifestPath=Join-Path $calibrationRun 'run_manifest.json'
    & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $calibrationManifestPath --require-status success --require-project $projectId --require-mode two_zone_accelerator_first_time_focus --require-local-run-config
    if($LASTEXITCODE-ne0){throw 'focus calibration evidence manifest verification failed'}
    $calibrationManifest=Get-Content -LiteralPath $calibrationManifestPath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 40
    $calibrationTrialPath=[string]$calibrationManifest.inputs.trial_contract.path
    $calibrationAnalysisPath=Join-Path $calibrationRun 'results\accelerator_focus_analysis.json'
    Assert-ManifestOutputIdentity -Manifest $calibrationManifest -Path $calibrationAnalysisPath -Label 'calibration focus analysis'
    $calibrationSourceSha=[string]$calibrationManifest.inputs.consumed_fly2.sha256
  }
  if($energyCalibrationRun){
    $energyCalibrationManifestPath=Join-Path $energyCalibrationRun 'run_manifest.json'
    & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $energyCalibrationManifestPath --require-status success --require-project $projectId --require-mode accelerator_finite_3d_exit_energy_calibration --require-local-run-config
    if($LASTEXITCODE-ne0){throw 'accelerator energy-calibration manifest verification failed'}
    $energyCalibrationManifest=Get-Content -LiteralPath $energyCalibrationManifestPath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 40
    $energyProposalRecords=@($energyCalibrationManifest.outputs|Where-Object{[IO.Path]::GetFileName([string]$_.path)-eq'accelerator_exit_energy_calibration_proposal.json'})
    if($energyProposalRecords.Count-ne1){throw 'accelerator energy-calibration manifest must publish exactly one correction proposal'}
    $energyCalibrationProposalPath=[IO.Path]::GetFullPath([string]$energyProposalRecords[0].path)
    Assert-ManifestOutputIdentity -Manifest $energyCalibrationManifest -Path $energyCalibrationProposalPath -Label 'accelerator energy-calibration proposal'
    $energyCalibrationProposal=Get-Content -LiteralPath $energyCalibrationProposalPath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 20
    if($energyCalibrationProposal.role-ne'mrtof_accelerator_finite_3d_energy_correction_proposal'-or
        $energyCalibrationProposal.status-ne'derived'-or
        $energyCalibrationProposal.qualification-ne'unity_response_first_correction_only__real_simion_exit_required'){
      throw 'accelerator energy-calibration proposal identity is invalid'
    }
    $proposalTarget=[double]$energyCalibrationProposal.target_axial_energy_per_charge_v
    $proposalCorrection=[double]$energyCalibrationProposal.proposed_cumulative_correction_v
    if(-not([double]::IsFinite($proposalTarget))-or$proposalTarget-ne$SelectedNetGainCenterV){throw 'accelerator energy-calibration exact-K target differs from the selected net-gain centre'}
    if(-not([double]::IsFinite($proposalCorrection))){throw 'accelerator energy-calibration correction must be finite'}
    $Finite3dGainCorrectionV=$proposalCorrection
  }
  $gainCorrectionText=$Finite3dGainCorrectionV.ToString('R',[Globalization.CultureInfo]::InvariantCulture)
  $names=@('mrtof_three_component_candidate.voltage_map.lua','simion_prototype_contract.json')
  $baseOperatingPoint=Join-Path $geometrySimion 'mrtof_three_component_candidate.operating_point.lua'
  $geometryReview=Join-Path $geometrySimion 'three_component_geometry_review.json'
  $structureReport=Join-Path $geometryResults 'iob_structure_report.txt'
  $sourceBuilderPath=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\materialize_accelerator_focus_source.py'
  $trialBuilderPath=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\accelerator_focus_voltage_trial.py'
  $focusTheoryPath=Join-Path $repoRoot 'projects\orthogonal_accelerator\analysis\accelerator_time_focus.py'
  $operatingPointAdapterPath=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\simion_operating_point_variation.py'
  $phaseContractPath=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\drift_phase_contract.py'
  $familyManifestPath=Join-Path $acceleratorFamilyRun 'run_manifest.json'
  $familyManifest=Get-Content -LiteralPath $familyManifestPath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 40
  $familyContract=Join-Path $acceleratorFamilyRun 'inputs\simion_candidate_two_zone.json'
  $familyGem=Join-Path $acceleratorFamilyRun 'simion\mrtof_accelerator.gem'
  $familyPublication=Join-Path $acceleratorFamilyRun 'results\pa_family_cache_result.json'
  if(-not(Test-Path -LiteralPath $familyContract -PathType Leaf)){throw 'accelerator family frozen contract is missing'}
  foreach($item in @($familyGem,$familyPublication)){Assert-ManifestOutputIdentity -Manifest $familyManifest -Path $item -Label 'accelerator family output'}
  $declaredPublication=Get-Content -LiteralPath $familyPublication -Raw -Encoding UTF8|ConvertFrom-Json -Depth 40
  $declaredFamilyGeneration=(Resolve-Path -LiteralPath ([string]$declaredPublication.generation_directory)).Path
  $geometryCompatibilityCode=@'
import sys
from pathlib import Path
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import load_contract
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.accelerator_focus_voltage_trial import require_reviewed_geometry
current=load_contract(Path(sys.argv[1]))
family=load_contract(Path(sys.argv[2]),inherited_detector_return_path=current["accelerator"]["detector_return_path"])
require_reviewed_geometry(current,family)
'@
  Invoke-ProjectPython -Arguments @('-c',$geometryCompatibilityCode,$baselinePath,$familyContract)
  $standaloneManifestPath=Join-Path $standaloneComponentRun 'run_manifest.json'
  $standaloneManifest=Get-Content -LiteralPath $standaloneManifestPath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 40
  $standaloneConfig=Get-Content -LiteralPath (Join-Path $standaloneComponentRun 'run_config.json') -Raw -Encoding UTF8|ConvertFrom-Json -Depth 40
  $sourceAnalyzer=[string]$standaloneConfig.inputs.global_analyzer_pa
  $sourceAccelerator=[string]$standaloneConfig.inputs.accelerator_pa
  $sourceDetector=[string]$standaloneConfig.inputs.detector_pa
  $standaloneReviewed=[string]$standaloneConfig.inputs.reviewed_geometry_contract
  foreach($item in @($sourceAnalyzer,$sourceAccelerator,$sourceDetector)){
    if([IO.Path]::GetExtension($item)-ine'.pa'){throw 'focus analyzer and detector inputs must be direct standalone .pa files'}
    Assert-ManifestOutputIdentity -Manifest $standaloneManifest -Path $item -Label 'standalone component PA'
  }
  if($calibrationRun){
    foreach($component in @(@('standalone_analyzer_pa',$sourceAnalyzer),@('standalone_detector_pa',$sourceDetector))){
      $componentRecord=@($standaloneManifest.outputs|Where-Object{[string]::Equals([IO.Path]::GetFullPath([string]$_.path),[IO.Path]::GetFullPath([string]$component[1]),[StringComparison]::OrdinalIgnoreCase)})
      if($componentRecord.Count-ne1-or$componentRecord[0].sha256-ne$calibrationManifest.inputs.($component[0]).sha256){throw 'focus calibration must retain the analyzer and detector PA identities'}
    }
  }
  if(-not(Test-Path -LiteralPath $standaloneReviewed -PathType Leaf)){throw 'standalone component reviewed geometry contract is missing'}
  if(-not(Test-RunFilesIdentical -Left $standaloneReviewed -Right (Join-Path $geometrySimion 'simion_prototype_contract.json'))){throw 'standalone components and the reviewed focus assembly do not share one geometry contract'}
  $familyAdapter=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\simion_pa_family_cache.py'
  $standaloneBankValidator=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\simion_standalone_bank.py'
  $commonFamilyCache=Join-Path $repoRoot 'common\simion\pa_family_cache.py'
  $composerPath=Join-Path $repoRoot 'common\simion\compose_standalone_pa.lua'
  $iobBuilderPath=Join-Path $PSScriptRoot 'build_three_component_iob.lua'
  $iobSeedPath=Join-Path $repoRoot 'common\simion\assets\iob_instance_seeds\3_instance_seed.iob'
  $sources=@($sourceManifestPath,$baselinePath,$geometryReview,$structureReport,$sourceBuilderPath,$baseOperatingPoint,
    $trialBuilderPath,$focusTheoryPath,$operatingPointAdapterPath,$phaseContractPath,$familyAdapter,$standaloneBankValidator,$commonFamilyCache,$composerPath,$iobBuilderPath,$iobSeedPath,$familyContract,$familyGem,$familyPublication,
    $standaloneManifestPath,(Join-Path $standaloneComponentRun 'run_config.json'),$standaloneReviewed,$sourceAnalyzer,$sourceDetector,
    (Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\simion\mrtof_accelerator_focus.lua'),
    (Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\simion\mirror_cycle_counter.lua'),
    (Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\simion\run_iob_flight.lua'),
    (Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\accelerator_focus_simion_analysis.py'))
  foreach($name in $names){$sources+=(Join-Path $geometrySimion $name)}
  if($calibrationRun){$sources+=@($calibrationManifestPath,$calibrationTrialPath,$calibrationAnalysisPath)}
  if($energyCalibrationRun){$sources+=@($energyCalibrationManifestPath,$energyCalibrationProposalPath)}
  if($exactKManifestPath){$sources+=@($exactKManifestPath,$exactKSummaryPath)}
  [int64]$copyBytes=0
  foreach($path in $sources){if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "focus input is missing: $path"};$copyBytes+=(Get-Item -LiteralPath $path).Length}
  # The reviewed standalone accelerator is not consumed, but its size is a
  # conservative estimate for the one composed operating PA retained by this run.
  $copyBytes+=2*(Get-Item -LiteralPath $sourceAccelerator).Length
  $failureStage='capacity_preflight'
  $startupProtected=@($package.artifact_run_dir,$geometryRun,$acceleratorFamilyRun,$standaloneComponentRun,$declaredFamilyGeneration)
  if($calibrationRun){$startupProtected+=$calibrationRun}
  if($energyCalibrationRun){$startupProtected+=$energyCalibrationRun}
  if($exactKManifestPath){$startupProtected+=(Split-Path -Parent $exactKManifestPath)}
  $startup=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -RequiredHeadroomBytes $copyBytes -ProtectedPaths $startupProtected
  $startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json';Write-RunJson -Path $startupPath -Depth 14 -Value $startup
  $failureStage='freeze_reviewed_pa_iob'
  foreach($name in $names){Copy-RequiredInput (Join-Path $geometrySimion $name) (Join-Path $solverDir $name) "reviewed $name"|Out-Null}
  Copy-RequiredInput $sourceManifestPath (Join-Path $solverDir 'prototype_input_manifest.json') 'source manifest'|Out-Null
  Copy-RequiredInput $geometryReview (Join-Path $solverDir 'three_component_geometry_review.json') 'geometry review receipt'|Out-Null
  Copy-RequiredInput $structureReport (Join-Path $solverDir 'iob_structure_report.txt') 'IOB structure report'|Out-Null
  $frozenFamilyManifest=Copy-RequiredInput $familyManifestPath (Join-Path $inputDir 'accelerator_family_run_manifest.json') 'accelerator family manifest'
  $frozenFamilyPublication=Copy-RequiredInput $familyPublication (Join-Path $inputDir 'accelerator_family_cache_publication.json') 'accelerator family publication'
  $frozenFamilyContract=Copy-RequiredInput $familyContract (Join-Path $inputDir 'accelerator_family_contract.json') 'accelerator family contract'
  $frozenStandaloneManifest=Copy-RequiredInput $standaloneManifestPath (Join-Path $inputDir 'standalone_component_run_manifest.json') 'standalone component manifest'
  $frozenStandaloneConfig=Copy-RequiredInput (Join-Path $standaloneComponentRun 'run_config.json') (Join-Path $inputDir 'standalone_component_run_config.json') 'standalone component run config'
  $frozenStandaloneReviewed=Copy-RequiredInput $standaloneReviewed (Join-Path $inputDir 'standalone_component_reviewed_geometry.json') 'standalone component reviewed geometry'
  $frozenBaseOperatingPoint=Copy-RequiredInput $baseOperatingPoint (Join-Path $inputDir 'reviewed_operating_point.lua') 'reviewed operating point'
  $frozenOperatingPointAdapter=Copy-RequiredInput $operatingPointAdapterPath (Join-Path $inputDir 'simion_operating_point_variation.py') 'operating-point adapter'
  $frozenPhaseContract=Copy-RequiredInput $phaseContractPath (Join-Path $inputDir 'drift_phase_contract.py') 'drift-phase contract resolver'
  if($energyCalibrationRun){
    $frozenEnergyCalibrationManifest=Copy-RequiredInput $energyCalibrationManifestPath (Join-Path $inputDir 'energy_calibration_run_manifest.json') 'energy-calibration run manifest'
    $frozenEnergyCalibrationProposal=Copy-RequiredInput $energyCalibrationProposalPath (Join-Path $inputDir 'energy_calibration_proposal.json') 'energy-calibration proposal'
  }
  if($exactKManifestPath){
    $frozenExactKManifest=Copy-RequiredInput $exactKManifestPath (Join-Path $inputDir 'exact_k_run_manifest.json') 'exact-K run manifest'
    $frozenExactKSummary=Copy-RequiredInput $exactKSummaryPath (Join-Path $inputDir 'exact_k_summary.json') 'exact-K summary'
  }
  $frozenBaseline=Copy-RequiredInput $baselinePath (Join-Path $solverDir 'simion_candidate_two_zone.json') 'current baseline contract'
  $sourceBuilder=Copy-RequiredInput $sourceBuilderPath (Join-Path $solverDir 'materialize_accelerator_focus_source.py') 'focus source builder'
  $trialBuilder=Copy-RequiredInput $trialBuilderPath (Join-Path $solverDir 'accelerator_focus_voltage_trial.py') 'voltage-trial builder'
  $frozenFocusTheory=Copy-RequiredInput $focusTheoryPath (Join-Path $inputDir 'accelerator_time_focus.py') 'accelerator focus theory'
  $reviewedContract=Join-Path $solverDir 'simion_prototype_contract.json'
  $trialContract=Join-Path $solverDir 'accelerator_focus_voltage_trial.json'
  $trialReceipt=Join-Path $resultDir 'accelerator_focus_voltage_trial_receipt.json'
  $theorySeedReceipt=Join-Path $resultDir 'accelerator_zero_extraction_theory_seed.json'
  $theorySeedCode=@'
import json,sys
import hashlib
from pathlib import Path
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import load_contract
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.accelerator_focus_voltage_trial import derive_zero_extraction_energy_focus_seed
current=load_contract(Path(sys.argv[1]))
reviewed=load_contract(Path(sys.argv[2]),inherited_detector_return_path=current["accelerator"]["detector_return_path"])
_,receipt=derive_zero_extraction_energy_focus_seed(current,reviewed,float(sys.argv[3]))
receipt["source_contract_sha256"]=hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest()
receipt["reviewed_contract_sha256"]=hashlib.sha256(Path(sys.argv[2]).read_bytes()).hexdigest()
Path(sys.argv[4]).write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n",encoding="utf-8")
'@
  $failureStage='derive_zero_extraction_theory_seed';Invoke-ProjectPython -Arguments @('-c',$theorySeedCode,$frozenBaseline,$reviewedContract,$selectedEnergyText,$theorySeedReceipt)
  $theorySeed=Get-Content -LiteralPath $theorySeedReceipt -Raw -Encoding UTF8|ConvertFrom-Json
  $firstGapSelection=if($calibrationRun){'theory_jacobian_from_verified_focus_run'}elseif($null-ne$FirstGapDropV){'explicit_override'}else{'zero_extraction_theory_seed'}
  if($calibrationRun){
    $frozenCalibrationManifest=Copy-RequiredInput $calibrationManifestPath (Join-Path $inputDir 'focus_calibration_run_manifest.json') 'calibration run manifest'
    $frozenCalibrationTrial=Copy-RequiredInput $calibrationTrialPath (Join-Path $inputDir 'focus_calibration_previous_trial.json') 'calibration previous trial'
    $frozenCalibrationAnalysis=Copy-RequiredInput $calibrationAnalysisPath (Join-Path $inputDir 'focus_calibration_previous_analysis.json') 'calibration previous analysis'
    $calibrationCode=@'
import hashlib,json,sys
from pathlib import Path
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import load_contract
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.accelerator_focus_voltage_trial import derive_focus_calibration_proposal
current_path,reviewed_path,previous_path,analysis_path,trial_path,receipt_path,theory_path=map(Path,sys.argv[1:8])
current=load_contract(current_path)
reviewed=load_contract(reviewed_path,inherited_detector_return_path=current["accelerator"]["detector_return_path"])
previous=load_contract(previous_path)
trial,receipt=derive_focus_calibration_proposal(current,reviewed,previous,json.loads(analysis_path.read_text(encoding="utf-8")),selected_net_gain_center_v=float(sys.argv[8]))
trial_path.write_text(json.dumps(trial,indent=2)+"\n",encoding="utf-8")
receipt["input_identity"]={name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in (("current_contract",current_path),("reviewed_contract",reviewed_path),("previous_trial",previous_path),("previous_analysis",analysis_path),("focus_theory",theory_path))}
receipt["trial_contract_sha256"]=hashlib.sha256(trial_path.read_bytes()).hexdigest()
receipt_path.write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n",encoding="utf-8")
'@
    $failureStage='derive_focus_calibration_proposal';Invoke-ProjectPython -Arguments @('-c',$calibrationCode,$frozenBaseline,$reviewedContract,$frozenCalibrationTrial,$frozenCalibrationAnalysis,$trialContract,$trialReceipt,$frozenFocusTheory,$selectedEnergyText)
    $firstGapDrop=[double](Get-Content -LiteralPath $trialReceipt -Raw -Encoding UTF8|ConvertFrom-Json).first_gap_drop_v
  }else{
    $firstGapDrop=if($null-ne$FirstGapDropV){[double]$FirstGapDropV}else{[double]$theorySeed.first_gap_drop_v}
  }
  if(-not([double]::IsFinite($firstGapDrop)) -or $firstGapDrop -le 0){throw 'first-gap voltage drop must be finite and positive'}
  $firstGapDropText=$firstGapDrop.ToString('R',[Globalization.CultureInfo]::InvariantCulture)
  if(-not $calibrationRun){$failureStage='derive_voltage_trial';Invoke-ProjectPython -Arguments @($trialBuilder,'--current',$frozenBaseline,'--reviewed',$reviewedContract,'--first-gap-drop-v',$firstGapDropText,'--selected-net-gain-center-v',$selectedEnergyText,'--finite-3d-gain-correction-v',$gainCorrectionText,'--output',$trialContract,'--receipt',$trialReceipt)}
  # wb:save() rewrites same-basename Workbench companions.  Keep the generated
  # source at a distinct frozen path so the IOB builder can restore it only
  # after saving the seed-derived Workbench.
  $focusFly2Input=Join-Path $inputDir 'accelerator_focus_source.input.fly2'
  $focusFly2=Join-Path $solverDir 'mrtof_three_component_candidate.fly2'
  $sourceReceipt=Join-Path $resultDir 'accelerator_focus_source_receipt.json'
  $failureStage='materialize_axial_source';Invoke-ProjectPython -Arguments @($sourceBuilder,'--contract',$trialContract,'--reviewed-contract',$reviewedContract,'--source-key',$SourceKey,'--output',$focusFly2Input,'--receipt',$sourceReceipt)
  Copy-RequiredInput (Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\simion\mrtof_accelerator_focus.lua') (Join-Path $solverDir 'mrtof_three_component_candidate.lua') 'focus program'|Out-Null
  Copy-RequiredInput (Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\simion\mirror_cycle_counter.lua') (Join-Path $solverDir 'mrtof_three_component_candidate.mirror_cycle_counter.lua') 'cycle counter companion'|Out-Null
  $launcher=Copy-RequiredInput (Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\simion\run_iob_flight.lua') (Join-Path $solverDir 'run_iob_flight.lua') 'flight launcher'
  $analyzer=Copy-RequiredInput (Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\accelerator_focus_simion_analysis.py') (Join-Path $solverDir 'accelerator_focus_simion_analysis.py') 'focus analyzer'
  $composer=Copy-RequiredInput $composerPath (Join-Path $solverDir 'compose_standalone_pa.lua') 'standalone PA composer'
  $iobBuilder=Copy-RequiredInput $iobBuilderPath (Join-Path $solverDir 'build_three_component_iob.lua') 'three-component IOB builder'
  $iobSeed=Copy-RequiredInput $iobSeedPath (Join-Path $solverDir '3_instance_seed.iob') 'three-instance IOB seed'
  foreach($index in 1..3){$name=('iob_seed_placeholder_{0:D2}.pa0'-f$index);Copy-RequiredInput (Join-Path $repoRoot "common\simion\assets\iob_instance_seeds\$name") (Join-Path $solverDir $name) 'IOB seed placeholder'|Out-Null}
  $trialValue=Get-Content -LiteralPath $trialReceipt -Raw -Encoding UTF8|ConvertFrom-Json
  # Local ID 1 is the grounded shield; IDs 2..4 are the endpoint electrodes
  # and IDs 5..9 are the stage-2 rings, matching the canonical GEM namespace.
  $targetVoltages=@(0)+@($trialValue.endpoint_voltages_v)+@($trialValue.ring_voltages_v)
  if($targetVoltages.Count-ne9){throw 'accelerator trial must define exactly nine electrode voltages'}
  $focusOperatingPoint=Join-Path $solverDir 'mrtof_three_component_candidate.operating_point.lua'
  $focusOperatingPointReceipt=Join-Path $resultDir 'focus_operating_point_materialization.json'
  $operatingPointCode=@'
import hashlib,json,sys
from pathlib import Path
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import resolve_trajectory_profile
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.drift_phase_contract import resolve_drift_phase_contract
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_operating_point_variation import apply_overrides,load_operating_point,render_operating_point
base_path,trial_path,output_path,receipt_path,adapter_path,profile_source_path,phase_source_path=map(Path,sys.argv[1:8])
contract=json.loads(profile_source_path.read_text(encoding="utf-8"))
profile=resolve_trajectory_profile(contract,sys.argv[8] or None)
phase=resolve_drift_phase_contract(contract)
point=load_operating_point(base_path,phase_contract={"phase_origin_mirror_side":phase.origin_mirror_side,"return_mirror_side":phase.return_mirror_side,"target_drift_period_ratio":phase.target_period_ratio,"target_half_oscillation_count":phase.target_half_oscillation_count})
trial=json.loads(trial_path.read_text(encoding="utf-8"))
point["accelerator_voltages_v"]=[float(value) for value in trial["endpoint_voltages_v"]]
point["accelerator_ring_voltages_v"]=[float(value) for value in trial["ring_voltages_v"]]
point=apply_overrides(point,{"trajectory_quality":profile["trajectory_quality"],"maximum_step_us":profile["maximum_step_us"]})
base_sha=hashlib.sha256(base_path.read_bytes()).hexdigest()
output_path.write_text(render_operating_point(point,base_sha),encoding="utf-8",newline="\n")
receipt={"schema_version":1,"role":"mrtof_focus_operating_point_materialization","status":"success","base_operating_point_sha256":base_sha,"voltage_trial_receipt_sha256":hashlib.sha256(trial_path.read_bytes()).hexdigest(),"adapter_sha256":hashlib.sha256(adapter_path.read_bytes()).hexdigest(),"phase_contract_source_sha256":hashlib.sha256(phase_source_path.read_bytes()).hexdigest(),"phase_contract":phase.as_dict(),"output_sha256":hashlib.sha256(output_path.read_bytes()).hexdigest(),"accelerator_voltages_v":point["accelerator_voltages_v"],"accelerator_ring_voltages_v":point["accelerator_ring_voltages_v"],"trajectory_profile":{"profile_id":profile["profile_id"],"trajectory_quality":point["trajectory_quality"],"maximum_step_us":point["maximum_step_us"],"purpose":profile["purpose"],"source_contract_sha256":hashlib.sha256(profile_source_path.read_bytes()).hexdigest()},"nonaccelerator_fields":"inherited_unchanged"}
receipt_path.write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n",encoding="utf-8")
'@
  $failureStage='materialize_focus_operating_point';Invoke-ProjectPython -Arguments @('-c',$operatingPointCode,$frozenBaseOperatingPoint,$trialReceipt,$focusOperatingPoint,$focusOperatingPointReceipt,$frozenOperatingPointAdapter,$frozenBaseline,$frozenPhaseContract,$TrajectoryProfileId)
  $failureStage='probe_accelerator_standalone_bank'
  $probeText=Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_standalone_bank','--cache-root',$cacheRoot,'--publication',$familyPublication)
  $familyProbe=$probeText|ConvertFrom-Json -Depth 40
  if($familyProbe.disposition-ne'hit'-or[bool]$familyProbe.native_family_members_opened-or[bool]$familyProbe.complete_native_generation_qualified){throw 'accelerator standalone response bank validation semantics differ'}
  if($declaredPublication.cache_key-ne$familyProbe.cache_key-or[IO.Path]::GetFullPath([string]$declaredPublication.generation_directory)-ne[IO.Path]::GetFullPath([string]$familyProbe.generation_directory)){throw 'accelerator family run and current cache probe identify different generations'}
  $familyProbePath=Join-Path $resultDir 'accelerator_standalone_bank_probe.json';Write-RunJson -Path $familyProbePath -Depth 40 -Value $familyProbe
  $bank=[string]$familyProbe.generation_directory;$responseContract=$familyProbe.standalone_response_contract
  if($responseContract.role-ne'mrtof_accelerator_standalone_response_bank'-or@($responseContract.responses).Count-ne9){throw 'accelerator standalone response contract is incomplete'}
  $familyCacheManifest=Join-Path $bank 'cache_manifest.json'
  if(-not(Test-Path -LiteralPath $familyCacheManifest -PathType Leaf)){throw 'accelerator standalone response bank lacks its cache manifest'}
  $frozenFamilyCacheManifest=Copy-RequiredInput $familyCacheManifest (Join-Path $inputDir 'accelerator_family_cache_manifest.json') 'accelerator family cache manifest'
  $baseSource=Join-Path $bank ([string]$responseContract.base_filename)
  $compositionResponses=@();$compositionArguments=@();$responseIds=@()
  foreach($response in @($responseContract.responses)){
    $id=[int]$response.electrode_id;$normalizationPath=Join-Path $bank ([string]$response.normalization_receipt_filename)
    $rows=@(Import-Csv -LiteralPath $normalizationPath)
    if($rows.Count-ne1){throw "accelerator response $id must have one normalization row"}
    $columns=@($rows[0].PSObject.Properties.Name)
    $expectedColumns=@('basis_voltage_V','minimum_physical_voltage_V','maximum_physical_voltage_V','nonzero_physical_nodes')
    if(Compare-Object -ReferenceObject $expectedColumns -DifferenceObject $columns){throw "accelerator response $id normalization columns differ from the common receipt"}
    $basis=[double]$rows[0].basis_voltage_V
    if(-not ([double]::IsFinite($basis)) -or $basis-eq0){throw "accelerator response $id has invalid basis normalization"}
    $responseSource=Join-Path $bank ([string]$response.standalone_response_filename)
    if([IO.Path]::GetExtension($responseSource)-ine'.pa'-or-not(Test-Path -LiteralPath $responseSource -PathType Leaf)){throw "accelerator response $id is not a direct standalone PA"}
    $responseIds+=$id
    $compositionResponses+=,[ordered]@{coordinate="accelerator_electrode_$id";path=$responseSource;basis_normalization_v=$basis;applied_voltage_delta_v=[double]$targetVoltages[$id-1]}
  }
  if((Compare-Object -ReferenceObject @(1..9) -DifferenceObject @($responseIds|Sort-Object -Unique))){throw 'accelerator response bank electrode IDs must be exactly 1 through 9'}
  $compositionSpec=Join-Path $resultDir 'accelerator_operating_pa_composition_spec.json'
  Write-RunJson -Path $compositionSpec -Depth 20 -Value ([ordered]@{output_name='iob_input_accelerator.pa';base_pa=$baseSource;responses=$compositionResponses;target_voltage_vector_v=$targetVoltages})
  $operatingIdentity=Join-Path $resultDir 'accelerator_operating_pa_cache_identity.json'
  $operatingCacheCode=@'
import json,sys
from pathlib import Path
from common.simion.operating_pa_cache import operating_pa_member_identity,linear_basis_operating_pa_group_identity,probe_operating_pa_cache
s=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
m=operating_pa_member_identity(s["output_name"],s["base_pa"],s["responses"],s["target_voltage_vector_v"])
i=linear_basis_operating_pa_group_identity([m],pa_format_version=2020,implementation_path=sys.argv[4])
Path(sys.argv[2]).write_text(json.dumps(i,indent=2,sort_keys=True)+"\n",encoding="utf-8")
p=probe_operating_pa_cache(sys.argv[3],i)
print(json.dumps({"disposition":p.disposition.value,"cache_key":p.cache_key,"generation_directory":str(p.generation_directory) if p.generation_directory else None,"detail":p.detail},sort_keys=True))
'@
  $operatingProbe=(@(Invoke-ProjectPython -Arguments @('-c',$operatingCacheCode,$compositionSpec,$operatingIdentity,$cacheRoot,$composer))-join"`n")|ConvertFrom-Json
  if($operatingProbe.disposition-eq'corrupt'){throw "accelerator operating PA cache is corrupt: $($operatingProbe.detail)"}
  $operatingBuildDir=Join-Path ([IO.Path]::GetTempPath()) ('simion_operating_pa_'+[guid]::NewGuid().ToString('N'));New-Item -ItemType Directory -Path $operatingBuildDir|Out-Null
  $temporaryAccelerator=Join-Path $operatingBuildDir 'iob_input_accelerator.pa'
  $acceleratorPa=Join-Path $solverDir 'iob_input_accelerator.pa'
  if($operatingProbe.disposition-eq'hit'){
    $materializeCode=@'
import json,sys
from pathlib import Path
from common.simion.operating_pa_cache import materialize_operating_pa_cache
identity=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
result=materialize_operating_pa_cache(sys.argv[2],sys.argv[3],expected_identity=identity)
print(json.dumps({"destination_directory":str(result.destination_directory),"files":[str(path) for path in result.files]}))
'@
    $materialized=(@(Invoke-ProjectPython -Arguments @('-c',$materializeCode,$operatingIdentity,[string]$operatingProbe.generation_directory,$operatingBuildDir))-join"`n")|ConvertFrom-Json
    Copy-RequiredInput $temporaryAccelerator $acceleratorPa 'cached standalone accelerator PA'|Out-Null
  }else{
    $basisLinkDir=Join-Path ([IO.Path]::GetTempPath()) ('simion_pa_links_'+[guid]::NewGuid().ToString('N'));New-Item -ItemType Directory -Path $basisLinkDir|Out-Null
    $privateBase=New-ShortPaCopy -Source $baseSource -Destination (Join-Path $basisLinkDir 'base.pa')
    $compositionArguments=@('--nogui','--noprompt','lua',$composer,$privateBase,$temporaryAccelerator)
    foreach($response in $compositionResponses){$privateResponse=New-ShortPaCopy -Source $response.path -Destination (Join-Path $basisLinkDir ((Split-Path $response.path -Leaf)));$coefficient=[double]$response.applied_voltage_delta_v/[double]$response.basis_normalization_v;$compositionArguments+=("{0},{1}"-f$privateResponse,(Format-InvariantNumber $coefficient))}
    $failureStage='compose_accelerator_standalone_without_refine';Invoke-SimionStage -Stage 'compose_accelerator_standalone_without_refine' -Arguments $compositionArguments
    Remove-ShortPaCopyDirectory -Path $basisLinkDir;$basisLinkDir=$null
    Copy-RequiredInput $temporaryAccelerator $acceleratorPa 'new standalone accelerator PA'|Out-Null
    $publishCode=@'
import json,sys
from pathlib import Path
from common.simion.operating_pa_cache import publish_operating_pa_cache
identity=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
publication=publish_operating_pa_cache(sys.argv[2],identity,sys.argv[3])
print(json.dumps({"disposition":publication.disposition.value,"cache_key":publication.cache_key,"generation_directory":str(publication.generation_directory),"generation_sha256":publication.generation_sha256}))
'@
    $operatingProbe=(@(Invoke-ProjectPython -Arguments @('-c',$publishCode,$operatingIdentity,$cacheRoot,$operatingBuildDir))-join"`n")|ConvertFrom-Json
  }
  Remove-PrivatePaFamilyDirectory -Path $operatingBuildDir -ExpectedNamePrefix 'simion_operating_pa_';$operatingBuildDir=$null
  $operatingCacheReceipt=Join-Path $resultDir 'accelerator_operating_pa_cache_result.json';Write-RunJson -Path $operatingCacheReceipt -Depth 20 -Value $operatingProbe
  $localAnalyzer=Copy-RequiredInput $sourceAnalyzer (Join-Path $solverDir 'iob_input_analyzer.pa') 'standalone analyzer PA'
  $localDetector=Copy-RequiredInput $sourceDetector (Join-Path $solverDir 'iob_input_detector.pa') 'standalone detector PA'
  $posePath=Join-Path $resultDir 'resolved_iob_pose.json'
  $poseCode="import json,sys; from pathlib import Path; from projects.parallel_mirror_dual_stripe_mr_tof.analysis.split_candidate_geometry import resolve_split_iob_origins; p=Path(sys.argv[1]); Path(sys.argv[2]).write_text(json.dumps({'origins_mm':resolve_split_iob_origins(p)},indent=2)+'\n',encoding='utf-8')"
  Invoke-ProjectPython -Arguments @('-c',$poseCode,$frozenBaseline,$posePath);$pose=Get-Content -LiteralPath $posePath -Raw|ConvertFrom-Json
  $origins=@();foreach($name in @('analyzer','accelerator','detector')){foreach($value in @($pose.origins_mm.$name)){$origins+=Format-InvariantNumber ([double]$value)}}
  $operatingIob=Join-Path $solverDir 'mrtof_three_component_candidate.iob'
  $failureStage='build_read_only_standalone_iob';Invoke-SimionStage -Stage 'build_read_only_standalone_iob' -Arguments (@('--nogui','--noprompt','lua',$iobBuilder,'--',$iobSeed,$localAnalyzer,$acceleratorPa,$localDetector,$operatingIob,(Join-Path $solverDir 'mrtof_three_component_candidate.lua'),$focusFly2Input)+$origins+@('read_only_voltageized'))
  if(-not(Test-Path -LiteralPath $operatingIob -PathType Leaf)){throw 'standalone accelerator focus IOB was not created'}
  if(-not(Test-RunFilesIdentical -Left $focusFly2Input -Right $focusFly2)){throw 'IOB companion Fly2 differs from the frozen accelerator focus source'}
  $config=Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $sourceIdentity=Get-Content -LiteralPath $sourceReceipt -Raw -Encoding UTF8|ConvertFrom-Json
  if((Get-FileHash -LiteralPath $focusFly2 -Algorithm SHA256).Hash-ne[string]$sourceIdentity.fly2_sha256){throw 'IOB companion Fly2 differs from the source receipt identity'}
  $config.inputs=[ordered]@{
    operating_iob=ConvertTo-ArtifactRunPath $operatingIob
    standalone_analyzer_pa=ConvertTo-ArtifactRunPath $localAnalyzer
    standalone_accelerator_pa=ConvertTo-ArtifactRunPath $acceleratorPa
    standalone_detector_pa=ConvertTo-ArtifactRunPath $localDetector
    accelerator_family_run_manifest=ConvertTo-ArtifactRunPath $frozenFamilyManifest
    accelerator_family_publication=ConvertTo-ArtifactRunPath $frozenFamilyPublication
    accelerator_family_contract=ConvertTo-ArtifactRunPath $frozenFamilyContract
    accelerator_family_probe=ConvertTo-ArtifactRunPath $familyProbePath
    accelerator_family_cache_manifest=ConvertTo-ArtifactRunPath $frozenFamilyCacheManifest
    standalone_component_run_manifest=ConvertTo-ArtifactRunPath $frozenStandaloneManifest
    standalone_component_run_config=ConvertTo-ArtifactRunPath $frozenStandaloneConfig
    standalone_component_reviewed_geometry=ConvertTo-ArtifactRunPath $frozenStandaloneReviewed
    reviewed_operating_point=ConvertTo-ArtifactRunPath $frozenBaseOperatingPoint
    operating_point_adapter=ConvertTo-ArtifactRunPath $frozenOperatingPointAdapter
    drift_phase_contract=ConvertTo-ArtifactRunPath $frozenPhaseContract
    focus_operating_point_materialization=ConvertTo-ArtifactRunPath $focusOperatingPointReceipt
    accelerator_operating_pa_composition_spec=ConvertTo-ArtifactRunPath $compositionSpec
    accelerator_operating_pa_cache_identity=ConvertTo-ArtifactRunPath $operatingIdentity
    accelerator_operating_pa_cache_result=ConvertTo-ArtifactRunPath $operatingCacheReceipt
    geometry_review_receipt=ConvertTo-ArtifactRunPath (Join-Path $solverDir 'three_component_geometry_review.json')
    iob_structure_report=ConvertTo-ArtifactRunPath (Join-Path $solverDir 'iob_structure_report.txt')
    geometry_source_manifest=ConvertTo-ArtifactRunPath (Join-Path $solverDir 'prototype_input_manifest.json')
    focus_program=ConvertTo-ArtifactRunPath (Join-Path $solverDir 'mrtof_three_component_candidate.lua')
    operating_point=ConvertTo-ArtifactRunPath $focusOperatingPoint
    voltage_map=ConvertTo-ArtifactRunPath (Join-Path $solverDir 'mrtof_three_component_candidate.voltage_map.lua')
    frozen_source_fly2=ConvertTo-ArtifactRunPath $focusFly2Input
    consumed_fly2=ConvertTo-ArtifactRunPath $focusFly2
    baseline_contract=ConvertTo-ArtifactRunPath $frozenBaseline
    trial_contract=ConvertTo-ArtifactRunPath $trialContract
    reviewed_contract=ConvertTo-ArtifactRunPath $reviewedContract
    theory_seed_receipt=ConvertTo-ArtifactRunPath $theorySeedReceipt
    trial_receipt=ConvertTo-ArtifactRunPath $trialReceipt
    source_receipt=ConvertTo-ArtifactRunPath $sourceReceipt
    resolved_iob_pose=ConvertTo-ArtifactRunPath $posePath
  }
  $focusOperatingPointIdentity=Get-Content -LiteralPath $focusOperatingPointReceipt -Raw -Encoding UTF8|ConvertFrom-Json
  $config.inputs.focus_theory=ConvertTo-ArtifactRunPath $frozenFocusTheory
  $config.inputs.voltage_trial_builder=ConvertTo-ArtifactRunPath $trialBuilder
  if($calibrationRun){
    if($sourceIdentity.fly2_sha256-ne$calibrationSourceSha){throw 'focus calibration must retain the previous frozen particle source'}
    $config.inputs.focus_calibration_manifest=ConvertTo-ArtifactRunPath $frozenCalibrationManifest
    $config.inputs.focus_calibration_trial=ConvertTo-ArtifactRunPath $frozenCalibrationTrial
    $config.inputs.focus_calibration_analysis=ConvertTo-ArtifactRunPath $frozenCalibrationAnalysis
  }
  if($energyCalibrationRun){
    $config.inputs.energy_calibration_manifest=ConvertTo-ArtifactRunPath $frozenEnergyCalibrationManifest
    $config.inputs.energy_calibration_proposal=ConvertTo-ArtifactRunPath $frozenEnergyCalibrationProposal
  }
  if($exactKManifestPath){
    $config.inputs.exact_k_run_manifest=ConvertTo-ArtifactRunPath $frozenExactKManifest
    $config.inputs.exact_k_summary=ConvertTo-ArtifactRunPath $frozenExactKSummary
  }
  $config.parameters.source_key=$SourceKey;$config.parameters.particle_count=$expectedCount;$config.parameters.source_sha256=$sourceIdentity.fly2_sha256;$config.parameters.first_gap_drop_v=$firstGapDrop;$config.parameters.first_gap_drop_selection=$firstGapSelection;$config.parameters.selected_net_gain_center_v=[double]$SelectedNetGainCenterV;$config.parameters.selected_net_gain_center_source=$selectedEnergySource;$config.parameters.finite_3d_gain_correction_v=$Finite3dGainCorrectionV
  $config.parameters.finite_3d_gain_correction_selection=if($energyCalibrationRun){'verified_accelerator_exit_energy_calibration_proposal'}else{'explicit_or_zero'}
  $config.parameters.trajectory_profile_id=[string]$focusOperatingPointIdentity.trajectory_profile.profile_id
  $config.parameters.trajectory_quality=[double]$focusOperatingPointIdentity.trajectory_profile.trajectory_quality
  $config.parameters.maximum_step_us=[double]$focusOperatingPointIdentity.trajectory_profile.maximum_step_us
  $config.parameters.trajectory_profile_purpose=[string]$focusOperatingPointIdentity.trajectory_profile.purpose
  $config.parameters.trajectory_profile_source_contract_sha256=[string]$focusOperatingPointIdentity.trajectory_profile.source_contract_sha256
  Write-RunJson -Path $runConfig -Value $config
  $failureStage='native_accelerator_focus'
  $lease=Update-HostResourceStage -Lease $lease -Stage flight `
    -Budget (Get-HostResourceBudget -Role SIMION -Stage flight) -RetainedMemoryBytes 0
  Push-Location -LiteralPath $solverDir
  try{& $simion '--nogui' '--noprompt' 'lua' $launcher $operatingIob 2>&1|Tee-Object -FilePath (Join-Path $logDir 'native_accelerator_focus.log');if($LASTEXITCODE -ne 0){throw 'SIMION accelerator focus flight failed'}}finally{Pop-Location}
  $lease=Update-HostResourceStage -Lease $lease -Stage postprocess `
    -Budget (Get-HostResourceBudget -Role SIMION -Stage postprocess) -RetainedMemoryBytes 0
  $rawLog=Join-Path $logDir 'native_accelerator_focus.log';$analysis=Join-Path $resultDir 'accelerator_focus_analysis.json'
  $failureStage='focus_analysis';Invoke-ProjectPython -Arguments @($analyzer,$rawLog,$trialContract,$analysis,'--expected-count',"$expectedCount",'--reviewed-contract',$reviewedContract)
  $analysisValue=Get-Content -LiteralPath $analysis -Raw -Encoding UTF8|ConvertFrom-Json
  Write-RunJson -Path $summary -Value ([ordered]@{schema_version=1;role='mrtof_two_zone_accelerator_first_time_focus';status='success';qualification='candidate_prototype_numeric_focus_only';particle_count=$expectedCount;focus_particle_count=$analysisValue.focus_particle_count;selected_net_gain_center_v=[double]$SelectedNetGainCenterV;selected_net_gain_center_source=$selectedEnergySource;finite_3d_gain_correction_v=$Finite3dGainCorrectionV;finite_3d_gain_correction_selection=if($energyCalibrationRun){'verified_accelerator_exit_energy_calibration_proposal'}else{'explicit_or_zero'};first_gap_drop_v=$firstGapDrop;first_gap_drop_selection=$firstGapSelection;analytic_trial_focus_plane_residual_z_mm=$analysisValue.analytic_trial_focus_plane_residual_z_mm;timing=$analysisValue.timing})
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $failureStage='capacity_terminal';$maximum=[int64](Get-ChildItem -LiteralPath $package.artifact_run_dir -Recurse -File|Measure-Object Length -Sum).Sum
  $terminalProtected=@($package.artifact_run_dir,$geometryRun);[int64]$publishedOperatingCacheBytes=0
  if($operatingProbe.disposition-eq'published'){
    $publishedGeneration=(Resolve-Path -LiteralPath ([string]$operatingProbe.generation_directory)).Path
    $publishedManifest=Get-Content -LiteralPath (Join-Path $publishedGeneration 'cache_manifest.json') -Raw -Encoding UTF8|ConvertFrom-Json -Depth 40
    if($publishedManifest.cache_key-ne$operatingProbe.cache_key-or$publishedManifest.generation_sha256-ne$operatingProbe.generation_sha256){throw 'published accelerator operating cache differs from its publication receipt'}
    $publishedOperatingCacheBytes=[int64](Get-ChildItem -LiteralPath $publishedGeneration -Recurse -File|Measure-Object Length -Sum).Sum
    $maximum+=$publishedOperatingCacheBytes;$terminalProtected+=$publishedGeneration
  }
  $terminal=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -ProtectedPaths $terminalProtected -KnownMeasuredBytes ([int64]$startup.measured_after_bytes) -MaximumNewArtifactBytes $maximum
  $terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json';Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  $manifestOutputs=@($summary,$rawLog,$analysis,$theorySeedReceipt,$trialReceipt,$focusOperatingPointReceipt,$sourceReceipt,$familyProbePath,$compositionSpec,$operatingIdentity,$operatingCacheReceipt,$posePath,$operatingIob,(Join-Path $solverDir 'mrtof_three_component_candidate.lua'),$focusOperatingPoint,(Join-Path $solverDir 'mrtof_three_component_candidate.voltage_map.lua'),$focusFly2,$acceleratorPa,$localAnalyzer,$localDetector,$startupPath,$terminalPath,$retention)|ForEach-Object{ConvertTo-ArtifactRunPath $_}
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig (ConvertTo-ArtifactRunPath $runConfig) -Status success -Software @('SIMION 2020','Python 3.11') -Outputs $manifestOutputs
  $terminalized=$true;$hostExecutionOutcome='success';Write-Host "MRTOF_ACCELERATOR_FOCUS_FLIGHT=PASS RUN_ID=$RunId"
}catch{
  if(-not $terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_two_zone_accelerator_first_time_focus' -Reason $_.Exception.Message -Software @('SIMION 2020','Python 3.11') -Status failed -FailureStage $failureStage;$terminalized=$true}
  throw
}finally{
  if($null-ne$basisLinkDir -and(Test-Path -LiteralPath $basisLinkDir -PathType Container)){Remove-ShortPaCopyDirectory -Path $basisLinkDir}
  if($null-ne$operatingBuildDir -and(Test-Path -LiteralPath $operatingBuildDir -PathType Container)){Remove-PrivatePaFamilyDirectory -Path $operatingBuildDir -ExpectedNamePrefix 'simion_operating_pa_'}
  if(-not $terminalized -and(Test-Path -LiteralPath $runConfig -PathType Leaf)){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_two_zone_accelerator_first_time_focus' -Reason 'Runner stopped before terminal evidence publication.' -Software @('SIMION 2020','Python 3.11') -Status interrupted -FailureStage $failureStage;$hostExecutionOutcome='interrupted'}
  if($null -ne $lease){Exit-HostExecutionLease -Lease $lease -Outcome $hostExecutionOutcome -RunId $RunId}
  Remove-RunPackageExecutionAlias -Package $package
}
