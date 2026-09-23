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
$hostRole = 'SIMION' # AnalyzeOnly still performs the runtime geometry gate.
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
$hostExecutionLease = Enter-HostExecutionLease -Role $hostRole -Stage prepare
try {
$projectRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $projectRoot 'artifacts\projects\single_reflection_oa_tof_mass_analyzer'
$formalDir = Join-Path $artifactRoot 'formal\simion'
$componentRoot = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer'
. (Join-Path $componentRoot 'oatof_lifecycle_preflight.ps1')
if (-not $RunId) {
  if ($OutputDir) { $RunId = Split-Path -Leaf ([IO.Path]::GetFullPath($OutputDir)) }
  else { $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + "__test__simion__ideal-field-matrix__n${N}" }
}
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $RunId" }
$expectedOutputDir = [IO.Path]::GetFullPath((Join-Path $artifactRoot "runs\$RunId"))
if ($OutputDir -and [IO.Path]::GetFullPath($OutputDir) -cne $expectedOutputDir) {
  throw 'OutputDir must be the canonical artifacts/runs/RunId directory.'
}
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$runRecordComplete = $false
$package = New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunId $RunId -Project 'single_reflection_oa_tof_mass_analyzer' -Mode 'simion_ideal_field_matrix' `
  -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass solver_review `
  -RetentionReason 'Public ideal-field diagnostic workbench evidence requires review.' `
  -CapacityLedgerLifecycleEnabled -AdditionalDirectories @('simion')
$OutputDir = $package.artifact_run_dir
$inputDir = $package.input_dir
$artifactResultDir = $package.result_dir
$artifactLogDir = $package.log_dir
$artifactSimionDir = Join-Path $OutputDir 'simion'
$lifecycleConfig = Get-Content -LiteralPath $package.run_config -Raw -Encoding UTF8 | ConvertFrom-Json
$executionAlias = $null
$runtimeRoot = $null
$runtimeAlias = $null
trap {
  if (-not $runRecordComplete) {
    Write-TerminalRunRecord -RunDir $OutputDir -Status failed `
      -Reason $_.Exception.Message -RepoRoot $repoRoot -Python $python `
      -SummaryRole 'oa_tof_terminal_run_summary'
  }
  if ($null -ne $runtimeAlias) {
    try { Remove-RunExecutionAlias -ExecutionAlias $runtimeAlias.execution_alias -TargetDirectory $runtimeRoot }
    catch { Write-Warning "Could not remove short formal-runtime alias: $($_.Exception.Message)" }
  }
  if ($null -ne $runtimeRoot) {
    try { Remove-OaTofFormalSimionRuntime -ArtifactRoot $artifactRoot -RuntimeRoot $runtimeRoot }
    catch { Write-Warning "Could not remove formal SIMION runtime: $($_.Exception.Message)" }
  }
  if ($null -ne $executionAlias) {
    try { Remove-RunExecutionAlias -ExecutionAlias $executionAlias.execution_alias -TargetDirectory $OutputDir }
    catch { Write-Warning "Could not remove short diagnostic execution alias: $($_.Exception.Message)" }
  }
  exit 1
}
$executionAlias = New-RunExecutionAlias -TargetDirectory $OutputDir `
  -AdditionalDirectories @('results','logs','simion') `
  -ExpectedExecutionRelativePaths @('logs/energy_only__ideal_reflectron.stderr.log','simion/ions_energy_only_N1000000.ion')
$executionOutputDir = [string]$executionAlias.execution_alias
$resultDir = Join-Path $executionOutputDir 'results'
$logDir = Join-Path $executionOutputDir 'logs'
$simionDir = Join-Path $executionOutputDir 'simion'

$sourceLua = Join-Path $PSScriptRoot 'formal\oatof_ideal_grounded.lua'
$runtimeLua = Join-Path $formalDir 'oatof_ideal_grounded.lua'
$formalIob = Join-Path $formalDir 'oatof_ideal_grounded.iob'
$iob = $formalIob
if ((Get-FileHash $sourceLua -Algorithm SHA256).Hash -ne (Get-FileHash $runtimeLua -Algorithm SHA256).Hash) {
  throw 'Formal SIMION Lua differs from source; rebuild the formal delivery before diagnosis.'
}
$geometryGate = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\workflows\formal_reference\verify_geometry_contract.ps1'
& $geometryGate -SimionExe $SimionExe | ForEach-Object { Write-Host $_ }
$runtimeReceipt = Join-Path $inputDir 'formal_simion_runtime_receipt.json'
if (-not $AnalyzeOnly) {
  $runtimeTaskId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__simion__ideal-field-runtime'
  $runtimeRoot = New-OaTofFormalSimionRuntime -ProjectRoot $componentRoot `
    -ArtifactRoot $artifactRoot -PythonExe $python `
    -Destination (Join-Path $artifactRoot "scratch\$runtimeTaskId") `
    -Receipt $runtimeReceipt
  $runtimeAlias = New-RunExecutionAlias -TargetDirectory $runtimeRoot `
    -ExpectedExecutionRelativePaths @('oatof_ideal_grounded.iob')
  $iob = Join-Path $runtimeAlias.execution_alias 'oatof_ideal_grounded.iob'
}

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
try {
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
      $hostExecutionLease = Update-HostResourceStage -Lease $hostExecutionLease -Stage flight `
        -Budget (Get-HostResourceBudget -Role $hostRole -Stage flight) -RetainedMemoryBytes 0
      $p = Start-Process -FilePath $SimionExe -ArgumentList $args -WorkingDirectory $runtimeAlias.execution_alias -NoNewWindow -Wait -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
      if ($p.ExitCode -ne 0) { throw "SIMION failed for $stem with exit code $($p.ExitCode); see $stderr" }
    } elseif (-not (Test-Path -LiteralPath $stdout)) {
      throw "AnalyzeOnly requested but log is missing: $stdout"
    }
    if (-not $AnalyzeOnly) {
      $hostExecutionLease = Update-HostResourceStage -Lease $hostExecutionLease -Stage postprocess `
        -Budget (Get-HostResourceBudget -Role $hostRole -Stage postprocess) -RetainedMemoryBytes 0
    }
    $summary = & $analyzer -Log $stdout -IonFile $ionFiles[$d.Name] -Mode $m.Name -Distribution $d.Name -ParticleCsv $particleCsv
    $summaries.Add($summary)
    }
  }
} finally {
  if ($null -ne $runtimeAlias) {
    try { Remove-RunExecutionAlias -ExecutionAlias $runtimeAlias.execution_alias -TargetDirectory $runtimeRoot }
    catch { Write-Warning "Could not remove short formal-runtime alias: $($_.Exception.Message)" }
    $runtimeAlias = $null
  }
  if ($null -ne $runtimeRoot) {
    try { Remove-OaTofFormalSimionRuntime -ArtifactRoot $artifactRoot -RuntimeRoot $runtimeRoot }
    catch { Write-Warning "Could not remove formal SIMION runtime: $($_.Exception.Message)" }
    $runtimeRoot = $null
  }
}

$summaryCsv = Join-Path $resultDir 'ideal_field_matrix_summary.csv'
$summaries | Export-Csv -LiteralPath $summaryCsv -NoTypeInformation -Encoding UTF8
$runConfig = Join-Path $OutputDir 'run_config.json'
[ordered]@{schema_version=2;run_id=$RunId;project='single_reflection_oa_tof_mass_analyzer';mode='simion_ideal_field_matrix';project_root=(Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer');artifact_retention=$($lifecycleConfig.artifact_retention);capacity_ledger_lifecycle=$($lifecycleConfig.capacity_ledger_lifecycle);inputs=[ordered]@{formal_iob=$formalIob;formal_simion_runtime_receipt=$runtimeReceipt};formal_gate_passed=$false;particles=$N;seed=$Seed} |
  ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $runConfig -Encoding UTF8
$summaryPath = Join-Path $OutputDir 'summary.json'
[ordered]@{schema_version=1;role='oa_tof_ideal_field_matrix_summary';status='success';cases=$summaries.Count;results='results/ideal_field_matrix_summary.csv'} |
  ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
$manifestArgs=@((Join-Path $repoRoot 'common\contracts\write_run_manifest.py'),'--run-config',$runConfig,'--status','success','--software','SIMION 2020','--output',$summaryPath)
foreach($file in Get-ChildItem -LiteralPath $artifactResultDir,$artifactLogDir,$artifactSimionDir -Recurse -File){$manifestArgs+=@('--output',$file.FullName)}
& $python @manifestArgs
if($LASTEXITCODE -ne 0){throw 'Ideal-field diagnostic manifest failed.'}
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') `
  (Join-Path $OutputDir 'run_manifest.json') --require-status success
if($LASTEXITCODE -ne 0){throw 'Ideal-field diagnostic manifest verification failed.'}
$runRecordComplete = $true
try { Remove-RunExecutionAlias -ExecutionAlias $executionAlias.execution_alias -TargetDirectory $OutputDir }
catch { Write-Warning "Could not remove short diagnostic execution alias: $($_.Exception.Message)" }
$executionAlias = $null
$summaries | Sort-Object Distribution,Mode | Format-Table Distribution,Mode,Hit,EfficiencyPct,MeanTofUs,StdTofNs,FwhmTofNs,ResolutionFwhm,MaxCrossingRadiusMm -AutoSize
Write-Host "Summary: $summaryCsv"

} finally {
  Exit-HostExecutionLease -Lease $hostExecutionLease
}
