param(
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\oa_tof'
$legacyWorkspace = Join-Path $artifactRoot 'models\simion\workspace'
$formalDir = Join-Path $artifactRoot 'models\simion\formal\oatof_524amu'

if (Test-Path -LiteralPath $formalDir) {
  throw "Formal delivery directory already exists; preserve it and build in a reviewed new location: $formalDir"
}
New-Item -ItemType Directory -Path $formalDir -Force | Out-Null

function Copy-PaFamily([string]$SourceDir, [string]$Stem, [int]$ExpectedFiles) {
  $files = @(Get-ChildItem -LiteralPath $SourceDir -File | Where-Object {
    $_.Name -eq "$Stem.pa#" -or $_.Name -eq "$Stem.pa-surf" -or $_.Name -match "^$([regex]::Escape($Stem))\.pa\d+$"
  } | Sort-Object Name)
  if ($files.Count -ne $ExpectedFiles) {
    throw "$Stem PA family count mismatch: actual=$($files.Count) expected=$ExpectedFiles"
  }
  foreach ($file in $files) {
    Copy-Item -LiteralPath $file.FullName -Destination (Join-Path $formalDir $file.Name)
  }
}

Copy-PaFamily (Join-Path $legacyWorkspace 'diagnostics\reflectron_mesh_scan\axial0250_radial1000') 'reflectron' 22
Copy-PaFamily (Join-Path $legacyWorkspace 'diagnostics\accelerator_compact_scan\borehalf5\grid_xy025_z0050') 'accelerator' 12
Copy-PaFamily (Join-Path $legacyWorkspace '04_workbench\formal') 'flight_tube_ground' 4
Copy-PaFamily (Join-Path $legacyWorkspace 'diagnostics\detector_marker\xy050_z0010') 'detector_ground' 4

$ionGenerator = Join-Path $PSScriptRoot 'generate_comsol_consistent_ions.ps1'
$ionSets = @(
  @{name='oatof_comsol_524amu_gaussian_N100.ion'; n=100; sha256='B3B2D94110B88F3320B1281B55596FC1AF7A004BCAC66159CA943E7E97180210'},
  @{name='oatof_comsol_524amu_gaussian_N1000.ion'; n=1000; sha256='051E96F28DB911B0D528F496A62B7F4AAF2C727167269ED0F5501D122B6C3562'}
)
foreach ($ionSet in $ionSets) {
  $ionPath = Join-Path $formalDir $ionSet.name
  & $ionGenerator -N $ionSet.n -MassAmu 524 -Charge 1 -EnergyMeanEv 5 -EnergyStdEv 0.4 `
    -HalfWidthMm 0.5 -Seed 20260713 -Output $ionPath | Out-Null
  $ionHash = (Get-FileHash -LiteralPath $ionPath -Algorithm SHA256).Hash
  if ($ionHash -ne $ionSet.sha256) {
    throw "$($ionSet.name) deterministic identity mismatch: $ionHash"
  }
}
Copy-Item -LiteralPath (Join-Path $projectRoot 'docs\SIMION_REPRODUCTION_PARAMETERS.md') `
  -Destination (Join-Path $formalDir 'SIMION_REPRODUCTION_PARAMETERS.md')

$oldValues = @{}
$environment = @{
  OATOF_FOUR_INSTANCE_TEMPLATE_IOB = Join-Path $legacyWorkspace '04_workbench\template_four_instance\mag_halbach_cylinder_2dp.iob'
  OATOF_FORMAL_IOB_OUTPUT = Join-Path $formalDir 'oatof_ideal_grounded.iob'
  OATOF_FORMAL_PA_DIR = $formalDir
  OATOF_FORMAL_PROGRAM_SOURCE = Join-Path $projectRoot 'simion\workbench\formal\oatof_ideal_grounded.lua'
  OATOF_FORMAL_FLY2_SOURCE = Join-Path $projectRoot 'simion\workbench\formal\oatof_ideal_grounded.fly2'
}
try {
  foreach ($item in $environment.GetEnumerator()) {
    $oldValues[$item.Key] = [Environment]::GetEnvironmentVariable($item.Key, 'Process')
    [Environment]::SetEnvironmentVariable($item.Key, $item.Value, 'Process')
  }
  & $SimionExe --nogui lua (Join-Path $PSScriptRoot 'build_formal_iob.lua')
  if ($LASTEXITCODE -ne 0) { throw "Formal IOB build failed with exit code $LASTEXITCODE" }
}
finally {
  foreach ($item in $environment.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($item.Key, $oldValues[$item.Key], 'Process')
  }
}

foreach ($required in @('oatof_ideal_grounded.iob','oatof_ideal_grounded.con','oatof_ideal_grounded.lua','oatof_ideal_grounded.fly2')) {
  if (-not (Test-Path -LiteralPath (Join-Path $formalDir $required) -PathType Leaf)) {
    throw "Formal delivery is missing $required"
  }
}

$hashes = Get-ChildItem -LiteralPath $formalDir -File | Where-Object {
  $_.Name -ne 'SHA256SUMS.csv' -and $_.Name -notlike 'trj*.tmp'
} | Sort-Object Name | ForEach-Object {
  [pscustomobject]@{file=$_.Name; bytes=$_.Length; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}
}
$hashes | Export-Csv -LiteralPath (Join-Path $formalDir 'SHA256SUMS.csv') -NoTypeInformation -Encoding UTF8
"STATUS=PASS FORMAL_DIR=$formalDir FILES=$($hashes.Count)"
