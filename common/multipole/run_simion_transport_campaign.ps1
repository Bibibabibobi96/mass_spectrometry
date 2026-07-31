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

$repo = [IO.Path]::GetFullPath($RepoRoot)
$campaignRoot = [IO.Path]::GetFullPath(
  (Join-Path $repo 'common\multipole\campaigns')
)
$candidate = if ([IO.Path]::IsPathRooted($CampaignPath)) {
  [IO.Path]::GetFullPath($CampaignPath)
} else {
  [IO.Path]::GetFullPath((Join-Path $campaignRoot $CampaignPath))
}
$relative = [IO.Path]::GetRelativePath($campaignRoot, $candidate)
if (
  $relative -eq '..' -or
  $relative.StartsWith(('..' + [IO.Path]::DirectorySeparatorChar))
) {
  throw 'CampaignPath must remain under common\multipole\campaigns.'
}
if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
  throw "Campaign file is missing: $candidate"
}

$campaign = Get-Content -LiteralPath $candidate -Raw -Encoding UTF8 |
  ConvertFrom-Json
if (
  [int]$campaign.schema_version -notin @(1, 2) -or
  [string]$campaign.role -ne 'multipole_transport_experiment_campaign'
) {
  throw 'Campaign identity differs.'
}
if ($PSCmdlet.ParameterSetName -eq 'Status') {
  $python = if ($PythonExe) {
    [IO.Path]::GetFullPath($PythonExe)
  } else {
    Join-Path $repo '.venv\Scripts\python.exe'
  }
  & $python -m common.multipole.campaign_status --repo-root $repo `
    --campaign $candidate
  if ($LASTEXITCODE -ne 0) {
    throw 'Campaign status verification failed.'
  }
  return
}
$selected = if ($PSCmdlet.ParameterSetName -eq 'All') {
  @($campaign.experiments)
} else {
  @($campaign.experiments | Where-Object {
      [string]$_.experiment_id -eq $ExperimentId
    })
}
if ($selected.Count -eq 0) {
  throw "Campaign experiment is missing: $ExperimentId"
}
if ($PSCmdlet.ParameterSetName -eq 'One' -and $selected.Count -ne 1) {
  throw "Campaign experiment identity is not unique: $ExperimentId"
}

$python = if ($PythonExe) {
  [IO.Path]::GetFullPath($PythonExe)
} else {
  Join-Path $repo '.venv\Scripts\python.exe'
}
$resolved = @()
try {
  foreach ($experiment in $selected) {
    $snapshot = Join-Path ([IO.Path]::GetTempPath()) (
      'multipole_campaign_preflight_{0}.json' -f [guid]::NewGuid()
    )
    & $python -m common.multipole.runtime_profile --repo-root $repo `
      --project-id ([string]$experiment.project_id) `
      --campaign-path $candidate `
      --experiment-id ([string]$experiment.experiment_id) `
      --output $snapshot
    if ($LASTEXITCODE -ne 0) {
      throw "Campaign preflight failed: $($experiment.experiment_id)"
    }
    $profile = Get-Content -LiteralPath $snapshot -Raw -Encoding UTF8 |
      ConvertFrom-Json
    $scope = $profile.engineering_budget.inline_contract.pilot_authorization.scope
    if (
      [string]$profile.project_id -ne [string]$experiment.project_id -or
      [string]$profile.runtime_profile_id -ne [string]$experiment.experiment_id -or
      [string]$scope.authorized_run_id -ne [string]$experiment.authorized_run_id
    ) {
      throw "Campaign preflight identity differs: $($experiment.experiment_id)"
    }
    $resolved += [pscustomobject]@{
      experiment = $experiment
      snapshot = $snapshot
    }
  }

  . (Join-Path $repo 'common\multipole\project_transport_launcher_support.ps1')
  foreach ($item in $resolved) {
    $experiment = $item.experiment
    Write-Host (
      'MULTIPOLE_CAMPAIGN=START CAMPAIGN={0} EXPERIMENT={1} RUN={2}' -f
      [string]$campaign.campaign_id,
      [string]$experiment.experiment_id,
      [string]$experiment.authorized_run_id
    )
    $arguments = @{
      Solver = 'simion'
      ProjectId = [string]$experiment.project_id
      CampaignPath = $candidate
      ExperimentId = [string]$experiment.experiment_id
      RepoRoot = $repo
      RunId = [string]$experiment.authorized_run_id
      RetentionClass = [string]$experiment.retention_class
      PythonExe = $python
    }
    if ($SimionExe) {
      $arguments.SimionExe = $SimionExe
    }
    Invoke-MultipoleProjectFinite3dTransport @arguments
    Write-Host (
      'MULTIPOLE_CAMPAIGN=PASS CAMPAIGN={0} EXPERIMENT={1}' -f
      [string]$campaign.campaign_id,
      [string]$experiment.experiment_id
    )
  }
} finally {
  foreach ($item in $resolved) {
    Remove-Item -LiteralPath $item.snapshot -Force -ErrorAction SilentlyContinue
  }
}

Write-Host (
  'MULTIPOLE_CAMPAIGN=COMPLETE CAMPAIGN={0} EXPERIMENTS={1}' -f
  [string]$campaign.campaign_id,
  $resolved.Count
)
