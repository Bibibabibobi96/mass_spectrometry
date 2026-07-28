<#
.SYNOPSIS
Registers one GUI-created, nonphysical SIMION layout for shared multipole runs.

.DESCRIPTION
This follows the oa-TOF Candidate template pattern: verify one GUI-editable PA
instance without flying particles, write a successful registration run, and let
production runners freeze the registered IOB+CON separately.
#>
param(
  [Parameter(Mandatory = $true)] [string]$SourceIobPath,
  [Parameter(Mandatory = $true)] [string]$SourceConPath,
  [Parameter(Mandatory = $true)] [string]$RunId,
  [Parameter(Mandatory = $true)] [switch]$ConfirmGuiCreatedAndReopened,
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [string]$ArtifactProjectRoot = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$providerProject = 'rf_quadrupole_ion_optics'
if ([string]::IsNullOrWhiteSpace($ArtifactProjectRoot)) {
  $ArtifactProjectRoot = Join-Path $workspaceRoot "artifacts\projects\$providerProject"
}
$artifactRoot = [IO.Path]::GetFullPath($ArtifactProjectRoot)
$scratchRoot = [IO.Path]::GetFullPath((Join-Path $artifactRoot 'scratch'))
$runsRoot = Join-Path $artifactRoot 'runs'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { $python = 'python' }

if (-not $ConfirmGuiCreatedAndReopened) {
  throw 'ConfirmGuiCreatedAndReopened is required.'
}
if (-not (Test-Path -LiteralPath $SimionExe -PathType Leaf)) {
  throw "SIMION executable is missing: $SimionExe"
}
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw "Invalid template registration RunId: $RunId" }

$sourceIob = (Resolve-Path -LiteralPath $SourceIobPath).Path
$sourceCon = (Resolve-Path -LiteralPath $SourceConPath).Path
if (-not $sourceIob.StartsWith($scratchRoot, [StringComparison]::OrdinalIgnoreCase) -or
    -not $sourceCon.StartsWith($scratchRoot, [StringComparison]::OrdinalIgnoreCase)) {
  throw 'Template IOB+CON must come from the provider project scratch directory.'
}
if ([IO.Path]::GetDirectoryName($sourceIob) -cne [IO.Path]::GetDirectoryName($sourceCon)) {
  throw 'Template IOB+CON must come from the same GUI source directory.'
}
if ([IO.Path]::GetFileNameWithoutExtension($sourceIob) -cne
    [IO.Path]::GetFileNameWithoutExtension($sourceCon)) {
  throw 'Template IOB+CON basenames differ.'
}
if ([IO.Path]::GetExtension($sourceIob).ToLowerInvariant() -ne '.iob' -or
    [IO.Path]::GetExtension($sourceCon).ToLowerInvariant() -ne '.con') {
  throw 'Template source must be a matching .iob + .con pair.'
}
$sourcePa = [IO.Path]::ChangeExtension($sourceIob, '.pa0')
if (-not (Test-Path -LiteralPath $sourcePa -PathType Leaf)) {
  throw "Template placeholder PA is missing beside the IOB: $sourcePa"
}

$runRoot = Join-Path $runsRoot $RunId
if (Test-Path -LiteralPath $runRoot) { throw "Registration run already exists: $runRoot" }
$bundle = Join-Path $runRoot 'inputs\template_bundle'
$codeDir = Join-Path $runRoot 'inputs\code'
$logDir = Join-Path $runRoot 'logs'
New-Item -ItemType Directory -Path $bundle, $codeDir, $logDir | Out-Null

$templateIob = Join-Path $bundle 'quad_monolithic.iob'
$templateCon = Join-Path $bundle 'quad_monolithic.con'
$templatePa = Join-Path $bundle 'quad_monolithic.pa0'
$inspector = Join-Path $codeDir 'inspect_simion_layout_template.lua'
Copy-Item -LiteralPath $sourceIob -Destination $templateIob
Copy-Item -LiteralPath $sourceCon -Destination $templateCon
Copy-Item -LiteralPath $sourcePa -Destination $templatePa
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'inspect_simion_layout_template.lua') -Destination $inspector

$runConfigPath = Join-Path $runRoot 'run_config.json'
$summaryPath = Join-Path $runRoot 'summary.json'
$manifestPath = Join-Path $runRoot 'run_manifest.json'
$reportPath = Join-Path $logDir 'simion_layout_structure_report.txt'
$stdoutPath = Join-Path $logDir 'simion_layout_stdout.txt'
$stderrPath = Join-Path $logDir 'simion_layout_stderr.txt'
$inputs = [ordered]@{
  template_iob = $templateIob
  template_con = $templateCon
  template_placeholder_pa0 = $templatePa
  structure_verifier = $inspector
}
$inputSha256 = [ordered]@{}
foreach ($entry in $inputs.GetEnumerator()) {
  $inputSha256[$entry.Key] = (Get-FileHash -LiteralPath $entry.Value -Algorithm SHA256).Hash
}
[ordered]@{
  schema_version = 1
  role = 'multipole_simion_layout_template_build'
  run_id = $RunId
  project = $providerProject
  mode = 'simion_layout_template_build'
  provider_project_id = $providerProject
  template_role = 'shared_multipole_single_pa_layout_template'
  physical_model = $false
  formal_gate_passed = $false
  inputs = $inputs
  input_sha256 = $inputSha256
  structural_contract = [ordered]@{
    instance_count = 1
    pa_basename = 'quad_monolithic.pa0'
    transform = [ordered]@{ x = 0; y = 0; z = 0; az = -90; el = 0; rt = 180; scale = 1 }
  }
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runConfigPath -Encoding UTF8

try {
  $env:MULTIPOLE_TEMPLATE_REPORT = $reportPath
  $env:MULTIPOLE_TEMPLATE_IOB = $templateIob
  $env:MULTIPOLE_TEMPLATE_BUNDLE_ROOT = $bundle
  try {
    $quotedInspector = '"' + $inspector + '"'
    $process = Start-Process -FilePath $SimionExe -ArgumentList @(
      '--nogui', '--noprompt', 'lua', $quotedInspector
    ) -WorkingDirectory $bundle -WindowStyle Hidden -Wait -PassThru `
      -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
  } finally {
    Remove-Item Env:MULTIPOLE_TEMPLATE_REPORT, Env:MULTIPOLE_TEMPLATE_IOB, `
      Env:MULTIPOLE_TEMPLATE_BUNDLE_ROOT -ErrorAction SilentlyContinue
  }
  if ($process.ExitCode -ne 0) {
    throw "SIMION layout structure verification failed: $($process.ExitCode)"
  }
  $report = Get-Content -LiteralPath $reportPath -Raw
  foreach ($token in @(
      'STATUS=PASS', 'INSTANCE_COUNT=1',
      'INSTANCE_1_TRANSFORM=0,0,0,-90,0,180,1',
      'PROGRAM_EXECUTED=false', 'PARTICLE_FLY_EXECUTED=false')) {
    if (-not $report.Contains($token)) { throw "Structure report is missing: $token" }
  }
  [ordered]@{
    schema_version = 1
    role = 'multipole_simion_layout_template_build_summary'
    status = 'success'
    runtime_structure_verified = $true
    program_executed = $false
    particle_fly_executed = $false
    formal_modified = $false
  } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
  & $python (Join-Path $repoRoot 'common\contracts\write_run_manifest.py') `
    --run-config $runConfigPath --manifest $manifestPath --status success `
    --software 'SIMION 2020 no-GUI structure verifier' `
    --output $summaryPath --output $reportPath --output $stdoutPath --output $stderrPath
  if ($LASTEXITCODE -ne 0) { throw 'Registration manifest generation failed.' }
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $manifestPath `
    --require-status success --require-local-run-config --require-run-id $RunId `
    --require-project $providerProject --require-mode simion_layout_template_build
  if ($LASTEXITCODE -ne 0) { throw 'Registration manifest verification failed.' }
  "MULTIPOLE_LAYOUT_TEMPLATE_REGISTER=PASS RUN_ROOT=$runRoot"
} catch {
  $message = $_.Exception.Message
  [ordered]@{
    schema_version = 1
    role = 'multipole_simion_layout_template_build_summary'
    status = 'failed'
    failure_stage = 'layout_structure_verification'
    error = $message
    particle_fly_executed = $false
    formal_modified = $false
  } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
  try {
    & $python (Join-Path $repoRoot 'common\contracts\write_run_manifest.py') `
      --run-config $runConfigPath --manifest $manifestPath --status failed --output $summaryPath
  } catch { }
  throw
}
