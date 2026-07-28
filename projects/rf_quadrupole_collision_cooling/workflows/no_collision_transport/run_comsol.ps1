[CmdletBinding()]
param(
  [ValidateSet('functional_baseline','functional_spatial_refined','functional_time_refined')]
  [string]$RuntimeProfileId = 'functional_baseline',
  [string]$EvidenceContractPath = '',
  [string]$RunId = '',
  [ValidateSet('compact','qualification','solver_review')][string]$RetentionClass = 'compact',
  [string]$RetentionReason = '',
  [string]$PythonExe = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
$resolutionPath = Join-Path ([IO.Path]::GetTempPath()) ("rfquad_runtime_{0}.json" -f [guid]::NewGuid())
try {
  Push-Location $repoRoot
  try {
    & $python -m common.multipole.runtime_profile --repo-root $repoRoot `
      --project-id rf_quadrupole_collision_cooling --runtime-profile-id $RuntimeProfileId `
      --output $resolutionPath
  } finally { Pop-Location }
  if ($LASTEXITCODE -ne 0) { throw 'RF quadrupole runtime profile resolution failed.' }
  $profile = Get-Content -LiteralPath $resolutionPath -Raw -Encoding UTF8 | ConvertFrom-Json
  $numerics = $profile.solver_numerics.comsol.values
  $arguments = @{
    ProjectId = 'rf_quadrupole_collision_cooling'
    DesignProfileId = [string]$profile.design_profile_id
    ParticleSourcePath = [string]$profile.particle_source.path
    RunId = $RunId
    RetentionClass = $RetentionClass
    RetentionReason = $RetentionReason
    PythonExe = $python
    MeshAutoLevel = [int]$numerics.mesh.global_auto_level
    WorkingRegionMaximumElementSizeMm = [double]$numerics.mesh.working_region_maximum_element_size_mm
    RfStepsPerPeriod = [int]$numerics.trajectory.rf_steps_per_period
    MaximumTimeUs = [double]$numerics.trajectory.maximum_global_time_us
  }
  if ($EvidenceContractPath) { $arguments.EvidenceContractPath = $EvidenceContractPath }
  & (Join-Path $repoRoot 'common\multipole\run_finite_3d_transport.ps1') @arguments
  if ($LASTEXITCODE -ne 0) { throw 'RF quadrupole COMSOL transport failed.' }
} finally {
  Remove-Item -LiteralPath $resolutionPath -Force -ErrorAction SilentlyContinue
}
