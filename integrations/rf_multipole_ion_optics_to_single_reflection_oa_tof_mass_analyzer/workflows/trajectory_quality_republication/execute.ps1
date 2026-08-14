[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$RunId,
  [string]$WorkspaceRoot=(Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)))))
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

$repoRoot=Join-Path $WorkspaceRoot 'simulation_repo'
$python=Join-Path $repoRoot '.venv\Scripts\python.exe'
$project='rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer'
$mode='trajectory_quality_manifest_bound_paired_republication'
$artifactRoot=Join-Path $WorkspaceRoot "artifacts\projects\$project"
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')

function Assert-SuccessManifestBinding {
  param([string]$ManifestPath,[string[]]$BoundPaths)
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $ManifestPath --require-status success
  if($LASTEXITCODE-ne 0){throw "Parent manifest verification failed: $ManifestPath"}
  $manifest=Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $records=@($manifest.inputs.Values)+@($manifest.outputs)
  foreach($path in $BoundPaths){
    $full=[IO.Path]::GetFullPath($path)
    $matches=@($records|Where-Object{[IO.Path]::GetFullPath([string]$_.path)-eq$full})
    if($matches.Count-ne 1){throw "Parent manifest does not bind exactly once: $full"}
    $record=$matches[0]
    if(-not[bool]$record.exists-or[int64]$record.bytes-ne(Get-Item -LiteralPath $full).Length-or
       [string]$record.sha256-cne(Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash){
      throw "Parent manifest identity differs: $full"
    }
  }
}

$q8Canonical=Join-Path $WorkspaceRoot 'artifacts\projects\rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer\runs\20260814_155700__analysis__cross__rr-canonical-clock-republish-n1000'
$q8Original=Join-Path $WorkspaceRoot 'artifacts\projects\rf_octupole_ion_optics\runs\20260813_170000__sim__simion__rf-oatof-single-flight-gap0__n1000__r03'
$q108=Join-Path $WorkspaceRoot 'artifacts\projects\rf_octupole_ion_optics\runs\20260814_010000__sim__simion__rf-oatof-single-flight-gap0__n100__r01'
$paths=[ordered]@{
  q8_canonical_manifest=Join-Path $q8Canonical 'run_manifest.json'
  q8_checkpoints=Join-Path $q8Canonical 'results\rr_canonical_clock\rr_canonical_checkpoints.csv'
  q8_clock_receipt=Join-Path $q8Canonical 'results\rr_canonical_clock\rr_canonical_clock_receipt.json'
  q8_original_manifest=Join-Path $q8Original 'run_manifest.json'
  q8_reanalysis_summary=Join-Path $q8Original 'results\manifest_bound_spatial_reanalysis_summary.json'
  q108_manifest=Join-Path $q108 'run_manifest.json'
  q108_checkpoints=Join-Path $q108 'results\single_flight_particle_checkpoints.csv'
  sample_receipt=Join-Path $repoRoot 'integrations\rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer\config\diagnostics\short_focus_rr_tqual_n100_sample_receipt.json'
  q108_configuration=Join-Path $q108 'inputs\simion_single_flight.json'
  q108_program_build=Join-Path $q108 'inputs\single_flight_program_build.json'
  q108_stdout=Join-Path $q108 'logs\simion__batch01.stdout.log'
  q108_geometry=Join-Path $q108 'inputs\oatof_resolved_geometry.json'
}
foreach($path in $paths.Values){if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Required input is missing: $path"}}
Assert-SuccessManifestBinding -ManifestPath $paths.q8_canonical_manifest -BoundPaths @($paths.q8_checkpoints,$paths.q8_clock_receipt)
Assert-SuccessManifestBinding -ManifestPath $paths.q108_manifest -BoundPaths @($paths.q108_checkpoints)

$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunId $RunId -Project $project -Mode $mode -Software @('Python 3.11') `
  -RetentionContractEnabled -RetentionClass compact
$resultDir=Join-Path $package.result_dir 'trajectory_quality_pair'
& $python -m integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.analyze_trajectory_quality_pair `
  --q8-checkpoints $paths.q8_checkpoints --q108-checkpoints $paths.q108_checkpoints `
  --q8-manifest $paths.q8_original_manifest --q8-reanalysis-summary $paths.q8_reanalysis_summary `
  --q108-manifest $paths.q108_manifest --sample-receipt $paths.sample_receipt `
  --q108-configuration $paths.q108_configuration --q108-program-build $paths.q108_program_build `
  --q108-stdout $paths.q108_stdout --q108-geometry $paths.q108_geometry `
  --output $resultDir --no-derived-manifest
if($LASTEXITCODE-ne 0){throw 'Trajectory-quality paired analyzer failed.'}

$config=[ordered]@{
  schema_version=2;run_id=$RunId;project=$project;mode=$mode;project_root=$repoRoot
  inputs=$paths
  parameters=[ordered]@{paired_particle_count=100;source_authority='canonical q8 clock republish plus successful q108 solver run';lifecycle_stage='completed'}
  formal_gate_passed=$false
  artifact_retention=[ordered]@{policy_version=1;class='compact';reason=$null}
}
Write-RunJson -Path $package.run_config -Value $config -Depth 8
$resultPath=Join-Path $resultDir 'trajectory_quality_paired_check.json'
$result=Get-Content -LiteralPath $resultPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
$summary=[ordered]@{
  schema_version=1;role='trajectory_quality_manifest_bound_paired_republication_summary';status='success';run_id=$RunId
  paired_particle_count=[int]$result.paired_particle_count
  focus_decision=$result.focus_decision
  result_path=$resultPath
  formal_eligible=$false
  claim_limit=[string]$result.claim_limit
}
Write-RunJson -Path $package.summary -Value $summary -Depth 8
$outputs=@(
  $package.summary,
  $resultPath,
  (Join-Path $resultDir 'checkpoint_paired_statistics.csv'),
  (Join-Path $resultDir 'checkpoint_arm_statistics.csv'),
  (Join-Path $resultDir 'trajectory_quality_paired_check.png')
)
Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config `
  -Status success -Software @('Python 3.11') -Outputs $outputs
Write-Output "TRAJECTORY_QUALITY_REPUBLICATION=PASS RUN_DIR=$($package.run_dir)"
