$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Initialize-OaTofRunRecord {
  param(
    [Parameter(Mandatory=$true)][string]$RunDir,
    [Parameter(Mandatory=$true)][string]$RunId,
    [Parameter(Mandatory=$true)][string]$Mode,
    [Parameter(Mandatory=$true)][string]$ProjectRoot,
    [Parameter(Mandatory=$true)][string]$RepoRoot,
    [Parameter(Mandatory=$true)][string]$Python
  )
  $config = Join-Path $RunDir 'run_config.json'
  $summary = Join-Path $RunDir 'summary.json'
  [ordered]@{
    schema_version=1;run_id=$RunId;project='oa_tof';mode=$Mode
    project_root=$ProjectRoot;formal_gate_passed=$false;inputs=[ordered]@{}
  } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $config -Encoding UTF8
  [ordered]@{
    schema_version=1;role='oa_tof_provisional_run_summary';status='interrupted'
    reason='Run package initialized; terminal status was not recorded.'
  } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summary -Encoding UTF8
  Write-OaTofTerminalRunRecord -RunDir $RunDir -Status interrupted `
    -Reason 'Run package initialized.' -RepoRoot $RepoRoot -Python $Python
}

function Write-OaTofTerminalRunRecord {
  param(
    [Parameter(Mandatory=$true)][string]$RunDir,
    [ValidateSet('failed','interrupted')][string]$Status,
    [Parameter(Mandatory=$true)][string]$Reason,
    [Parameter(Mandatory=$true)][string]$RepoRoot,
    [Parameter(Mandatory=$true)][string]$Python
  )
  $config = Join-Path $RunDir 'run_config.json'
  $summary = Join-Path $RunDir 'summary.json'
  [ordered]@{
    schema_version=1;role='oa_tof_terminal_run_summary';status=$Status;reason=$Reason
  } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summary -Encoding UTF8
  $writer = Join-Path $RepoRoot 'common\contracts\write_run_manifest.py'
  $manifest = Join-Path $RunDir 'run_manifest.json'
  & $Python $writer --run-config $config --manifest $manifest --status $Status `
    --output $summary
  if ($LASTEXITCODE -ne 0) { throw "Could not write $Status run manifest." }
  & $Python (Join-Path $RepoRoot 'common\contracts\verify_run_manifest.py') `
    $manifest --require-status $Status
  if ($LASTEXITCODE -ne 0) { throw "Could not verify $Status run manifest." }
}
