param(
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [string]$RunId = '',
  [switch]$ReuseExisting
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\oa_tof'
$formalDir = Join-Path $artifactRoot 'formal\simion'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__test__simion__accelerator-geometry__strict-focus'
}
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $RunId" }
$runDir = Join-Path $artifactRoot "runs\$RunId"
$scratchDir = Join-Path $runDir 'runtime'
$resultDir = Join-Path $runDir 'results'
$logDir = Join-Path $runDir 'logs'
$contractPath = Join-Path $projectRoot 'config\candidates\accelerator_grid_aligned_strict_focus.json'
$baselinePath = Join-Path $projectRoot 'config\resolved_geometry.json'
$derivedPath = Join-Path $resultDir 'derived_geometry.json'
$theory = Join-Path $projectRoot 'analysis\accelerator_time_focus.py'
$builder = Join-Path $projectRoot 'simion\accelerator\build_accelerator_variant.lua'
$gem = Join-Path $projectRoot 'simion\accelerator\oatof_accelerator_3d.gem'
$program = Join-Path $projectRoot 'simion\workbench\formal\oatof_ideal_grounded.lua'
$fly2 = Join-Path $projectRoot 'simion\workbench\formal\oatof_ideal_grounded.fly2'
$iobBuilder = Join-Path $projectRoot 'simion\workbench\build_formal_iob.lua'
$ionGenerator = Join-Path $projectRoot 'simion\workbench\generate_comsol_consistent_ions.ps1'
$logAnalyzer = Join-Path $projectRoot 'simion\workbench\analyze_ideal_field_log.ps1'

New-Item -ItemType Directory -Force -Path $scratchDir,$runDir,$resultDir,$logDir | Out-Null
& $python $theory $contractPath --write-derived $derivedPath | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Accelerator focus derivation failed.' }
$derived = Get-Content -LiteralPath $derivedPath -Raw -Encoding UTF8 | ConvertFrom-Json
$candidateContract = Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8 | ConvertFrom-Json
$baseline = Get-Content -LiteralPath $baselinePath -Raw -Encoding UTF8 | ConvertFrom-Json
$translation = [double]$derived.assembly_translation_z_mm
$d1 = [double]$derived.d1_mm
$d2 = [double]$derived.d2_mm
$repellerZ = [double]$derived.repeller_global_z_mm
$grid1Z = [double]$derived.grid1_global_z_mm
$grid2Z = [double]$derived.grid2_global_z_mm
$instanceZ = $translation-$baseline.geometry_mm.accelerator_repeller_thickness-
  $baseline.geometry_mm.accelerator_rear_clearance-$baseline.geometry_mm.accelerator_shield_wall
$sourceCenterZ = $translation+$d1/2

$smokeIob = Join-Path $scratchDir 'strict_focus_runtime.iob'
Copy-Item -LiteralPath (Join-Path $formalDir 'oatof_ideal_grounded.iob') -Destination $smokeIob -Force
$candidateProgram = Get-Content -LiteralPath $program -Raw -Encoding UTF8
function Set-Adjustable([string]$Text, [string]$Name, [double]$Value) {
  $pattern = "(?m)^adjustable\s+$([regex]::Escape($Name))=[-+0-9.eE]+\s*$"
  if (-not [regex]::IsMatch($Text, $pattern)) { throw "Candidate Program adjustable is absent: $Name" }
  return [regex]::Replace($Text, $pattern, ('adjustable {0}={1:R}' -f $Name,$Value), 1)
}
foreach ($entry in ([ordered]@{
  accelerator_assembly_translation_z_mm=$translation
  accelerator_stage1_length_mm=$d1
  accelerator_stage2_length_mm=$d2
  accelerator_repeller_front_z_mm=$repellerZ
  accelerator_grid1_z_mm=$grid1Z
  accelerator_grid2_z_mm=$grid2Z
  accelerator_instance_z_mm=$instanceZ
}).GetEnumerator()) {
  $candidateProgram = Set-Adjustable $candidateProgram $entry.Key ([double]$entry.Value)
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
  $g = $baseline.geometry_mm
  $b = $baseline.simion_geometry_build.accelerator
  Invoke-Simion @('--nogui','lua',$builder,$gem,$candidatePaSharp,
    ([string]$b.cell_xy_mm),([string]$b.cell_z_mm),([string]$g.accelerator_bore_half),
    ([string]$g.accelerator_ring_width),([string]$g.accelerator_insulation_gap),
    ([string]$g.accelerator_rear_clearance),([string]$g.accelerator_shield_wall),
    ([string]$b.vacuum_margin_mm),([string]$b.max_gib),'0','0','0',
    ([string]$d1),([string]$d2),([string]$baseline.rings.accelerator_count),
    ([string]$g.accelerator_repeller_thickness),([string]$g.accelerator_ring_thickness),
    ([string]$g.accelerator_front_vacuum_margin),([string]$baseline.electrodes_V.repeller),
    ([string]$baseline.electrodes_V.grid1)) (Join-Path $runDir 'build.log') (Join-Path $runDir 'build.stderr.log')
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
  Invoke-Simion @('--nogui','lua',$iobBuilder) (Join-Path $logDir 'iob_build.log') (Join-Path $logDir 'iob_build.stderr.log')
} finally {
  foreach ($item in $buildEnvironment.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($item.Key, $oldBuildEnvironment[$item.Key], 'Process')
  }
}
$ionPath = Join-Path $scratchDir 'candidate_fixedN100.ion'
& $ionGenerator -N 100 -MassAmu $baseline.validation_target.mass_amu -Charge 1 `
  -EnergyMeanEv $baseline.validation_target.initial_energy_mean_ev `
  -EnergyStdEv $baseline.validation_target.initial_energy_sigma_ev `
  -HalfWidthXmm ($baseline.particle_source.size_x_mm/2) `
  -HalfWidthYmm ($baseline.particle_source.size_y_mm/2) `
  -HalfWidthZmm ($baseline.particle_source.size_z_mm/2) `
  -CenterXmm $baseline.particle_source.center_x_mm -CenterYmm $baseline.particle_source.center_y_mm `
  -CenterZmm $sourceCenterZ -Seed $baseline.particle_source.seed -Output $ionPath | Out-Null

$oldOverride = $env:OATOF_ACCELERATOR_PA_OVERRIDE
try {
  $env:OATOF_ACCELERATOR_PA_OVERRIDE = $candidatePa0
  $stdout = Join-Path $logDir 'fixedN100.log'
  $stderr = Join-Path $logDir 'fixedN100.stderr.log'
  $particleCsv = Join-Path $resultDir 'fixedN100_particles.csv'
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
  $summary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $resultDir 'solver_summary.json') -Encoding UTF8
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
  particle_csv=(Join-Path $resultDir 'fixedN100_particles.csv')
  summary=(Join-Path $resultDir 'solver_summary.json')
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $resultDir 'manifest.json') -Encoding UTF8

$runConfig = Join-Path $runDir 'run_config.json'
[ordered]@{schema_version=1;run_id=$RunId;project='oa_tof';mode='accelerator_geometry_candidate';project_root=$projectRoot;inputs=[ordered]@{candidate_contract=$contractPath;resolved_geometry=$baselinePath;formal_iob=(Join-Path $formalDir 'oatof_ideal_grounded.iob')};formal_gate_passed=$false;particles=100} |
  ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $runConfig -Encoding UTF8
$runSummary = Join-Path $runDir 'summary.json'
[ordered]@{schema_version=1;role='oa_tof_accelerator_geometry_candidate_summary';status='success';particles=100;results='results/manifest.json'} |
  ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $runSummary -Encoding UTF8
$manifestArgs=@((Join-Path $repoRoot 'common\contracts\write_run_manifest.py'),'--run-config',$runConfig,'--status','success','--software','SIMION 2020','--output',$runSummary)
foreach($file in Get-ChildItem -LiteralPath $resultDir,$logDir,$scratchDir -Recurse -File){$manifestArgs+=@('--output',$file.FullName)}
& $python @manifestArgs
if($LASTEXITCODE -ne 0){throw 'Accelerator-geometry manifest failed.'}

Write-Host 'SIMION_ACCELERATOR_GEOMETRY_CANDIDATE_STATUS=PASS'
Write-Host "Results: $resultDir"
