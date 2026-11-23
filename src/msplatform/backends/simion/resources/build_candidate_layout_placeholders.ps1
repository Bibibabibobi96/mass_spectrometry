<#
.SYNOPSIS
Builds four non-physical PA0 files for one manually assembled oa-TOF Candidate layout.

.DESCRIPTION
The output is a GUI seed only. It contains no oa-TOF geometry, voltage,
particles, Program, or Candidate physics. A user adds the four PA0 files to
one new SIMION Workbench in the listed order, saves an IOB+CON bundle, then
uses register_candidate_layout_template.ps1 to freeze that independent bundle.
#>
param(
  [Parameter(Mandatory = $true)] [string]$OutputDir,
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$source = Join-Path $PSScriptRoot 'candidate_layout_placeholder.gem'
$builder = Join-Path $PSScriptRoot 'build_candidate_layout_placeholders.lua'
$output = [IO.Path]::GetFullPath($OutputDir)
if (-not (Test-Path -LiteralPath $SimionExe -PathType Leaf)) {
  throw "SIMION executable is missing: $SimionExe"
}
if (Test-Path -LiteralPath $output) {
  if (@(Get-ChildItem -LiteralPath $output -Force).Count -ne 0) {
    throw "OutputDir already exists and is not empty: $output"
  }
}
else {
  New-Item -ItemType Directory -Path $output | Out-Null
}

& $SimionExe --nogui lua $builder $source $output
if ($LASTEXITCODE -ne 0) { throw 'SIMION did not build Candidate layout placeholders.' }
$names = @('flight_tube_ground.pa0', 'reflectron.pa0', 'accelerator.pa0', 'detector_ground.pa0')
foreach ($name in $names) {
  if (-not (Test-Path -LiteralPath (Join-Path $output $name) -PathType Leaf)) {
    throw "SIMION did not generate placeholder PA: $name"
  }
}
[ordered]@{
  role = 'oa_tof_candidate_layout_placeholders'
  physical_model = $false
  pa_order = $names
  source_gem_sha256 = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $output 'placeholder_manifest.json') -Encoding UTF8

"CANDIDATE_LAYOUT_PLACEHOLDERS=PASS OUTPUT_DIR=$output"
