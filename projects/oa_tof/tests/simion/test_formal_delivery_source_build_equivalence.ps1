param(
  [Parameter(Mandatory = $true)][string]$ReferenceDir,
  [Parameter(Mandatory = $true)][string]$CandidateDir,
  [string]$RunId = ((Get-Date -Format 'yyyyMMdd_HHmmss') + '__test__simion__delivery-equivalence__n1000'),
  [int]$ParticleCount = 1000,
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\oa_tof'
$reference = (Resolve-Path -LiteralPath $ReferenceDir).Path
$candidate = (Resolve-Path -LiteralPath $CandidateDir).Path
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $RunId" }
$runDir = Join-Path $artifactRoot "runs\$RunId"
$resultDir = Join-Path $runDir 'results'
if (Test-Path -LiteralPath $runDir) { throw "Run directory already exists: $runDir" }
if (Test-Path -LiteralPath $resultDir) { throw "Result directory already exists: $resultDir" }
New-Item -ItemType Directory -Path $runDir,$resultDir | Out-Null

$ion = Join-Path $reference ("oatof_comsol_524amu_gaussian_N{0}.ion" -f $ParticleCount)
$fieldVerifier = Join-Path $PSScriptRoot 'verify_formal_runtime.lua'
$logAnalyzer = Join-Path $projectRoot 'simion\workbench\analyze_ideal_field_log.ps1'
$referenceAnalysis = Join-Path $projectRoot 'analysis\reference_analysis.py'
$runConfigPath = Join-Path $runDir 'run_config.json'
$runConfig = [ordered]@{
  schema_version=1; role='oa_tof_simion_source_build_equivalence_run_config'
  run_id=$RunId; project='oa_tof'; mode='simion_source_build_equivalence'
  project_root=$projectRoot
  inputs=[ordered]@{
    reference_iob=(Join-Path $reference 'oatof_ideal_grounded.iob')
    candidate_iob=(Join-Path $candidate 'oatof_ideal_grounded.iob')
    fixed_ion=$ion
  }
  particle_count=$ParticleCount; trajectory_quality=8
  output_dir=$runDir; result_dir=$resultDir; formal_gate_passed=$false
}
$runConfig | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runConfigPath -Encoding UTF8
foreach ($path in @($SimionExe,$ion,$fieldVerifier,$logAnalyzer,$python,$referenceAnalysis)) {
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required input is absent: $path" }
}

function Invoke-Simion([string[]]$Arguments,[string]$WorkingDirectory,[string]$Stdout,[string]$Stderr) {
  $process = Start-Process -FilePath $SimionExe -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory `
    -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr
  if ($process.ExitCode -ne 0) { throw "SIMION failed with exit code $($process.ExitCode): $Stderr" }
}

$cases = [ordered]@{ reference=$reference; source_built=$candidate }
foreach ($entry in $cases.GetEnumerator()) {
  $name = $entry.Key; $dir = $entry.Value
  $iob = Join-Path $dir 'oatof_ideal_grounded.iob'
  $resolvedLua = Join-Path $dir 'oatof_resolved.lua'
  if (-not (Test-Path -LiteralPath $resolvedLua -PathType Leaf)) { throw "$name resolved contract is absent: $resolvedLua" }
  $fieldReport = Join-Path $runDir ($name + '_field.txt')
  $fieldArguments = @('--nogui','lua',$fieldVerifier,$fieldReport,$iob,$resolvedLua)
  if ($name -eq 'reference') { $fieldArguments += 'allow_legacy_order' }
  Invoke-Simion $fieldArguments $dir `
    (Join-Path $runDir ($name + '_field_stdout.log')) (Join-Path $runDir ($name + '_field_stderr.log'))
  if (-not (Select-String -LiteralPath $fieldReport -Pattern '^STATUS=PASS$' -Quiet)) {
    throw "$name field/runtime verification did not pass."
  }
  $flyLog = Join-Path $runDir ($name + '.log')
  Invoke-Simion @('--default-num-particles',[string]$ParticleCount,'--nogui','fly',
    '--trajectory-quality','8','--retain-trajectories','0','--particles',$ion,
    '--adjustable','trajectory_quality=8','--adjustable','trajectory_log_enable=1',$iob) $dir `
    $flyLog (Join-Path $runDir ($name + '.stderr.log'))
  $summary = & $logAnalyzer -Log $flyLog -IonFile $ion -Mode $name `
    -Distribution ("fixedN{0}" -f $ParticleCount) -ParticleCsv (Join-Path $runDir ($name + '_particles.csv'))
  $summary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $runDir ($name + '_summary.json')) -Encoding UTF8
  if ([int]$summary.Hit -ne $ParticleCount) { throw "$name hit count $($summary.Hit) != $ParticleCount" }
}

function Read-Fields([string]$Path) {
  $values = @{}
  foreach ($line in Get-Content -LiteralPath $Path) {
    if ($line -match '^FIELD_(.+)_PA_LOCAL_E_V_PER_MM=([-+0-9.eE]+),([-+0-9.eE]+),([-+0-9.eE]+)$') {
      $values[$Matches[1]] = @([double]$Matches[2],[double]$Matches[3],[double]$Matches[4])
    }
  }
  return $values
}
$leftFields = Read-Fields (Join-Path $runDir 'reference_field.txt')
$rightFields = Read-Fields (Join-Path $runDir 'source_built_field.txt')
$maxFieldRelativeDifference = 0.0
foreach ($key in $leftFields.Keys) {
  if (-not $rightFields.ContainsKey($key)) { throw "Source-built field report lacks $key" }
  $left = $leftFields[$key]; $right = $rightFields[$key]
  $norm = [Math]::Sqrt($left[0]*$left[0]+$left[1]*$left[1]+$left[2]*$left[2])
  $difference = [Math]::Sqrt(($right[0]-$left[0])*($right[0]-$left[0])+
    ($right[1]-$left[1])*($right[1]-$left[1])+($right[2]-$left[2])*($right[2]-$left[2]))
  if ($norm -gt 1e-12) { $maxFieldRelativeDifference = [Math]::Max($maxFieldRelativeDifference,$difference/$norm) }
}

& $python -m projects.oa_tof.analysis.reference_analysis compare (Join-Path $runDir 'reference_particles.csv') `
  (Join-Path $runDir 'source_built_particles.csv') --mass 524 --output $resultDir `
  --left-label frozen_formal --right-label source_built --require-paired-particle-ids --bootstrap-resamples 0
if ($LASTEXITCODE -ne 0) { throw 'Unified paired comparison failed.' }
$metrics = Get-Content -LiteralPath (Join-Path $resultDir 'comparison_metrics.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$comparison = $metrics.comparison
$checks = [ordered]@{
  max_field_relative_difference = $maxFieldRelativeDifference -le 1e-6
  mean_tof_difference_ns = [Math]::Abs([double]$comparison.mean_tof_difference_right_minus_left_ns) -le 0.01
  paired_tof_rms_ns = [double]$comparison.paired_tof_difference.rms_ns -le 0.01
  paired_tof_max_abs_ns = [double]$comparison.paired_tof_difference.max_abs_ns -le 0.05
  paired_landing_rms_mm = [double]$comparison.detector_landing.paired_rms_landing_distance_mm -le 0.001
  paired_landing_max_mm = [double]$comparison.detector_landing.paired_max_landing_distance_mm -le 0.005
  standardized_kde_overlap = [double]$comparison.standardized_kde_overlap -ge 0.999
}
$failed = @($checks.GetEnumerator() | Where-Object { -not $_.Value })
$promotion = [ordered]@{
  schema_version=1; status=if($failed.Count){'FAIL'}else{'PASS'}; particle_count=$ParticleCount
  reference_dir=$reference; candidate_dir=$candidate; max_field_relative_difference=$maxFieldRelativeDifference
  mean_tof_difference_ns=[double]$comparison.mean_tof_difference_right_minus_left_ns
  paired_tof_rms_ns=[double]$comparison.paired_tof_difference.rms_ns
  paired_tof_max_abs_ns=[double]$comparison.paired_tof_difference.max_abs_ns
  paired_landing_rms_mm=[double]$comparison.detector_landing.paired_rms_landing_distance_mm
  paired_landing_max_mm=[double]$comparison.detector_landing.paired_max_landing_distance_mm
  standardized_kde_overlap=[double]$comparison.standardized_kde_overlap; checks=$checks
}
$promotion | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $resultDir 'promotion_summary.json') -Encoding UTF8
$promotion | Add-Member -NotePropertyName status -NotePropertyValue 'success' -Force
$promotion | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $runDir 'summary.json') -Encoding UTF8
if ($failed.Count) { throw "Source-built delivery equivalence failed: $($failed.Key -join ', ')" }
$manifestScript = Join-Path $repoRoot 'common\contracts\write_run_manifest.py'
$manifestArguments = @(
  $manifestScript
  '--run-config'; $runConfigPath
  '--status'; 'success'
  '--software'; 'SIMION 2020'
)
$manifestOutputs = @(
  Get-ChildItem -LiteralPath $runDir -File | Where-Object { $_.Name -notin @('run_config.json','run_manifest.json') }
) + @(Get-ChildItem -LiteralPath $resultDir -File)
foreach ($output in $manifestOutputs) { $manifestArguments += @('--output', $output.FullName) }
& $python @manifestArguments
if ($LASTEXITCODE -ne 0) { throw 'Source-build equivalence manifest generation failed.' }
Write-Output "SIMION_SOURCE_BUILD_EQUIVALENCE=PASS RESULT=$resultDir"
