param(
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [Parameter(Mandatory=$true)][string]$IobPath,
  [Parameter(Mandatory=$true)][string]$OutputCsv,
  [Parameter(Mandatory=$true)][string]$ReportPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$contract = Get-Content -LiteralPath (Join-Path $projectRoot 'config\resolved_geometry.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$geometry = $contract.geometry_mm
$source = $contract.particle_source
$old = @{}
$environment = @{
  OATOF_FORMAL_IOB_PATH = [IO.Path]::GetFullPath($IobPath)
  OATOF_SIMION_FIELD_CSV = [IO.Path]::GetFullPath($OutputCsv)
  OATOF_SIMION_FIELD_REPORT = [IO.Path]::GetFullPath($ReportPath)
  OATOF_ACCELERATOR_AXIS_X_MM = [string]$contract.coordinate_convention.accelerator_axis_x
  OATOF_REFLECTRON_AXIS_X_MM = [string]$contract.coordinate_convention.reflectron_axis[0]
  OATOF_SOURCE_Z_MIN_MM = [string]($source.center_z_mm-$source.size_z_mm/2)
  OATOF_SOURCE_Z_MAX_MM = [string]($source.center_z_mm+$source.size_z_mm/2)
  OATOF_ACCELERATOR_SAMPLE_Z_MIN_MM = [string]($geometry.accelerator_repeller_z+0.2)
  OATOF_ACCELERATOR_SAMPLE_Z_MAX_MM = [string]($geometry.accelerator_grid2_z-0.2)
  OATOF_REFLECTRON_SAMPLE_Z_MIN_MM = [string]($geometry.L_flight+0.25)
  OATOF_REFLECTRON_SAMPLE_Z_MAX_MM = [string]($geometry.L_flight+$geometry.L_reflectron-0.25)
}
try {
  foreach ($item in $environment.GetEnumerator()) {
    $old[$item.Key] = [Environment]::GetEnvironmentVariable($item.Key, 'Process')
    [Environment]::SetEnvironmentVariable($item.Key, $item.Value, 'Process')
  }
  & $SimionExe --nogui lua (Join-Path $PSScriptRoot 'export_axis_field_profiles.lua')
  if ($LASTEXITCODE -ne 0) { throw "SIMION field export failed with exit code $LASTEXITCODE" }
}
finally {
  foreach ($item in $environment.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($item.Key, $old[$item.Key], 'Process')
  }
}
