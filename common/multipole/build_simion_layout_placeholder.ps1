<#
.SYNOPSIS
Builds the one non-physical PA used to create the shared multipole GUI layout.

.DESCRIPTION
The legacy quad_monolithic basename is retained only to minimize the later
production-runner migration.  It does not identify quadrupole physics.
This command creates no IOB, CON, Program, particle source, voltage, or run.
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$OutputDir,
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'require_powershell7.ps1')

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$canonicalScratchRoot = [IO.Path]::GetFullPath(
  (Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling\scratch'))
$source = Join-Path $PSScriptRoot 'multipole_layout_placeholder.gem'
$output = [IO.Path]::GetFullPath($OutputDir)
$scratchPrefix = $canonicalScratchRoot + [IO.Path]::DirectorySeparatorChar
if (-not $output.StartsWith($scratchPrefix, [StringComparison]::OrdinalIgnoreCase)) {
  throw "OutputDir must be below the fixed multipole provider scratch root: $canonicalScratchRoot"
}
$buildDir = Join-Path $output 'build'
$guiSourceDir = Join-Path $output 'gui_source'
$frozenGem = Join-Path $buildDir 'multipole_layout_placeholder.gem'
$placeholder = Join-Path $guiSourceDir 'quad_monolithic.pa0'
if (-not (Test-Path -LiteralPath $SimionExe -PathType Leaf)) {
  throw "SIMION executable is missing: $SimionExe"
}
if (Test-Path -LiteralPath $output) {
  if (@(Get-ChildItem -LiteralPath $output -Force).Count -ne 0) {
    throw "OutputDir already exists and is not empty: $output"
  }
} else {
  New-Item -ItemType Directory -Path $output | Out-Null
}
New-Item -ItemType Directory -Path $buildDir, $guiSourceDir | Out-Null
Copy-Item -LiteralPath $source -Destination $frozenGem
if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -cne
    (Get-FileHash -LiteralPath $frozenGem -Algorithm SHA256).Hash) {
  throw 'Frozen placeholder GEM differs from the canonical repository GEM.'
}

Push-Location $buildDir
try {
  & $SimionExe --nogui --noprompt gem2pa $frozenGem $placeholder
  if ($LASTEXITCODE -ne 0) {
    throw 'SIMION did not build the multipole layout placeholder.'
  }
} finally {
  Pop-Location
}
if (-not (Test-Path -LiteralPath $placeholder -PathType Leaf)) {
  throw "SIMION did not generate the placeholder PA: $placeholder"
}
[ordered]@{
  schema_version = 1
  role = 'multipole_simion_layout_placeholder'
  physical_model = $false
  pa_basename = 'quad_monolithic.pa0'
  legacy_basename_semantics = 'compatibility_role_name_not_quadrupole_physics'
  source_gem_identity = [ordered]@{
    role = 'shared_multipole_layout_placeholder_source'
    repo_path = 'common/multipole/multipole_layout_placeholder.gem'
    sha256 = (Get-FileHash -LiteralPath $frozenGem -Algorithm SHA256).Hash
  }
  source_gem_sha256 = (Get-FileHash -LiteralPath $frozenGem -Algorithm SHA256).Hash
  output_pa0_sha256 = (Get-FileHash -LiteralPath $placeholder -Algorithm SHA256).Hash
  frozen_gem_path = 'build/multipole_layout_placeholder.gem'
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (
  Join-Path $guiSourceDir 'placeholder_manifest.json') -Encoding UTF8

"MULTIPOLE_LAYOUT_PLACEHOLDER=PASS GUI_SOURCE_DIR=$guiSourceDir BUILD_DIR=$buildDir"
