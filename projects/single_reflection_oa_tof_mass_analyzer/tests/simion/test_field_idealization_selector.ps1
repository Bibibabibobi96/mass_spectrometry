Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$runner = Join-Path $PSScriptRoot 'run_field_idealization_sweep.ps1'
$valid = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'config\diagnostics\field_idealization_feasibility.json'
& $runner -CaseConfig $valid -ValidateConfigOnly

$invalid = Join-Path $env:TEMP ('oatof_invalid_field_selector_' + [Guid]::NewGuid().ToString('N') + '.json')
try {
  [IO.File]::WriteAllText($invalid,'{"particle_count":100,"cases":[{"id":"bad","selector":"ideal:stage1.ex"}]}',[Text.UTF8Encoding]::new($false))
  $rejected = $false
  try { & $runner -CaseConfig $invalid -ValidateConfigOnly } catch { $rejected = $_.Exception.Message -match 'supports composable Ez only' }
  if (-not $rejected) { throw 'SIMION Ex selector was not rejected with the capability-boundary error.' }
} finally {
  if (Test-Path -LiteralPath $invalid) { Remove-Item -LiteralPath $invalid -Force }
}
Write-Host 'SIMION_FIELD_SELECTOR_TEST=PASS'
