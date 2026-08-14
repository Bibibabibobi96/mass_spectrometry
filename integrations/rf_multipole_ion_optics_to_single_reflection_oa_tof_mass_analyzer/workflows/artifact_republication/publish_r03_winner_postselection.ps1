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
$mode='manifest_bound_r03_winner_postselection_republication'
$artifactRoot=Join-Path $WorkspaceRoot "artifacts\projects\$project"
$sourceDir=Join-Path $artifactRoot 'scratch\r03-winner-post-selection'
$q8Run=Join-Path $WorkspaceRoot 'artifacts\projects\rf_octupole_ion_optics\runs\20260813_170000__sim__simion__rf-oatof-single-flight-gap0__n1000__r03'
$q8Manifest=Join-Path $q8Run 'run_manifest.json'
$q8ReanalysisSummary=Join-Path $q8Run 'results\manifest_bound_spatial_reanalysis_summary.json'
$q8ReanalysisCheckpoints=Join-Path $q8Run 'results\manifest_bound_spatial_reanalysis_checkpoints.csv'
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')

& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $q8Manifest --require-status failed
if($LASTEXITCODE-ne 0){throw 'Original q8 failed manifest verification failed.'}
$sourceManifestSha=(Get-FileHash -LiteralPath $q8Manifest -Algorithm SHA256).Hash
$reanalysis=Get-Content -LiteralPath $q8ReanalysisSummary -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
if([string]$reanalysis.status-ne'success'-or
   [string]$reanalysis.reanalysis_provenance.source_run_manifest.sha256-cne$sourceManifestSha){
  throw 'Successful reanalysis provenance does not bind the original q8 manifest.'
}

$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunId $RunId -Project $project -Mode $mode -Software @('Python 3.11','PowerShell 7') `
  -RetentionContractEnabled -RetentionClass compact
$resultDir=Join-Path $package.result_dir 'winner_postselection'
New-Item -ItemType Directory -Path $resultDir|Out-Null
$names=@('checkpoints.csv','summary.json','winner_detector_peak_metadata.json','winner_detector_peak.png')
$outputs=@()
foreach($name in $names){
  $destination=Join-Path $resultDir $name
  $outputs+=Copy-VerifiedRunInput -Source (Join-Path $sourceDir $name) -Destination $destination
}
$scientificSummary=Get-Content -LiteralPath (Join-Path $resultDir 'summary.json') -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
if([string]$scientificSummary.status-ne'success'-or
   [string]$scientificSummary.reanalysis_provenance.source_run_manifest.sha256-cne$sourceManifestSha){
  throw 'Winner post-selection summary does not bind the original q8 manifest.'
}
$config=[ordered]@{
  schema_version=2;run_id=$RunId;project=$project;mode=$mode;project_root=$repoRoot
  inputs=[ordered]@{q8_source_manifest=$q8Manifest;q8_successful_reanalysis_summary=$q8ReanalysisSummary;q8_successful_reanalysis_checkpoints=$q8ReanalysisCheckpoints}
  parameters=[ordered]@{migration='byte-preserving scratch-to-standard-run-package';particle_count=1000;lifecycle_stage='completed'}
  formal_gate_passed=$false
  artifact_retention=[ordered]@{policy_version=1;class='compact';reason=$null}
}
Write-RunJson -Path $package.run_config -Value $config -Depth 8
$identities=@($outputs|ForEach-Object{[ordered]@{name=[IO.Path]::GetFileName($_);bytes=(Get-Item -LiteralPath $_).Length;sha256=(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash}})
Write-RunJson -Path $package.summary -Depth 8 -Value ([ordered]@{
  schema_version=1;role='manifest_bound_r03_winner_postselection_republication_summary';status='success';run_id=$RunId
  source_run_id='20260813_170000__sim__simion__rf-oatof-single-flight-gap0__n1000__r03'
  source_manifest_status='failed';successful_reanalysis_status='success';particle_count=1000
  migrated_outputs=$identities;byte_identity_verified=$true;scientific_equivalence='exact byte identity'
  formal_eligible=$false;claim_limit='Detector-blind spatial reanalysis/post-selection evidence only; source solver run terminal status remains failed.'
})
$outputs=@($package.summary)+$outputs
Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config `
  -Status success -Software @('Python 3.11','PowerShell 7') -Outputs $outputs
Write-Output "R03_WINNER_REPUBLICATION=PASS RUN_DIR=$($package.run_dir)"
