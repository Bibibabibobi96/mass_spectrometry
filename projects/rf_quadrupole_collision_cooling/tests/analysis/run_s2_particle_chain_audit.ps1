param(
  [string]$SourceRunId = '20260722_150059__sim__comsol__rf-oatof-s2-passive-connector__n100__r02',
  [string]$RunId = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$supportSource = (Resolve-Path (Join-Path $projectRoot 'tests\support\rf_run_artifact_support.ps1')).Path
. $supportSource
$sourceRun = Join-Path (Join-Path $artifactRoot 'runs') $SourceRunId
$sourceManifest = Join-Path $sourceRun 'run_manifest.json'
$sourceParticles = Join-Path $sourceRun 'inputs\canonical_rf_exit_at_s2_connector.csv'
$sourceEvents = Join-Path $sourceRun 'results\s2_passive_connector_particles.csv'
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__analysis__python__rf-oatof-s2-particle-chain__n100'
}
$software = @('Python 3.11')
$package = New-RfRunPackage -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunId $RunId -Project 'rf_quadrupole_collision_cooling' `
  -Mode 'rf_to_oatof_s2_particle_chain_audit' -Software $software

try {
  & $package.python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') `
    $sourceManifest --require-status success
  if ($LASTEXITCODE -ne 0) { throw 'The S2 particle source run manifest is invalid.' }
  $analysis = Join-Path $package.input_dir 'audit_s2_particle_chain.py'
  $contract = Join-Path $package.input_dir 'rf_to_oatof_s2_passive_connector.json'
  $runner = Join-Path $package.input_dir 'run_s2_particle_chain_audit.ps1.txt'
  $support = Join-Path $package.input_dir 'rf_run_artifact_support.ps1.txt'
  Copy-Item -LiteralPath (Join-Path $projectRoot 'analysis\audit_s2_particle_chain.py') -Destination $analysis
  Copy-Item -LiteralPath (Join-Path $projectRoot 'config\rf_to_oatof_s2_passive_connector.json') -Destination $contract
  Copy-Item -LiteralPath $PSCommandPath -Destination $runner
  Copy-Item -LiteralPath $supportSource -Destination $support
  $auditOutput = Join-Path $package.result_dir 's2_particle_chain_audit.json'
  $runConfiguration = [ordered]@{
    schema_version = 1
    run_id = $RunId
    project = 'rf_quadrupole_collision_cooling'
    mode = 'rf_to_oatof_s2_particle_chain_audit'
    project_root = $repoRoot
    inputs = [ordered]@{
      analysis = $analysis
      contract = $contract
      runner = $runner
      run_artifact_support = $support
      source_run_manifest = $sourceManifest
      source_particles = $sourceParticles
      source_events = $sourceEvents
    }
    parameters = [ordered]@{
      source_run_id = $SourceRunId
      solver_rerun = $false
      particle_count = 100
    }
    formal_gate_passed = $false
  }
  Write-RfJson -Path $package.run_config -Depth 7 -Value $runConfiguration
  Write-RfJson -Path $package.summary -Value ([ordered]@{
    schema_version = 1
    role = 'rf_to_oatof_s2_particle_chain_audit_summary'
    status = 'interrupted'
    reason = 'Run package initialized; final status not yet recorded.'
  })
  Write-RfRunManifest -Python $package.python -RepoRoot $repoRoot `
    -RunConfig $package.run_config -Status interrupted -Software $software
  & $package.python $analysis --source $sourceParticles --events $sourceEvents `
    --contract $contract --output $auditOutput
  if ($LASTEXITCODE -ne 0) { throw 'S2 particle-chain audit failed.' }
  $audit = Get-Content -LiteralPath $auditOutput -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($audit.status -ne 'PASS' -or [int]$audit.particles -ne 100 -or
      [int]$audit.oatof_entry_crossings -lt 1) {
    throw 'S2 particle-chain audit output violates the functional contract.'
  }
  Write-RfJson -Path $package.summary -Value ([ordered]@{
    schema_version = 1
    role = 'rf_to_oatof_s2_particle_chain_audit_summary'
    status = 'success'
    source_run_id = $SourceRunId
    result = 'results/s2_particle_chain_audit.json'
    particles = [int]$audit.particles
    oatof_entry_crossings = [int]$audit.oatof_entry_crossings
    downstream_entry_wall_losses = [int]$audit.downstream_entry_wall_losses
    solver_rerun = $false
    s2_stage_passed = $false
    formal_gate_passed = $false
  })
  Write-RfRunManifest -Python $package.python -RepoRoot $repoRoot `
    -RunConfig $package.run_config -Status success -Software $software `
    -Outputs @($auditOutput,$package.summary)
  Write-Output "STATUS=PASS RUN_ID=$RunId ENTRY=$($audit.oatof_entry_crossings) WALL_LOSS=$($audit.downstream_entry_wall_losses)"
} catch {
  Complete-RfFailedRun -Python $package.python -RepoRoot $repoRoot `
    -RunConfig $package.run_config -Summary $package.summary `
    -SummaryRole 'rf_to_oatof_s2_particle_chain_audit_summary' `
    -Reason $_.Exception.Message -Software $software
  throw
}
