param(
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [string]$RunId = '2026-07-17_strict_focus',
  [switch]$ReuseExisting
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\oa_tof'
$formalDir = Join-Path $artifactRoot 'models\simion\formal\oatof_524amu'
$scratchDir = Join-Path $artifactRoot "scratch\simion\accelerator_geometry_candidate\$RunId"
$runDir = Join-Path $artifactRoot "runs\accelerator_geometry_candidate\$RunId"
$resultDir = Join-Path $artifactRoot "results\simion\accelerator_geometry_candidate\$RunId"
$contractPath = Join-Path $projectRoot 'config\candidates\accelerator_grid_aligned_strict_focus.json'
$derivedPath = Join-Path $runDir 'derived_geometry.json'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$theory = Join-Path $projectRoot 'analysis\accelerator_time_focus.py'
$builder = Join-Path $projectRoot 'simion\accelerator\build_accelerator_variant.lua'
$gem = Join-Path $projectRoot 'simion\accelerator\oatof_accelerator_3d.gem'
$program = Join-Path $projectRoot 'simion\workbench\formal\oatof_ideal_grounded.lua'
$fly2 = Join-Path $projectRoot 'simion\workbench\formal\oatof_ideal_grounded.fly2'
$iobBuilder = Join-Path $projectRoot 'simion\workbench\build_formal_iob.lua'
$ionGenerator = Join-Path $projectRoot 'simion\workbench\generate_comsol_consistent_ions.ps1'
$logAnalyzer = Join-Path $projectRoot 'simion\workbench\analyze_ideal_field_log.ps1'

New-Item -ItemType Directory -Force -Path $scratchDir,$runDir,$resultDir | Out-Null
& $python $theory $contractPath --write-derived $derivedPath | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Accelerator focus derivation failed.' }
$derived = Get-Content -LiteralPath $derivedPath -Raw -Encoding UTF8 | ConvertFrom-Json
$contract = Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8 | ConvertFrom-Json
$translation = [double]$derived.assembly_translation_z_mm
$d1 = [double]$derived.d1_mm
$d2 = [double]$derived.d2_mm
$repellerZ = [double]$derived.repeller_global_z_mm
$grid1Z = [double]$derived.grid1_global_z_mm
$grid2Z = [double]$derived.grid2_global_z_mm
$instanceZ = -10.0 + $translation
$sourceCenterZ = 1.5 + $translation

$smokeIob = Join-Path $scratchDir 'strict_focus_runtime.iob'
Copy-Item -LiteralPath (Join-Path $formalDir 'oatof_ideal_grounded.iob') -Destination $smokeIob -Force
$candidateProgram = Get-Content -LiteralPath $program -Raw -Encoding UTF8
$candidateDefaults = [ordered]@{
  'accelerator_assembly_translation_z_mm=0' = ('accelerator_assembly_translation_z_mm={0:R}' -f $translation)
  'accelerator_stage1_length_mm=3' = ('accelerator_stage1_length_mm={0:R}' -f $d1)
  'accelerator_stage2_length_mm=16.83' = ('accelerator_stage2_length_mm={0:R}' -f $d2)
  'accelerator_repeller_front_z_mm=0' = ('accelerator_repeller_front_z_mm={0:R}' -f $repellerZ)
  'accelerator_grid1_z_mm=3' = ('accelerator_grid1_z_mm={0:R}' -f $grid1Z)
  'accelerator_grid2_z_mm=19.83' = ('accelerator_grid2_z_mm={0:R}' -f $grid2Z)
  'accelerator_instance_z_mm=-10' = ('accelerator_instance_z_mm={0:R}' -f $instanceZ)
}
foreach ($entry in $candidateDefaults.GetEnumerator()) {
  $needle = 'adjustable ' + $entry.Key
  if (-not $candidateProgram.Contains($needle)) { throw "Candidate Program default is absent: $needle" }
  $candidateProgram = $candidateProgram.Replace($needle, 'adjustable ' + $entry.Value)
}
Set-Content -LiteralPath (Join-Path $scratchDir 'strict_focus_runtime.lua') -Value $candidateProgram -Encoding UTF8
Copy-Item -LiteralPath $fly2 -Destination (Join-Path $scratchDir 'strict_focus_runtime.fly2') -Force

function Invoke-Simion([string[]]$Arguments,[string]$Stdout,[string]$Stderr) {
  $process = Start-Process -FilePath $SimionExe -ArgumentList $Arguments -WorkingDirectory $scratchDir `
    -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr
  if ($process.ExitCode -ne 0) { throw "SIMION failed with exit code $($process.ExitCode); see $Stderr" }
}

$candidatePaSharp = Join-Path $scratchDir 'accelerator.pa#'
$candidatePa0 = Join-Path $scratchDir 'accelerator.pa0'
if (-not $ReuseExisting -or -not (Test-Path -LiteralPath $candidatePa0 -PathType Leaf)) {
  Invoke-Simion @('--nogui','lua',$builder,$gem,$candidatePaSharp,
    '0.25','0.05','5','5','5','5','4','0','3.5','0','0','0',
    ([string]$d1),([string]$d2)) (Join-Path $runDir 'build.log') (Join-Path $runDir 'build.stderr.log')
}
if (-not (Test-Path -LiteralPath $candidatePa0 -PathType Leaf)) { throw 'Candidate accelerator PA0 is absent.' }

foreach ($pattern in @('oatof_ideal_grounded.iob','reflectron.pa*',
    'flight_tube_ground.pa*','detector_ground.pa*')) {
  Copy-Item -Path (Join-Path $formalDir $pattern) -Destination $scratchDir -Force
}
$candidateIob = Join-Path $scratchDir 'strict_focus_candidate.iob'
$oldBuildEnvironment = @{}
$buildEnvironment = @{
  OATOF_FOUR_INSTANCE_TEMPLATE_IOB = $smokeIob
  OATOF_FORMAL_IOB_OUTPUT = $candidateIob
  OATOF_FORMAL_PA_DIR = $scratchDir
  OATOF_FORMAL_PROGRAM_SOURCE = Join-Path $scratchDir 'strict_focus_runtime.lua'
  OATOF_FORMAL_FLY2_SOURCE = $fly2
  OATOF_ACCELERATOR_TRANSLATION_Z = [string]$translation
}
try {
  foreach ($item in $buildEnvironment.GetEnumerator()) {
    $oldBuildEnvironment[$item.Key] = [Environment]::GetEnvironmentVariable($item.Key, 'Process')
    [Environment]::SetEnvironmentVariable($item.Key, $item.Value, 'Process')
  }
  Invoke-Simion @('--nogui','lua',$iobBuilder) (Join-Path $runDir 'iob_build.log') (Join-Path $runDir 'iob_build.stderr.log')
} finally {
  foreach ($item in $buildEnvironment.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($item.Key, $oldBuildEnvironment[$item.Key], 'Process')
  }
}
$ionPath = Join-Path $runDir 'candidate_fixedN100.ion'
& $ionGenerator -N 100 -MassAmu 524 -Charge 1 -EnergyMeanEv 5 -EnergyStdEv 0.4 `
  -HalfWidthMm 0.5 -CenterZmm $sourceCenterZ -Seed 20260713 -Output $ionPath | Out-Null

$oldOverride = $env:OATOF_ACCELERATOR_PA_OVERRIDE
try {
  $env:OATOF_ACCELERATOR_PA_OVERRIDE = $candidatePa0
  $stdout = Join-Path $runDir 'fixedN100.log'
  $stderr = Join-Path $runDir 'fixedN100.stderr.log'
  $particleCsv = Join-Path $runDir 'fixedN100_particles.csv'
  $args = @('--default-num-particles','100','--nogui','fly','--trajectory-quality','8',
    '--retain-trajectories','0','--particles',$ionPath,
    '--adjustable','trajectory_quality=8','--adjustable','trajectory_log_enable=1',
    '--adjustable','accelerator_fast_adjust_enable=0',
    '--adjustable',("accelerator_repeller_front_z_mm={0:R}" -f $repellerZ),
    '--adjustable',("accelerator_grid1_z_mm={0:R}" -f $grid1Z),
    '--adjustable',("accelerator_grid2_z_mm={0:R}" -f $grid2Z),
    '--adjustable',("accelerator_instance_z_mm={0:R}" -f $instanceZ),$candidateIob)
  Invoke-Simion $args $stdout $stderr
  $summary = & $logAnalyzer -Log $stdout -IonFile $ionPath -Mode 'strict_focus_geometry_candidate' `
    -Distribution 'fixedN100' -ParticleCsv $particleCsv
  if ($LASTEXITCODE -ne 0) { throw 'Candidate log analysis failed.' }
  $summary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $resultDir 'summary.json') -Encoding UTF8
  if ([int]$summary.Hit -ne 100) { throw "Candidate hit count is $($summary.Hit), expected 100." }
} finally {
  $env:OATOF_ACCELERATOR_PA_OVERRIDE = $oldOverride
}

[pscustomobject]@{
  status='PASS'; contract=$contractPath; derived=$derivedPath; candidate_pa0=$candidatePa0
  validation_scope='candidate PA, persisted four-instance IOB, candidate Program, fixed detector plane, and fixed N=100 full-flight validation'
  translation_z_mm=$translation; grid2_global_z_mm=$grid2Z
  reference_focus_global_z_mm=[double]$derived.reference_global_focus_z_mm
  candidate_focus_global_z_mm=[double]$derived.focus_global_z_mm
  particle_csv=(Join-Path $runDir 'fixedN100_particles.csv')
  summary=(Join-Path $resultDir 'summary.json')
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $resultDir 'manifest.json') -Encoding UTF8

Write-Host 'SIMION_ACCELERATOR_GEOMETRY_CANDIDATE_STATUS=PASS'
Write-Host "Results: $resultDir"
