param(
  [int]$N = 100,
  [double]$MassAmu = 524,
  [int]$Charge = 1,
  [double]$EnergyMeanEv = 5,
  [double]$EnergyStdEv = 0.4,
  [double]$HalfWidthMm = 0.5,
  [double]$HalfWidthXmm = -1,
  [double]$HalfWidthYmm = -1,
  [double]$HalfWidthZmm = -1,
  [double]$CenterXmm = -48.8,
  [double]$CenterYmm = 0.0,
  [double]$CenterZmm = -18.42918680341103,
  [int]$Seed = 20260713,
  [string]$Output = '',
  [switch]$AllowNonstandardDiagnosticCount
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($Output)) {
  $massLabel = $MassAmu.ToString('g', [Globalization.CultureInfo]::InvariantCulture)
  $Output = "oatof_comsol_${massLabel}amu_gaussian_N${N}.ion"
}
$hx = if ($HalfWidthXmm -ge 0) { $HalfWidthXmm } else { $HalfWidthMm }
$hy = if ($HalfWidthYmm -ge 0) { $HalfWidthYmm } else { $HalfWidthMm }
$hz = if ($HalfWidthZmm -ge 0) { $HalfWidthZmm } else { $HalfWidthMm }
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$arguments = @(
  (Join-Path $projectRoot 'analysis\generate_ion_source.py')
  '--particle-count'; [string]$N
  '--mass-amu'; [string]$MassAmu
  '--charge'; [string]$Charge
  '--energy-mean-ev'; [string]$EnergyMeanEv
  '--energy-std-ev'; [string]$EnergyStdEv
  '--half-width-x-mm'; [string]$hx
  '--half-width-y-mm'; [string]$hy
  '--half-width-z-mm'; [string]$hz
  '--center-x-mm'; [string]$CenterXmm
  '--center-y-mm'; [string]$CenterYmm
  '--center-z-mm'; [string]$CenterZmm
  '--seed'; [string]$Seed
  '--output'; $Output
)
if ($AllowNonstandardDiagnosticCount) {
  $arguments += '--allow-nonstandard-diagnostic-count'
}
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw 'Python ION source generation failed.' }
