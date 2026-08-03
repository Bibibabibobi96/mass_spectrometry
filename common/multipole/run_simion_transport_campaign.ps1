[CmdletBinding(DefaultParameterSetName = 'One')]
param(
  [Parameter(Mandatory = $true)]
  [string]$CampaignPath,
  [Parameter(Mandatory = $true, ParameterSetName = 'One')]
  [string]$ExperimentId,
  [Parameter(Mandatory = $true, ParameterSetName = 'All')]
  [switch]$All,
  [Parameter(Mandatory = $true, ParameterSetName = 'Status')]
  [switch]$Status,
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')),
  [string]$PythonExe = '',
  [string]$SimionExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-AnalysisPreflight {
  param([string]$Python,[string]$Repository,[string]$Workspace,[string]$Campaign)
  $json=@(& $Python -m common.multipole.campaign_analysis `
    --campaign-preflight $Campaign --repo-root $Repository --workspace-root $Workspace)
  if($LASTEXITCODE-ne 0){throw 'Campaign analysis preflight failed.'}
  return ($json-join "`n")|ConvertFrom-Json
}

function Invoke-AnalysisLifecycle {
  param([object]$Plan,[object]$Preflight,[string]$Repository,[string]$Workspace,[string]$Python)
  if([string]$Plan.status-eq'COMPLETE'){
    Write-Host "MULTIPOLE_CAMPAIGN_ANALYSIS=COMPLETE RUN=$([string]$Plan.analysis_run_id)";return
  }
  if([string]$Plan.status-eq'PENDING'){
    Write-Host "MULTIPOLE_CAMPAIGN_ANALYSIS=PENDING RUN=$([string]$Plan.analysis_run_id)";return
  }
  if([string]$Plan.status-eq'FAILED'){throw "Campaign analysis is failed closed: $($Plan.reason)"}
  if([string]$Plan.status-ne'READY'){throw "Unknown campaign analysis state: $($Plan.status)"}

  . (Join-Path $Repository 'common\contracts\run_artifact_support.ps1')
  $artifactRoot=Join-Path $Workspace "artifacts\projects\$([string]$Plan.project_id)"
  $package=New-RunPackage -Python $Python -RepoRoot $Repository -ArtifactRoot $artifactRoot `
    -RunId ([string]$Plan.analysis_run_id) -Project ([string]$Plan.project_id) `
    -Mode ([string]$Plan.mode) -Software @('Python 3.11') `
    -RetentionContractEnabled -RetentionClass compact
  try{
    $outputs=[ordered]@{}
    foreach($property in $Plan.fixed_output_roles.PSObject.Properties){
      $path=[IO.Path]::GetFullPath((Join-Path $package.run_dir ([string]$property.Value)))
      if(-not$path.StartsWith($package.result_dir+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){
        throw "Analysis output escapes results: $($property.Name)"
      }
      $outputs[$property.Name]=$path
    }
    $inputs=[ordered]@{
      campaign=Copy-VerifiedRunInput -Source ([string]$Preflight.campaign_path) `
        -Destination (Join-Path $package.input_dir 'campaign.json')
      analysis_capability_catalog=Copy-VerifiedRunInput -Source ([string]$Preflight.catalog_path) `
        -Destination (Join-Path $package.input_dir 'analysis_capabilities.json')
    }
    foreach($property in $Plan.consumer.PSObject.Properties){
      $source=Join-Path $Repository (([string]$property.Value-replace'\.','\')+'.py')
      $inputs[$property.Name]=Copy-VerifiedRunInput -Source $source `
        -Destination (Join-Path $package.input_dir ("$($property.Name).py"))
    }
    $analysisArgs=@('-m',[string]$Plan.consumer.analysis_module)
    $plotArgs=@('-m',[string]$Plan.consumer.plot_module)
    for($index=0;$index-lt@($Plan.sources).Count;$index+=1){
      $source=@($Plan.sources)[$index];$number=$index+1;$label=[string]$source.experiment_id
      $manifest=Copy-VerifiedRunInput -Source ([string]$source.run_manifest_path) `
        -Destination (Join-Path $package.input_dir ("source_{0:D3}_run_manifest.json"-f$number))
      $figure=Copy-VerifiedRunInput -Source ([string]$source.figure_manifest_path) `
        -Destination (Join-Path $package.input_dir ("source_{0:D3}_figure_manifest.json"-f$number))
      $state=Copy-VerifiedRunInput -Source ([string]$source.state_path) `
        -Destination (Join-Path $package.input_dir ("source_{0:D3}_state.csv"-f$number))
      if((Get-FileHash -LiteralPath $state -Algorithm SHA256).Hash-cne[string]$source.state_sha256){
        throw "Frozen source state SHA-256 differs: $label"
      }
      $inputs[("source_{0:D3}_run_manifest"-f$number)]=$manifest
      $inputs[("source_{0:D3}_figure_manifest"-f$number)]=$figure
      $inputs[("source_{0:D3}_state"-f$number)]=$state
      $analysisArgs+=@('--series',$label,$manifest)
      $plotArgs+=@('--series',("{0}={1}={2}"-f$label,$state,$source.run_id))
    }
    $analysisArgs+=@('--baseline-label',[string]$Plan.baseline_experiment_id,
      '--output',$outputs.metrics,'--markdown',$outputs.report)
    $plotArgs+=@('--output',$outputs.figure,'--manifest',$outputs.figure_manifest,
      '--title',[string]$Plan.fixed_settings.title,'--purpose',[string]$Plan.fixed_settings.purpose,
      '--bin-count',[string]$Plan.parameters.bin_count,'--dpi',[string]$Plan.parameters.dpi,
      '--repo-root',$Repository)
    $config=Get-Content -LiteralPath $package.run_config -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    $config.inputs=$inputs
    $config.parameters=[ordered]@{lifecycle_stage='analysis';campaign_id=[string]$Preflight.campaign_id;
      capability_id=[string]$Plan.capability_id;baseline_experiment_id=[string]$Plan.baseline_experiment_id;
      experiment_ids=@($Plan.experiment_ids);analysis_parameters=$Plan.parameters;claim_class=[string]$Plan.claim_class}
    $config.provenance=[ordered]@{campaign_sha256=[string]$Preflight.campaign_sha256;
      analysis_capability_catalog_sha256=[string]$Preflight.catalog_sha256}
    Write-RunJson -Path $package.run_config -Depth 12 -Value $config
    Push-Location $Repository
    try{
      & $Python @analysisArgs;if($LASTEXITCODE-ne 0){throw 'Campaign metrics analysis failed.'}
      & $Python @plotArgs;if($LASTEXITCODE-ne 0){throw 'Campaign exit-state comparison plot failed.'}
    }finally{Pop-Location}
    Write-RunJson -Path $package.summary -Depth 8 -Value ([ordered]@{schema_version=1;
      role='multipole_campaign_analysis_summary';status='success';project_id=[string]$Plan.project_id;
      campaign_id=[string]$Preflight.campaign_id;capability_id=[string]$Plan.capability_id;
      claim_class=[string]$Plan.claim_class;source_run_count=@($Plan.sources).Count;
      baseline_experiment_id=[string]$Plan.baseline_experiment_id;formal_gate_passed=$false})
    $retention=Apply-RunArtifactRetention -Python $Python -RepoRoot $Repository -RunConfig $package.run_config
    $frozenOutputs=@($package.summary)+@($outputs.Values)+@($retention)
    Write-VerifiedRunManifest -Python $Python -RepoRoot $Repository -RunConfig $package.run_config `
      -Status success -Software @('Python 3.11') -Outputs $frozenOutputs
    Write-Host "MULTIPOLE_CAMPAIGN_ANALYSIS=COMPLETE RUN=$([string]$Plan.analysis_run_id)"
  }catch{
    Complete-FailedRun -Python $Python -RepoRoot $Repository -RunConfig $package.run_config `
      -Summary $package.summary -SummaryRole 'multipole_campaign_analysis_summary' `
      -Reason $_.Exception.Message -Software @('Python 3.11') -Status failed
    throw
  }
}

$repo = [IO.Path]::GetFullPath($RepoRoot)
$workspace = Split-Path -Parent $repo
$campaignRoot = [IO.Path]::GetFullPath((Join-Path $repo 'common\multipole\campaigns'))
$candidate = if ([IO.Path]::IsPathRooted($CampaignPath)) {
  [IO.Path]::GetFullPath($CampaignPath)
} else {
  [IO.Path]::GetFullPath((Join-Path $campaignRoot $CampaignPath))
}
$relative = [IO.Path]::GetRelativePath($campaignRoot, $candidate)
if ($relative -eq '..' -or $relative.StartsWith(('..' + [IO.Path]::DirectorySeparatorChar))) {
  throw 'CampaignPath must remain under common\multipole\campaigns.'
}
if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
  throw "Campaign file is missing: $candidate"
}

$campaign = Get-Content -LiteralPath $candidate -Raw -Encoding UTF8 | ConvertFrom-Json
if ([int]$campaign.schema_version -notin @(1, 2, 3, 4) -or
  [string]$campaign.role -ne 'multipole_transport_experiment_campaign') {
  throw 'Campaign identity differs.'
}
$python = if ($PythonExe) {[IO.Path]::GetFullPath($PythonExe)} else {Join-Path $repo '.venv\Scripts\python.exe'}
if ($PSCmdlet.ParameterSetName -eq 'Status') {
  & $python -m common.multipole.campaign_status --repo-root $repo --campaign $candidate
  if ($LASTEXITCODE -ne 0) {throw 'Campaign status verification failed.'}
  $preflight=Get-AnalysisPreflight $python $repo $workspace $candidate
  foreach($plan in @($preflight.analyses)){
    $display=if([string]$plan.status-eq'COMPLETE'){'COMPLETE'}elseif([string]$plan.status-eq'FAILED'){'FAILED'}else{'PENDING'}
    Write-Host ('MULTIPOLE_CAMPAIGN_ANALYSIS_STATUS={0} CAPABILITY={1} RUN={2} REASON={3}' -f `
      $display,[string]$plan.capability_id,[string]$plan.analysis_run_id,[string]$plan.reason)
  }
  return
}
$selected = if ($PSCmdlet.ParameterSetName -eq 'All') {@($campaign.experiments)} else {
  @($campaign.experiments | Where-Object {[string]$_.experiment_id -eq $ExperimentId})
}
if ($selected.Count -eq 0) {throw "Campaign experiment is missing: $ExperimentId"}
if ($PSCmdlet.ParameterSetName -eq 'One' -and $selected.Count -ne 1) {
  throw "Campaign experiment identity is not unique: $ExperimentId"
}

$preflight=Get-AnalysisPreflight $python $repo $workspace $candidate
foreach($plan in @($preflight.analyses)){
  if([string]$plan.status-eq'FAILED'){throw "Campaign analysis is failed closed: $($plan.reason)"}
}
$resolved = @()
try {
  foreach ($experiment in $selected) {
    $snapshot = Join-Path ([IO.Path]::GetTempPath()) ('multipole_campaign_preflight_{0}.json' -f [guid]::NewGuid())
    & $python -m common.multipole.runtime_profile --repo-root $repo `
      --project-id ([string]$experiment.project_id) --campaign-path $candidate `
      --experiment-id ([string]$experiment.experiment_id) --output $snapshot
    if ($LASTEXITCODE -ne 0) {throw "Campaign preflight failed: $($experiment.experiment_id)"}
    $profile = Get-Content -LiteralPath $snapshot -Raw -Encoding UTF8 | ConvertFrom-Json
    $scope = $profile.engineering_budget.inline_contract.pilot_authorization.scope
    if ([string]$profile.project_id -ne [string]$experiment.project_id -or
      [string]$profile.runtime_profile_id -ne [string]$experiment.experiment_id -or
      [string]$scope.authorized_run_id -ne [string]$experiment.authorized_run_id) {
      throw "Campaign preflight identity differs: $($experiment.experiment_id)"
    }
    $resolved += [pscustomobject]@{experiment=$experiment;snapshot=$snapshot}
  }

  . (Join-Path $repo 'common\multipole\project_transport_launcher_support.ps1')
  foreach ($item in $resolved) {
    $experiment = $item.experiment
    Write-Host ('MULTIPOLE_CAMPAIGN=START CAMPAIGN={0} EXPERIMENT={1} RUN={2}' -f `
      [string]$campaign.campaign_id,[string]$experiment.experiment_id,[string]$experiment.authorized_run_id)
    $arguments = @{Solver='simion';ProjectId=[string]$experiment.project_id;CampaignPath=$candidate;
      ExperimentId=[string]$experiment.experiment_id;RepoRoot=$repo;RunId=[string]$experiment.authorized_run_id;
      RetentionClass=[string]$experiment.retention_class;PythonExe=$python}
    if ($SimionExe) {$arguments.SimionExe = $SimionExe}
    if ([int]$campaign.schema_version -eq 4) {$arguments.CaseSet = [string]$experiment.case_set}
    Invoke-MultipoleProjectFinite3dTransport @arguments
    Write-Host ('MULTIPOLE_CAMPAIGN=PASS CAMPAIGN={0} EXPERIMENT={1}' -f `
      [string]$campaign.campaign_id,[string]$experiment.experiment_id)
    $preflight=Get-AnalysisPreflight $python $repo $workspace $candidate
    foreach($plan in @($preflight.analyses)){
      Invoke-AnalysisLifecycle $plan $preflight $repo $workspace $python
    }
  }
} finally {
  foreach ($item in $resolved) {Remove-Item -LiteralPath $item.snapshot -Force -ErrorAction SilentlyContinue}
}

Write-Host ('MULTIPOLE_CAMPAIGN=COMPLETE CAMPAIGN={0} EXPERIMENTS={1}' -f `
  [string]$campaign.campaign_id,$resolved.Count)
