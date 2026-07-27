[CmdletBinding()]
param(
  [ValidateSet('baseline_finite_3d','endplate_acceleration_reference')]
  [string]$RuntimeProfileId = 'baseline_finite_3d',
  [string]$EvidenceContractPath = '',
  [string]$RunId = '',
  [string]$PythonExe = '',
  [string]$ReferenceComsolRunId = '',
  [string]$SimionExe = '',
  [string]$TemplateIob = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
$resolutionPath = Join-Path ([IO.Path]::GetTempPath()) ("rfhex_runtime_{0}.json" -f [guid]::NewGuid())
try {
  Push-Location $repoRoot
  try {
    & $python -m common.multipole.runtime_profile --repo-root $repoRoot `
      --project-id rf_hexapole_ion_guide --runtime-profile-id $RuntimeProfileId `
      --output $resolutionPath
  } finally { Pop-Location }
  if ($LASTEXITCODE -ne 0) { throw 'RF hexapole runtime profile resolution failed.' }
  $profile = Get-Content -LiteralPath $resolutionPath -Raw -Encoding UTF8 | ConvertFrom-Json
  $numerics = $profile.solver_numerics.simion.values
  $arguments = @{
    ProjectId = 'rf_hexapole_ion_guide'
    DesignProfileId = [string]$profile.design_profile_id
    ParticleSourcePath = [string]$profile.particle_source.path
    RunId = $RunId
    PythonExe = $python
    ReferenceComsolRunId = $ReferenceComsolRunId
    CellMm = [double]$numerics.cell_mm
    RfStepsPerPeriod = [int]$numerics.trajectory.rf_steps_per_period
    TrajectoryQuality = [int]$numerics.trajectory_quality
    MaximumTimeUs = [double]$numerics.trajectory.maximum_global_time_us
  }
  if ($EvidenceContractPath) { $arguments.EvidenceContractPath = $EvidenceContractPath }
  if ($SimionExe) { $arguments.SimionExe = $SimionExe }
  if ($TemplateIob) { $arguments.TemplateIob = $TemplateIob }
  & (Join-Path $repoRoot 'common\multipole\run_simion_finite_3d_transport.ps1') @arguments
  if ($LASTEXITCODE -ne 0) { throw 'RF hexapole SIMION transport failed.' }
} finally {
  Remove-Item -LiteralPath $resolutionPath -Force -ErrorAction SilentlyContinue
}
