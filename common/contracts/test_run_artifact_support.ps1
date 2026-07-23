[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-Equal {
  param(
    [Parameter(Mandatory)][object]$Actual,
    [Parameter(Mandatory)][object]$Expected,
    [Parameter(Mandatory)][string]$Message
  )
  if ($Actual -ne $Expected) {
    throw "$Message Expected='$Expected' Actual='$Actual'"
  }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$projectRoot = Join-Path $repoRoot 'projects\oa_tof'
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ("run_artifact_support_" + [guid]::NewGuid().ToString('N'))

try {
  . (Join-Path $PSScriptRoot 'run_artifact_support.ps1')
  $interruptedDir = Join-Path $testRoot '20260723_170001__test__cross__lifecycle-interrupted__n100'
  New-Item -ItemType Directory -Path $interruptedDir -Force | Out-Null
  Initialize-RunRecord -RunDir $interruptedDir `
    -RunId (Split-Path -Leaf $interruptedDir) -Project 'oa_tof' -Mode 'contract_test' `
    -ProjectRoot $projectRoot -RepoRoot $repoRoot -Python $python `
    -ProvisionalSummaryRole 'oa_tof_provisional_run_summary' `
    -TerminalSummaryRole 'oa_tof_terminal_run_summary'

  $config = Get-Content -LiteralPath (Join-Path $interruptedDir 'run_config.json') `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  $summary = Get-Content -LiteralPath (Join-Path $interruptedDir 'summary.json') `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  $manifest = Get-Content -LiteralPath (Join-Path $interruptedDir 'run_manifest.json') `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  Assert-Equal $config.project_root $projectRoot 'Initialize-RunRecord changed project_root.'
  Assert-Equal $summary.role 'oa_tof_terminal_run_summary' 'Initialization summary role changed.'
  Assert-Equal $summary.status 'interrupted' 'Initialization summary status changed.'
  Assert-Equal $summary.reason 'Run package initialized.' 'Initialization reason changed.'
  Assert-Equal $manifest.status 'interrupted' 'Initialization manifest status changed.'
  Assert-Equal @($manifest.outputs).Count 1 'Initialization manifest must record summary.json.'
  Assert-Equal (Split-Path -Leaf $manifest.outputs[0].path) 'summary.json' `
    'Initialization manifest output path changed.'

  Write-TerminalRunRecord -RunDir $interruptedDir -Status failed `
    -Reason 'synthetic failure' -RepoRoot $repoRoot -Python $python `
    -SummaryRole 'oa_tof_terminal_run_summary'
  $failedSummary = Get-Content -LiteralPath (Join-Path $interruptedDir 'summary.json') `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  $failedManifest = Get-Content -LiteralPath (Join-Path $interruptedDir 'run_manifest.json') `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  Assert-Equal $failedSummary.status 'failed' 'Failed summary status changed.'
  Assert-Equal $failedSummary.reason 'synthetic failure' 'Failed summary reason changed.'
  Assert-Equal $failedManifest.status 'failed' 'Failed manifest status changed.'

  $successDir = Join-Path $testRoot '20260723_170002__test__cross__lifecycle-success__n100'
  New-Item -ItemType Directory -Path $successDir -Force | Out-Null
  $successConfig = Join-Path $successDir 'run_config.json'
  $successSummary = Join-Path $successDir 'summary.json'
  Write-RunJson -Path $successConfig -Value ([ordered]@{
    schema_version=1;run_id=(Split-Path -Leaf $successDir);project='oa_tof'
    mode='contract_test';project_root=$projectRoot;inputs=[ordered]@{}
  })
  Write-RunJson -Path $successSummary -Value ([ordered]@{
    schema_version=1;role='oa_tof_contract_test_summary';status='success'
  })
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot `
    -RunConfig $successConfig -Status success -Outputs @($successSummary)
  $successManifest = Get-Content -LiteralPath (Join-Path $successDir 'run_manifest.json') `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  Assert-Equal $successManifest.status 'success' 'Success manifest status changed.'

  $writeError = ''
  try {
    Write-VerifiedRunManifest -Python (Join-Path $testRoot 'missing-python.exe') `
      -RepoRoot $repoRoot -RunConfig $successConfig -Status failed
  } catch {
    $writeError = $_.Exception.Message
  }
  Assert-Equal $writeError 'Could not write failed run manifest.' `
    'Manifest write failure message changed.'

  $timeoutRejected = $false
  try {
    Write-RunManifest -Python $python -RepoRoot $repoRoot `
      -RunConfig $successConfig -Status timeout
  } catch {
    $timeoutRejected = $true
  }
  Assert-Equal $timeoutRejected $true `
    'PowerShell manifest support must not reinterpret candidate-workflow timeout.'

  Write-Output 'RUN_ARTIFACT_SUPPORT=PASS'
} finally {
  if (Test-Path -LiteralPath $testRoot) {
    [IO.Directory]::Delete($testRoot, $true)
  }
}
