Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-SimionCompiledApertureTopologyCheck {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$PaPath,
    [Parameter(Mandatory)][string]$ReportPath,
    [Parameter(Mandatory)][string]$VerifierPath,
    [Parameter(Mandatory)][double]$OriginXmm,
    [Parameter(Mandatory)][double]$OriginYmm,
    [Parameter(Mandatory)][double]$OriginZmm,
    [Parameter(Mandatory)][double]$CellMmX,
    [Parameter(Mandatory)][double]$CellMmY,
    [Parameter(Mandatory)][double]$CellMmZ,
    [Parameter(Mandatory)][double]$FlangeXMinMm,
    [Parameter(Mandatory)][double]$FlangeXMaxMm,
    [Parameter(Mandatory)][double]$CenterYmm,
    [Parameter(Mandatory)][double]$CenterZmm,
    [Parameter(Mandatory)][double]$MechanicalWidthMm,
    [Parameter(Mandatory)][double]$MechanicalHeightMm,
    [Parameter(Mandatory)][string]$BooleanBoundaryPolicy,
    [Parameter(Mandatory)][scriptblock]$InvokeVerifier
  )

  if ($CellMmX -le 0 -or $CellMmY -le 0 -or $CellMmZ -le 0 -or
      $MechanicalWidthMm -lt $CellMmY -or
      $MechanicalHeightMm -lt $CellMmZ) {
    throw 'SIMION aperture width and height must each be at least one positive cell.'
  }
  if ($FlangeXMaxMm -lt $FlangeXMinMm) {
    throw 'SIMION aperture flange bounds are reversed.'
  }
  if ($BooleanBoundaryPolicy -cne 'exclude_shape_inside_or_on_v1') {
    throw "Unsupported SIMION aperture Boolean boundary policy: $BooleanBoundaryPolicy"
  }
  foreach ($path in @($PaPath,$VerifierPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
      throw "SIMION aperture topology input is missing: $path"
    }
  }

  $invariant = [Globalization.CultureInfo]::InvariantCulture
  $environment = [ordered]@{
    SIMION_APERTURE_PA_PATH = [IO.Path]::GetFullPath($PaPath)
    SIMION_APERTURE_REPORT_PATH = [IO.Path]::GetFullPath($ReportPath)
    SIMION_APERTURE_ORIGIN_X_MM = $OriginXmm.ToString('R',$invariant)
    SIMION_APERTURE_ORIGIN_Y_MM = $OriginYmm.ToString('R',$invariant)
    SIMION_APERTURE_ORIGIN_Z_MM = $OriginZmm.ToString('R',$invariant)
    SIMION_APERTURE_CELL_MM_X = $CellMmX.ToString('R',$invariant)
    SIMION_APERTURE_CELL_MM_Y = $CellMmY.ToString('R',$invariant)
    SIMION_APERTURE_CELL_MM_Z = $CellMmZ.ToString('R',$invariant)
    SIMION_APERTURE_FLANGE_X_MIN_MM = $FlangeXMinMm.ToString('R',$invariant)
    SIMION_APERTURE_FLANGE_X_MAX_MM = $FlangeXMaxMm.ToString('R',$invariant)
    SIMION_APERTURE_CENTER_Y_MM = $CenterYmm.ToString('R',$invariant)
    SIMION_APERTURE_CENTER_Z_MM = $CenterZmm.ToString('R',$invariant)
    SIMION_APERTURE_WIDTH_MM = $MechanicalWidthMm.ToString('R',$invariant)
    SIMION_APERTURE_HEIGHT_MM = $MechanicalHeightMm.ToString('R',$invariant)
    SIMION_APERTURE_BOOLEAN_BOUNDARY_POLICY = $BooleanBoundaryPolicy
  }
  $saved = @{}
  foreach ($name in $environment.Keys) {
    $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
  }
  try {
    foreach ($name in $environment.Keys) {
      [Environment]::SetEnvironmentVariable($name, $environment[$name], 'Process')
    }
    $processResult = & $InvokeVerifier ([IO.Path]::GetFullPath($VerifierPath))
  } finally {
    foreach ($name in $environment.Keys) {
      [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process')
    }
  }
  if ($null -eq $processResult -or $null -eq $processResult.exit_code) {
    throw 'SIMION aperture verifier callback did not return an exit_code.'
  }
  if ($processResult.resource_budget_exceeded) {
    throw 'SIMION aperture topology verification exceeded its resource budget.'
  }
  if ($processResult.exit_code -ne 0 -or
      -not (Test-Path -LiteralPath $ReportPath -PathType Leaf)) {
    throw 'Compiled SIMION PA aperture topology verification failed.'
  }
  $audit = Get-Content -LiteralPath $ReportPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($audit.role -cne 'simion_compiled_pa_aperture_topology_check' -or
      $audit.status -cne 'PASS' -or [int]$audit.open_column_count -lt 1 -or
      -not $audit.guard_electrode_check_passed) {
    throw 'Compiled SIMION PA aperture topology audit did not pass.'
  }
  return [pscustomobject]@{ process_result=$processResult; audit=$audit }
}
