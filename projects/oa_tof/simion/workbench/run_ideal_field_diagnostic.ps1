param(
  [int]$N = 100,
  [int]$Seed = 20260713,
  [int]$TrajectoryQuality = 8,
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [string]$OutputDir = '',
  [string]$RunId = '',
  [switch]$AnalyzeOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
$projectRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $projectRoot 'artifacts\projects\oa_tof'
$formalDir = Join-Path $artifactRoot 'formal\simion'
if (-not $OutputDir) {
  if (-not $RunId) { $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + "__test__simion__ideal-field-matrix__n${N}" }
  $OutputDir = Join-Path $artifactRoot "runs\$RunId"
}
if (-not $RunId) { $RunId = Split-Path -Leaf $OutputDir }
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $RunId" }
$resultDir = Join-Path $OutputDir 'results'
$logDir = Join-Path $OutputDir 'logs'
$simionDir = Join-Path $OutputDir 'simion'
New-Item -ItemType Directory -Force -Path $OutputDir,$resultDir,$logDir,$simionDir | Out-Null
. (Join-Path $repoRoot 'projects\oa_tof\tests\run_record_helpers.ps1')
Initialize-OaTofRunRecord -RunDir $OutputDir -RunId $RunId `
  -Mode 'simion_ideal_field_matrix' -ProjectRoot (Join-Path $repoRoot 'projects\oa_tof') `
  -RepoRoot $repoRoot -Python $python
$runRecordComplete = $false
trap {
  if (-not $runRecordComplete) {
    Write-OaTofTerminalRunRecord -RunDir $OutputDir -Status failed `
      -Reason $_.Exception.Message -RepoRoot $repoRoot -Python $python
  }
  exit 1
}

$sourceLua = Join-Path $PSScriptRoot 'formal\oatof_ideal_grounded.lua'
$runtimeLua = Join-Path $formalDir 'oatof_ideal_grounded.lua'
$iob = Join-Path $formalDir 'oatof_ideal_grounded.iob'
if ((Get-FileHash $sourceLua -Algorithm SHA256).Hash -ne (Get-FileHash $runtimeLua -Algorithm SHA256).Hash) {
  throw 'Formal SIMION Lua differs from source; rebuild the formal delivery before diagnosis.'
}
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
  $ion = Join-Path $simionDir ("ions_{0}_N{1}.ion" -f $d.Name,$N)
  $generatorArgs = @{}
  if ($N -notin @(100,1000)) { $generatorArgs.AllowNonstandardDiagnosticCount = $true }
  & $generator -N $N -Seed $Seed -HalfWidthXmm $d.HX -HalfWidthYmm $d.HY `
    -HalfWidthZmm $d.HZ -EnergyStdEv $d.ES -Output $ion @generatorArgs | Out-Null
  $ionFiles[$d.Name] = $ion
}

$summaries = [Collections.Generic.List[object]]::new()
foreach ($d in $distributions) {
  foreach ($m in $modes) {
    $stem = "{0}__{1}" -f $d.Name,$m.Name
    $stdout = Join-Path $logDir ($stem + '.log')
    $stderr = Join-Path $logDir ($stem + '.stderr.log')
    $particleCsv = Join-Path $resultDir ($stem + '_particles.csv')
    $args = @(
      '--default-num-particles', [string]$N,
      '--nogui','fly',
      '--trajectory-quality', [string]$TrajectoryQuality,
      '--retain-trajectories','0',
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

$summaryCsv = Join-Path $resultDir 'ideal_field_matrix_summary.csv'
$summaries | Export-Csv -LiteralPath $summaryCsv -NoTypeInformation -Encoding UTF8
$runConfig = Join-Path $OutputDir 'run_config.json'
[ordered]@{schema_version=1;run_id=$RunId;project='oa_tof';mode='simion_ideal_field_matrix';project_root=(Join-Path $repoRoot 'projects\oa_tof');inputs=[ordered]@{formal_iob=$iob};formal_gate_passed=$false;particles=$N;seed=$Seed} |
  ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $runConfig -Encoding UTF8
$summaryPath = Join-Path $OutputDir 'summary.json'
[ordered]@{schema_version=1;role='oa_tof_ideal_field_matrix_summary';status='success';cases=$summaries.Count;results='results/ideal_field_matrix_summary.csv'} |
  ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
$manifestArgs=@((Join-Path $repoRoot 'common\contracts\write_run_manifest.py'),'--run-config',$runConfig,'--status','success','--software','SIMION 2020','--output',$summaryPath)
foreach($file in Get-ChildItem -LiteralPath $resultDir,$logDir,$simionDir -Recurse -File){$manifestArgs+=@('--output',$file.FullName)}
& $python @manifestArgs
if($LASTEXITCODE -ne 0){throw 'Ideal-field diagnostic manifest failed.'}
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') `
  (Join-Path $OutputDir 'run_manifest.json') --require-status success
if($LASTEXITCODE -ne 0){throw 'Ideal-field diagnostic manifest verification failed.'}
$runRecordComplete = $true
$summaries | Sort-Object Distribution,Mode | Format-Table Distribution,Mode,Hit,EfficiencyPct,MeanTofUs,StdTofNs,FwhmTofNs,ResolutionFwhm,MaxCrossingRadiusMm -AutoSize
Write-Host "Summary: $summaryCsv"
