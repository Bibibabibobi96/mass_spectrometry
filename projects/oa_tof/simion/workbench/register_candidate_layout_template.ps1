<#!
.SYNOPSIS
Registers a GUI-materialized, declarative W-GEM SIMION four-slot layout for oa-TOF Candidate runs.

.DESCRIPTION
This entrypoint never creates, copies, refines, or flies a SIMION binary.  It
records the explicitly supplied W-GEM + IOB+CON as immutable external inputs of a
template-build run, then uses the existing no-GUI IOB structure verifier to
prove the GUI-editable slot order.  Candidate preparation may consume only a
successful registration run and freezes its input bundle into the Candidate
run separately.
#>
param(
  [Parameter(Mandatory = $true)] [string]$SourceIobPath,
  [Parameter(Mandatory = $true)] [string]$SourceConPath,
  [Parameter(Mandatory = $true)] [string]$SourceWgemPath,
  [Parameter(Mandatory = $true)] [string]$RunId,
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [string]$ArtifactProjectRoot = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
if ([string]::IsNullOrWhiteSpace($ArtifactProjectRoot)) {
  $ArtifactProjectRoot = Join-Path $workspaceRoot 'artifacts\projects\oa_tof'
}
$artifactRoot = [IO.Path]::GetFullPath($ArtifactProjectRoot)
$runsRoot = Join-Path $artifactRoot 'runs'

function Test-ProhibitedTemplatePath([string]$Path) {
  $segments = ([IO.Path]::GetFullPath($Path).ToLowerInvariant() -split '[\\/]')
  return @('formal', 'archive', 'history') | Where-Object { $segments -contains $_ }
}

function Assert-NonFormalSource([string]$Path, [string]$Label) {
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "$Label is missing: $Path"
  }
  $resolved = (Resolve-Path -LiteralPath $Path).Path
  if (Test-ProhibitedTemplatePath $resolved) {
    throw "$Label must not be sourced from Formal, archive, or history: $resolved"
  }
  return $resolved
}

# Validate before creating the target run directory.
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { $python = 'python' }
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw "Invalid template-build RunId: $RunId" }

$sourceIob = Assert-NonFormalSource $SourceIobPath 'SourceIobPath'
$sourceCon = Assert-NonFormalSource $SourceConPath 'SourceConPath'
$sourceWgem = Assert-NonFormalSource $SourceWgemPath 'SourceWgemPath'
if ([IO.Path]::GetExtension($sourceIob).ToLowerInvariant() -ne '.iob') { throw 'SourceIobPath must use the .iob extension.' }
if ([IO.Path]::GetExtension($sourceCon).ToLowerInvariant() -ne '.con') { throw 'SourceConPath must use the .con extension.' }
if ([IO.Path]::GetExtension($sourceWgem).ToLowerInvariant() -ne '.wgem') { throw 'SourceWgemPath must use the .wgem extension.' }
if ([IO.Path]::GetFileNameWithoutExtension($sourceIob) -cne [IO.Path]::GetFileNameWithoutExtension($sourceCon)) {
  throw 'SourceIobPath and SourceConPath must have the same basename.'
}
$candidateSourceRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot 'simion\workbench\candidates'))
if (-not $sourceWgem.StartsWith($candidateSourceRoot, [StringComparison]::OrdinalIgnoreCase)) {
  throw 'SourceWgemPath must be the Git-tracked oa-TOF Candidate declarative source.'
}
foreach ($requiredToken in @('GENERATED: oa-TOF Candidate declarative workbench source', 'role=flight_tube_shield', 'role=reflectron', 'role=accelerator', 'role=detector', 'pa_define {', "filename='flight_tube_ground.pa0'", "filename='reflectron.pa0'", "filename='accelerator.pa0'", "filename='detector_ground.pa0'")) {
  if (-not (Select-String -LiteralPath $sourceWgem -Pattern ([regex]::Escape($requiredToken)) -Quiet)) {
    throw "SourceWgemPath is not an accepted oa-TOF declarative Candidate source: missing $requiredToken"
  }
}

$runRoot = Join-Path $runsRoot $RunId
if (Test-Path -LiteralPath $runRoot) { throw "Template-build run already exists: $runRoot" }
foreach ($source in @($sourceIob, $sourceCon, $sourceWgem)) {
  if ($source.StartsWith(([IO.Path]::GetFullPath($runRoot)), [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Template source must not be located in its target template-build run.'
  }
}

$runConfig = [ordered]@{
  schema_version = 1
  role = 'oa_tof_simion_candidate_layout_template_build'
  run_id = $RunId
  project = 'oa_tof'
  mode = 'candidate_layout_template_build'
  project_root = $projectRoot
  inputs = [ordered]@{ source_wgem = $sourceWgem; source_iob = $sourceIob; source_con = $sourceCon }
  input_sha256 = [ordered]@{
    source_wgem = (Get-FileHash -LiteralPath $sourceWgem -Algorithm SHA256).Hash
    source_iob = (Get-FileHash -LiteralPath $sourceIob -Algorithm SHA256).Hash
    source_con = (Get-FileHash -LiteralPath $sourceCon -Algorithm SHA256).Hash
  }
  formal_gate_passed = $false
  template_role = 'oa_tof_candidate_simion_layout_template'
  source_is_declarative_wgem_gui_materialization = $true
}

New-Item -ItemType Directory -Path $runRoot -ErrorAction Stop | Out-Null
$runConfigPath = Join-Path $runRoot 'run_config.json'
$summaryPath = Join-Path $runRoot 'summary.json'
$runtimeReport = Join-Path $runRoot 'simion_layout_runtime_report.txt'
try {
  $runConfig | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runConfigPath -Encoding UTF8
  $verifier = Join-Path $projectRoot 'tests\simion\verify_iob_runtime_contract.ps1'
  & $verifier -IobPath $sourceIob -ExpectedInstances 4 -TemplateStructureOnly -SimionExe $SimionExe |
    Set-Content -LiteralPath $runtimeReport -Encoding UTF8
  if ($LASTEXITCODE -ne 0) { throw "SIMION template structure verification failed with exit code $LASTEXITCODE" }
  if (-not (Select-String -LiteralPath $runtimeReport -Pattern '^STATUS=PASS$' -Quiet)) {
    throw 'SIMION template structure verification did not produce STATUS=PASS.'
  }
  if (-not (Select-String -LiteralPath $runtimeReport -Pattern '^INSTANCE_COUNT=4$' -Quiet)) {
    throw 'SIMION template structure verification did not prove four editable instances.'
  }
  if (-not (Select-String -LiteralPath $runtimeReport -Pattern '^TEMPLATE_STRUCTURE_ONLY=true$' -Quiet)) {
    throw 'SIMION template verification did not run in structure-only mode.'
  }
  [ordered]@{
    schema_version = 1
    role = 'oa_tof_simion_candidate_layout_template_build_summary'
    status = 'success'
    template_role = 'oa_tof_candidate_simion_layout_template'
    source_wgem_sha256 = $runConfig.input_sha256.source_wgem
    source_iob_sha256 = $runConfig.input_sha256.source_iob
    source_con_sha256 = $runConfig.input_sha256.source_con
    runtime_structure_verified = $true
    particle_fly_executed = $false
    formal_modified = $false
  } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
  $manifestWriter = Join-Path $repoRoot 'common\contracts\write_run_manifest.py'
  $manifestVerifier = Join-Path $repoRoot 'common\contracts\verify_run_manifest.py'
  & $python $manifestWriter --run-config $runConfigPath --manifest (Join-Path $runRoot 'run_manifest.json') --status success `
    --software 'SIMION 2020 no-GUI layout structure verifier' --output $summaryPath --output $runtimeReport
  if ($LASTEXITCODE -ne 0) { throw 'Template-build manifest generation failed.' }
  & $python $manifestVerifier (Join-Path $runRoot 'run_manifest.json') --require-status success --require-local-run-config `
    --require-run-id $RunId --require-project oa_tof --require-mode candidate_layout_template_build
  if ($LASTEXITCODE -ne 0) { throw 'Template-build manifest verification failed.' }
  "CANDIDATE_LAYOUT_TEMPLATE_REGISTER=PASS RUN_ROOT=$runRoot"
}
catch {
  $message = $_.Exception.Message
  if (-not (Test-Path -LiteralPath $runConfigPath -PathType Leaf)) {
    $runConfig | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runConfigPath -Encoding UTF8
  }
  [ordered]@{
    schema_version = 1; role = 'oa_tof_simion_candidate_layout_template_build_summary'; status = 'failed'
    template_role = 'oa_tof_candidate_simion_layout_template'; failure_stage = 'layout_structure_verification'
    error = $message; particle_fly_executed = $false; formal_modified = $false
  } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
  try {
    & $python (Join-Path $repoRoot 'common\contracts\write_run_manifest.py') --run-config $runConfigPath `
      --manifest (Join-Path $runRoot 'run_manifest.json') --status failed --output $summaryPath
  } catch { }
  throw
}
