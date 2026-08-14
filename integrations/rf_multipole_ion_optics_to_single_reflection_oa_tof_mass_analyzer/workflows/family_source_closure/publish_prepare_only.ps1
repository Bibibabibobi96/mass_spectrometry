[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$Campaign,
  [Parameter(Mandatory)][string]$ExperimentId,
  [switch]$ResumeInitializedRun,
  [switch]$PublishExistingPrepared,
  [string]$WorkspaceRoot=(Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)))))
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$repoRoot=Join-Path $WorkspaceRoot 'simulation_repo'
$python=Join-Path $repoRoot '.venv\Scripts\python.exe'
$project='rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer'
$mode='family_source_closure_prepare_only'
$campaignPath=[IO.Path]::GetFullPath($(if([IO.Path]::IsPathRooted($Campaign)){$Campaign}else{Join-Path $repoRoot $Campaign}))
$campaignDocument=Get-Content -LiteralPath $campaignPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
$rows=@($campaignDocument.experiments|Where-Object{[string]$_.experiment_id-eq$ExperimentId})
if($rows.Count-ne 1){throw 'Campaign experiment must resolve exactly once.'}
$row=$rows[0];$runId=[string]$row.run_id
$artifactRoot=Join-Path $WorkspaceRoot "artifacts\projects\$project"
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$runDir=Join-Path $artifactRoot "runs\$runId"
if($ResumeInitializedRun){
  if(-not(Test-Path -LiteralPath (Join-Path $runDir 'run_manifest.json') -PathType Leaf)){throw 'Initialized run manifest is missing.'}
  $package=[pscustomobject]@{run_dir=$runDir;input_dir=Join-Path $runDir 'inputs';result_dir=Join-Path $runDir 'results';log_dir=Join-Path $runDir 'logs';run_config=Join-Path $runDir 'run_config.json';summary=Join-Path $runDir 'summary.json'}
}else{
  $package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -RunId $runId -Project $project -Mode $mode -Software @('Python 3.11','PowerShell 7') `
    -RetentionContractEnabled -RetentionClass compact
}
if(-not$PublishExistingPrepared){
  & (Join-Path $PSScriptRoot 'execute.ps1') -Campaign $campaignPath -ExperimentId $ExperimentId `
    -PrepareOnly -OutputDirectory $package.run_dir -PythonExe $python
  if($LASTEXITCODE-ne 0){throw 'Official family source-closure preparation failed.'}
}
$sourceManifest=[IO.Path]::GetFullPath((Join-Path $WorkspaceRoot ([string]$row.source.manifest.path)))
$config=[ordered]@{
  schema_version=2;run_id=$runId;project=$project;mode=$mode;project_root=$repoRoot
  inputs=[ordered]@{campaign=$campaignPath;execution_policy=Join-Path $repoRoot ([string]$campaignDocument.execution_policy.path);source_manifest=$sourceManifest}
  parameters=[ordered]@{campaign_id=[string]$campaignDocument.campaign_id;experiment_id=$ExperimentId;prepare_only=$true;lifecycle_stage='completed'}
  formal_gate_passed=$false
  artifact_retention=[ordered]@{policy_version=1;class='compact';reason=$null}
}
Write-RunJson -Path $package.run_config -Value $config -Depth 8
$materialized=Join-Path $package.input_dir 'single_flight_materialized_particle_source.csv'
$target=Join-Path $package.input_dir 'single_flight_pulse_target_state.csv'
$receipt=Join-Path $package.input_dir 'single_flight_source_materialization_receipt.json'
$summary=[ordered]@{
  schema_version=1;role='family_source_closure_prepare_only_summary';status='success';run_id=$runId
  campaign_id=[string]$campaignDocument.campaign_id;experiment_id=$ExperimentId;particle_count=1000
  materialized_source=[ordered]@{path=$materialized;sha256=(Get-FileHash -LiteralPath $materialized -Algorithm SHA256).Hash}
  pulse_target_state=[ordered]@{path=$target;sha256=(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash}
  materialization_receipt=[ordered]@{path=$receipt;sha256=(Get-FileHash -LiteralPath $receipt -Algorithm SHA256).Hash}
  solver_executed=$false;formal_eligible=$false;claim_limit=[string]$campaignDocument.claim_limit
}
Write-RunJson -Path $package.summary -Value $summary -Depth 8
$outputs=@($package.summary,$materialized,$target,$receipt)+@(
  Get-ChildItem -LiteralPath $package.run_dir -File -Filter '*.json'|
    Where-Object{$_.Name-notin@('run_config.json','run_manifest.json','summary.json')}|
    ForEach-Object{$_.FullName}
)
Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config `
  -Status success -Software @('Python 3.11','PowerShell 7') -Outputs $outputs
Write-Output "FAMILY_SOURCE_PREPARE_PUBLICATION=PASS RUN_DIR=$($package.run_dir)"
