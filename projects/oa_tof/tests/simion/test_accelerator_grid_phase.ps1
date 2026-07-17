param(
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [string]$RunId = '2026-07-17_eps0030',
  [string]$ModelRunId = '2026-07-17',
  [double]$IdealGridEpsilonMm = 0.03,
  [switch]$ReuseExisting,
  [switch]$ForceFlights
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$projectRoot = Join-Path $repoRoot 'projects\oa_tof'
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\oa_tof'
$formalDir = Join-Path $artifactRoot 'models\simion\formal\oatof_524amu'
$modelScratch = Join-Path $artifactRoot ("scratch\simion\accelerator_grid_phase\{0}" -f $ModelRunId)
$runDir = Join-Path $artifactRoot ("runs\accelerator_grid_phase\{0}" -f $RunId)
$resultDir = Join-Path $artifactRoot ("results\reference_analysis\accelerator_grid_phase_{0}" -f $RunId)
$workbenchDir = Join-Path $modelScratch 'workbench'
$builder = Join-Path $projectRoot 'simion\accelerator\build_accelerator_variant.lua'
$gem = Join-Path $projectRoot 'simion\accelerator\oatof_accelerator_3d.gem'
$program = Join-Path $projectRoot 'simion\workbench\formal\oatof_ideal_grounded.lua'
$fieldExporter = Join-Path $PSScriptRoot 'export_accelerator_grid_phase_field.lua'
$logAnalyzer = Join-Path $projectRoot 'simion\workbench\analyze_ideal_field_log.ps1'
$pythonAnalyzer = Join-Path $projectRoot 'analysis\analyze_accelerator_grid_phase.py'
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
$fixedN100 = Join-Path $formalDir 'oatof_comsol_524amu_gaussian_N100.ion'

foreach ($path in @($SimionExe,$builder,$gem,$program,$fieldExporter,$logAnalyzer,$pythonAnalyzer,$pythonExe,$fixedN100)) {
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required file is missing: $path" }
}
New-Item -ItemType Directory -Force -Path $modelScratch,$runDir,$resultDir,$workbenchDir | Out-Null
foreach ($extension in @('iob','con','fly2')) {
  Copy-Item -LiteralPath (Join-Path $formalDir ("oatof_ideal_grounded.{0}" -f $extension)) -Destination $workbenchDir -Force
}
$runtimeProgram = Join-Path $workbenchDir 'oatof_ideal_grounded.lua'
$programText = Get-Content -LiteralPath $program -Raw -Encoding UTF8
$adjustableNeedle = 'adjustable accelerator_instance_z_mm=-10'
$transformNeedle = ' ai.x,ai.y,ai.z=accelerator_axis_x_mm-half_x,accelerator_axis_y_mm-half_y,accelerator_instance_z_mm'
if (-not $programText.Contains($adjustableNeedle) -or -not $programText.Contains($transformNeedle)) {
  throw 'Formal Program no longer matches the grid-phase diagnostic patch contract.'
}
$programText = $programText.Replace($adjustableNeedle, @'
adjustable accelerator_instance_z_mm=-10
adjustable accelerator_pa_back_margin_mm=0
adjustable accelerator_pa_grid_phase_z_mm=0
'@.TrimEnd())
$programText = $programText.Replace($transformNeedle, @'
 assert(accelerator_pa_back_margin_mm>=0,
   'accelerator PA back margin must be nonnegative')
 assert(accelerator_pa_grid_phase_z_mm>=0 and
        accelerator_pa_grid_phase_z_mm<ai.pa.dz_mm,
   'accelerator PA grid phase must be in [0,dz)')
 ai.x,ai.y,ai.z=accelerator_axis_x_mm-half_x,accelerator_axis_y_mm-half_y,
   accelerator_instance_z_mm-accelerator_pa_back_margin_mm-
   accelerator_pa_grid_phase_z_mm
'@.TrimEnd())
Set-Content -LiteralPath $runtimeProgram -Value $programText -Encoding UTF8
# The copied IOB uses package-relative PA names.  Copy only the arrays needed
# for initial loading and the non-accelerator Fast Adjust operations; the tested
# accelerator is loaded from its case directory through the explicit override.
Copy-Item -LiteralPath (Join-Path $formalDir 'accelerator.pa0') -Destination $workbenchDir -Force
foreach ($pattern in @('reflectron.pa*','flight_tube_ground.pa*','detector_ground.pa*')) {
  Copy-Item -Path (Join-Path $formalDir $pattern) -Destination $workbenchDir -Force
}
$candidateIob = Join-Path $workbenchDir 'oatof_ideal_grounded.iob'
$fieldIob = Join-Path $formalDir 'oatof_ideal_grounded.iob'
$singleIon = Join-Path $runDir 'fixed_single_particle.ion'
Get-Content -LiteralPath $fixedN100 -TotalCount 1 | Set-Content -LiteralPath $singleIon -Encoding ascii

$cases = @(
  [pscustomobject]@{ Name='formal_crop_p0000'; Phase=0.0;    Back=0.0; Front=0.0; Build=$false; Pa=(Join-Path $formalDir 'accelerator.pa0') },
  [pscustomobject]@{ Name='expanded_p0000';    Phase=0.0;    Back=0.2; Front=0.2; Build=$true;  Pa='' },
  [pscustomobject]@{ Name='expanded_p0125';    Phase=0.0125; Back=0.2; Front=0.2; Build=$true;  Pa='' },
  [pscustomobject]@{ Name='expanded_p0250';    Phase=0.025;  Back=0.2; Front=0.2; Build=$true;  Pa='' },
  [pscustomobject]@{ Name='expanded_p0375';    Phase=0.0375; Back=0.2; Front=0.2; Build=$true;  Pa='' }
)

function Invoke-SimionProcess([string[]]$Arguments,[string]$WorkingDirectory,[string]$Stdout,[string]$Stderr) {
  $process = Start-Process -FilePath $SimionExe -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory `
    -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr
  if ($process.ExitCode -ne 0) { throw "SIMION failed with exit code $($process.ExitCode); see $Stderr" }
}

$manifestCases = [Collections.Generic.List[object]]::new()
foreach ($case in $cases) {
  $caseModelDir = Join-Path $modelScratch $case.Name
  $caseRunDir = Join-Path $runDir $case.Name
  New-Item -ItemType Directory -Force -Path $caseModelDir,$caseRunDir | Out-Null
  if ($case.Build) {
    $paSharp = Join-Path $caseModelDir 'accelerator.pa#'
    $case.Pa = Join-Path $caseModelDir 'accelerator.pa0'
    if (-not $ReuseExisting -or -not (Test-Path -LiteralPath $case.Pa)) {
      Write-Host ("Building {0}: phase={1} mm, margins=({2},{3}) mm" -f $case.Name,$case.Phase,$case.Back,$case.Front)
      Invoke-SimionProcess @('--nogui','lua',$builder,$gem,$paSharp,'0.25','0.05','5','5','5','5','4','0','3.5',
        ([string]$case.Back),([string]$case.Front),([string]$case.Phase)) $caseModelDir `
        (Join-Path $caseRunDir 'build.log') (Join-Path $caseRunDir 'build.stderr.log')
    }
  }
  if (-not (Test-Path -LiteralPath $case.Pa -PathType Leaf)) { throw "Candidate PA is missing: $($case.Pa)" }

  $oldOverride = $env:OATOF_ACCELERATOR_PA_OVERRIDE
  $oldBack = $env:OATOF_ACCELERATOR_PA_BACK_MARGIN_MM
  $oldPhase = $env:OATOF_ACCELERATOR_PA_GRID_PHASE_Z_MM
  try {
    $env:OATOF_ACCELERATOR_PA_OVERRIDE = $case.Pa
    $env:OATOF_ACCELERATOR_PA_BACK_MARGIN_MM = [string]$case.Back
    $env:OATOF_ACCELERATOR_PA_GRID_PHASE_Z_MM = [string]$case.Phase
    $fieldCsv = Join-Path $caseRunDir 'axis_field.csv'
    $env:OATOF_FORMAL_IOB_PATH = $fieldIob
    $env:OATOF_SIMION_FIELD_CSV = $fieldCsv
    Invoke-SimionProcess @('--nogui','lua',$fieldExporter) $workbenchDir `
      (Join-Path $caseRunDir 'field.log') (Join-Path $caseRunDir 'field.stderr.log')

    foreach ($run in @(
      [pscustomobject]@{ Name='single'; N=1; Ion=$singleIon },
      [pscustomobject]@{ Name='fixedN100'; N=100; Ion=$fixedN100 }
    )) {
      $stdout = Join-Path $caseRunDir ($run.Name + '.log')
      $stderr = Join-Path $caseRunDir ($run.Name + '.stderr.log')
      $particleCsv = Join-Path $caseRunDir ($run.Name + '_particles.csv')
      if ($ForceFlights -or -not $ReuseExisting -or -not (Test-Path -LiteralPath $particleCsv)) {
        Write-Host ("Flying {0} / {1}" -f $case.Name,$run.Name)
        $args = @('--nogui','fly','--trajectory-quality','8','--retain-trajectories','0','--particles',$run.Ion,
          '--adjustable','trajectory_quality=8','--adjustable','trajectory_log_enable=1',
          '--adjustable','accelerator_fast_adjust_enable=0',
          '--adjustable',("ideal_grid_epsilon_mm={0}" -f $IdealGridEpsilonMm),
          '--adjustable',("accelerator_pa_back_margin_mm={0}" -f $case.Back),
          '--adjustable',("accelerator_pa_grid_phase_z_mm={0}" -f $case.Phase),$candidateIob)
        if ($run.N -gt 1) {
          $args = @('--default-num-particles',[string]$run.N) + $args
        }
        Invoke-SimionProcess $args $workbenchDir $stdout $stderr
        & $logAnalyzer -Log $stdout -IonFile $run.Ion -Mode $case.Name -Distribution $run.Name -ParticleCsv $particleCsv | Out-Null
      }
    }
  } finally {
    $env:OATOF_ACCELERATOR_PA_OVERRIDE = $oldOverride
    $env:OATOF_ACCELERATOR_PA_BACK_MARGIN_MM = $oldBack
    $env:OATOF_ACCELERATOR_PA_GRID_PHASE_Z_MM = $oldPhase
  }
  $manifestCases.Add([pscustomobject]@{
    name=$case.Name; phase_mm=$case.Phase; back_margin_mm=$case.Back; front_margin_mm=$case.Front
    pa_path=$case.Pa
    particle_csv=(Join-Path $caseRunDir 'fixedN100_particles.csv')
    single_particle_csv=(Join-Path $caseRunDir 'single_particles.csv')
    field_csv=(Join-Path $caseRunDir 'axis_field.csv')
  })
}

$manifest = [pscustomobject]@{
  schema_version=1
  ideal_grid_epsilon_mm=$IdealGridEpsilonMm
  cases=$manifestCases
}
$manifestPath = Join-Path $runDir 'grid_phase_manifest.json'
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding utf8
& $pythonExe $pythonAnalyzer $manifestPath --output $resultDir
if ($LASTEXITCODE -ne 0) { throw "Grid-phase Python analysis failed with exit code $LASTEXITCODE" }
Write-Host "GRID_PHASE_DIAGNOSTIC_STATUS=PASS"
Write-Host "Manifest: $manifestPath"
Write-Host "Results: $resultDir"
