param(
  [int]$N = 5000,
  [int]$Seed = 20260713,
  [int]$TrajectoryQuality = 8,
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [string]$OutputDir = '',
  [switch]$AnalyzeOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
$projectRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $projectRoot 'artifacts\projects\oa_tof'
$formalDir = Join-Path $artifactRoot 'models\simion\workspace\04_workbench\formal'
if (-not $OutputDir) {
  $OutputDir = Join-Path $artifactRoot 'runs\simion_ideal_field_diagnostic\2026-07-14'
}
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$sourceLua = Join-Path $PSScriptRoot 'formal\oatof_ideal_grounded.lua'
$runtimeLua = Join-Path $formalDir 'oatof_ideal_grounded.lua'
$iob = Join-Path $formalDir 'oatof_ideal_grounded.iob'
Copy-Item -LiteralPath $sourceLua -Destination $runtimeLua -Force
$geometryGate = Join-Path $repoRoot 'projects\oa_tof\tests\cross_solver\verify_geometry_contract.ps1'
& $geometryGate -SimionExe $SimionExe | ForEach-Object { Write-Host $_ }

$generator = Join-Path $PSScriptRoot 'generate_comsol_consistent_ions.ps1'
$analyzer = Join-Path $PSScriptRoot 'analyze_ideal_field_log.ps1'
$distributions = @(
  @{ Name='all';         HX=0.5; HY=0.5; HZ=0.5; ES=0.4 },
  @{ Name='z_only';      HX=0.0; HY=0.0; HZ=0.5; ES=0.0 },
  @{ Name='xy_only';     HX=0.5; HY=0.5; HZ=0.0; ES=0.0 },
  @{ Name='energy_only'; HX=0.0; HY=0.0; HZ=0.0; ES=0.4 }
)
$modes = @(
  @{ Name='actual';            A=0; S1=0; S2=0 },
  @{ Name='ideal_accel';       A=1; S1=0; S2=0 },
  @{ Name='ideal_stage1';      A=0; S1=1; S2=0 },
  @{ Name='ideal_stage2';      A=0; S1=0; S2=1 },
  @{ Name='ideal_reflectron';  A=0; S1=1; S2=1 },
  @{ Name='ideal_all';         A=1; S1=1; S2=1 }
)

$ionFiles = @{}
foreach ($d in $distributions) {
  $ion = Join-Path $OutputDir ("ions_{0}_N{1}.ion" -f $d.Name,$N)
  & $generator -N $N -Seed $Seed -HalfWidthXmm $d.HX -HalfWidthYmm $d.HY -HalfWidthZmm $d.HZ -EnergyStdEv $d.ES -Output $ion | Out-Null
  $ionFiles[$d.Name] = $ion
}

$summaries = [Collections.Generic.List[object]]::new()
foreach ($d in $distributions) {
  foreach ($m in $modes) {
    $stem = "{0}__{1}" -f $d.Name,$m.Name
    $stdout = Join-Path $OutputDir ($stem + '.log')
    $stderr = Join-Path $OutputDir ($stem + '.stderr.log')
    $particleCsv = Join-Path $OutputDir ($stem + '_particles.csv')
    $args = @(
      '--default-num-particles', [string]$N,
      '--nogui','fly',
      '--trajectory-quality', [string]$TrajectoryQuality,
      '--particles', $ionFiles[$d.Name],
      '--adjustable', ("trajectory_quality={0}" -f $TrajectoryQuality),
      '--adjustable', ("ideal_accel_enable={0}" -f $m.A),
      '--adjustable', ("ideal_refl_stage1_enable={0}" -f $m.S1),
      '--adjustable', ("ideal_refl_stage2_enable={0}" -f $m.S2),
      '--adjustable', 'trajectory_log_enable=1',
      $iob
    )
    if (-not $AnalyzeOnly) {
      Write-Host ("Running {0} / {1}" -f $d.Name,$m.Name)
      $p = Start-Process -FilePath $SimionExe -ArgumentList $args -WorkingDirectory $formalDir -NoNewWindow -Wait -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
      if ($p.ExitCode -ne 0) { throw "SIMION failed for $stem with exit code $($p.ExitCode); see $stderr" }
    } elseif (-not (Test-Path -LiteralPath $stdout)) {
      throw "AnalyzeOnly requested but log is missing: $stdout"
    }
    $summary = & $analyzer -Log $stdout -IonFile $ionFiles[$d.Name] -Mode $m.Name -Distribution $d.Name -ParticleCsv $particleCsv
    $summaries.Add($summary)
  }
}

$summaryCsv = Join-Path $OutputDir 'ideal_field_matrix_summary.csv'
$summaries | Export-Csv -LiteralPath $summaryCsv -NoTypeInformation -Encoding UTF8
$summaries | Sort-Object Distribution,Mode | Format-Table Distribution,Mode,Hit,EfficiencyPct,MeanTofUs,StdTofNs,FwhmTofNs,ResolutionFwhm,MaxCrossingRadiusMm -AutoSize
Write-Host "Summary: $summaryCsv"
