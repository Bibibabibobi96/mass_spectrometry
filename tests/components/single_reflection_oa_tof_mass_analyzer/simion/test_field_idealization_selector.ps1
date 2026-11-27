Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$runner = Join-Path $repo 'src/msplatform/workflows/resources/run_field_idealization_sweep.ps1'
$science = Join-Path $repo 'src/msplatform/components/single_reflection_oa_tof'
$workspace = Split-Path -Parent $repo
$artifactRoot = Join-Path $workspace 'artifacts'
$valid = Join-Path $science 'config/diagnostics/field_idealization_feasibility.json'
$context = @{WorkspaceRoot=$repo; ArtifactRootPath=$artifactRoot; ScienceRoot=$science}
& $runner @context -CaseConfig $valid -ValidateConfigOnly

$invalid = Join-Path $env:TEMP ('oatof_invalid_field_selector_' + [Guid]::NewGuid().ToString('N') + '.json')
try {
  [IO.File]::WriteAllText($invalid,'{"particle_count":100,"cases":[{"id":"bad","selector":"ideal:stage1.ex"}]}',[Text.UTF8Encoding]::new($false))
  $rejected = $false
  try { & $runner @context -CaseConfig $invalid -ValidateConfigOnly } catch { $rejected = $_.Exception.Message -match 'supports composable Ez only' }
  if (-not $rejected) { throw 'SIMION Ex selector was not rejected with the capability-boundary error.' }
} finally {
  if (Test-Path -LiteralPath $invalid) { Remove-Item -LiteralPath $invalid -Force }
}
Write-Host 'SIMION_FIELD_SELECTOR_TEST=PASS'
