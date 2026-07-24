param(
  [string]$RunId = "$(Get-Date -Format 'yyyyMMdd_HHmmss')__test__simion__oatof-source-build-track__n100",
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$repoRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\oa_tof'
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
$formalSimion = Join-Path $artifactRoot 'formal\simion'
$builder = Join-Path $projectRoot 'simion\workbench\build_formal_delivery.ps1'
$analyzer = Join-Path $projectRoot 'simion\workbench\analyze_ideal_field_log.ps1'
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')

foreach ($path in @($SimionExe, $builder, $analyzer)) {
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
    throw "Required executable or script is missing: $path"
  }
}
$software = @('SIMION 2020', 'Python 3.11')
$package = New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunId $RunId -Project 'oa_tof' -Mode 'simion_n100_source_build_and_track' `
  -Software $software -AdditionalDirectories @('simion')
$simionDir = Join-Path $package.run_dir 'simion'
$textDir = Join-Path $package.input_dir 'simion_text'
New-Item -ItemType Directory -Path $textDir | Out-Null

$inputSources = [ordered]@{
  baseline = Join-Path $projectRoot 'config\baseline.json'
  resolved_geometry = Join-Path $projectRoot 'config\resolved_geometry.json'
  resolved_lua = Join-Path $projectRoot 'simion\workbench\formal\oatof_resolved.lua'
  program_lua = Join-Path $projectRoot 'simion\workbench\formal\oatof_ideal_grounded.lua'
  particles_fly2 = Join-Path $projectRoot 'simion\workbench\formal\oatof_ideal_grounded.fly2'
  accelerator_builder = Join-Path $projectRoot 'simion\accelerator\build_accelerator_variant.lua'
  reflectron_builder = Join-Path $projectRoot 'simion\reflectron\build_reflectron_variant.lua'
  flight_tube_builder = Join-Path $projectRoot 'simion\workbench\build_flight_tube_variant.lua'
  detector_builder = Join-Path $projectRoot 'simion\workbench\build_detector_variant.lua'
}
$frozen = [ordered]@{}
foreach ($entry in $inputSources.GetEnumerator()) {
  if (-not (Test-Path -LiteralPath $entry.Value -PathType Leaf)) {
    throw "Required input is missing: $($entry.Value)"
  }
  $destination = if ($entry.Key -in @('resolved_lua', 'program_lua', 'particles_fly2')) {
    Join-Path $textDir (Split-Path -Leaf $entry.Value)
  }
  else {
    Join-Path $package.input_dir ("{0}__{1}" -f $entry.Key, (Split-Path -Leaf $entry.Value))
  }
  Copy-Item -LiteralPath $entry.Value -Destination $destination
  $frozen[$entry.Key] = $destination
}
$templateIob = Join-Path $formalSimion 'oatof_ideal_grounded.iob'
$frozen.template_iob = $templateIob

$config = Get-Content -LiteralPath $package.run_config -Raw -Encoding UTF8 |
  ConvertFrom-Json -AsHashtable
$config.inputs = $frozen
$config.parameters = [ordered]@{
  particle_count = 100
  trajectory_quality = 8
  lifecycle_stage = 'inputs_frozen'
  claim_limit = 'Functional source build and N=100 transport only; no Formal or convergence claim.'
}
Write-RunJson -Value $config -Path $package.run_config
Write-RunManifest -Python $package.python -RepoRoot $repoRoot `
  -RunConfig $package.run_config -Status interrupted -Software $software

function Invoke-SimionHidden {
  param(
    [Parameter(Mandatory)][string[]]$Arguments,
    [Parameter(Mandatory)][string]$WorkingDirectory,
    [Parameter(Mandatory)][string]$Stdout,
    [Parameter(Mandatory)][string]$Stderr,
    [switch]$ExpectFailure
  )
  $process = Start-Process -FilePath $SimionExe -ArgumentList $Arguments `
    -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -Wait -PassThru `
    -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr
  if ($ExpectFailure) {
    if ($process.ExitCode -eq 0) { throw 'SIMION unexpectedly accepted missing builder arguments.' }
  }
  elseif ($process.ExitCode -ne 0) {
    throw "SIMION failed with exit code $($process.ExitCode): $Stderr"
  }
}

try {
  $requiredBuilders = @(
    @{
      Name = 'reflectron'
      Script = Join-Path $projectRoot 'simion\reflectron\build_reflectron_variant.lua'
      Source = Join-Path $projectRoot 'simion\reflectron\oatof_reflectron_ideal_10_5.gem'
    },
    @{
      Name = 'flight_tube'
      Script = Join-Path $projectRoot 'simion\workbench\build_flight_tube_variant.lua'
      Source = Join-Path $projectRoot 'simion\workbench\oatof_flight_tube_ground.gem'
    },
    @{
      Name = 'detector'
      Script = Join-Path $projectRoot 'simion\workbench\build_detector_variant.lua'
      Source = Join-Path $projectRoot 'simion\workbench\oatof_detector_ground.gem'
    }
  )
  foreach ($case in $requiredBuilders) {
    $stdout = Join-Path $package.log_dir "$($case.Name)_missing_args.stdout.log"
    $stderr = Join-Path $package.log_dir "$($case.Name)_missing_args.stderr.log"
    Invoke-SimionHidden -Arguments @(
      '--nogui', 'lua', $case.Script, $case.Source,
      (Join-Path $simionDir "$($case.Name)_invalid.pa#")
    ) -WorkingDirectory $simionDir -Stdout $stdout -Stderr $stderr -ExpectFailure
    $failureText = (Get-Content $stdout, $stderr -Raw -ErrorAction SilentlyContinue) -join "`n"
    if ($failureText -notmatch 'arguments are required') {
      throw "$($case.Name) builder did not report its required-argument contract."
    }
  }

  & $builder -SimionExe $SimionExe -OutputDir $simionDir -RunId $RunId `
    -ContractPath $frozen.resolved_geometry -CandidateBaselinePath $frozen.baseline `
    -CandidateTextDir $textDir -TemplateIob $templateIob -DeferRunFinalization
  if ($LASTEXITCODE -ne 0) { throw 'SIMION source delivery build failed.' }

  $temporaryGem = @(Get-ChildItem -LiteralPath $simionDir -Recurse -File |
    Where-Object { $_.Name -like '*.source.gem' -or $_.Name -like '*.processed.gem' })
  if ($temporaryGem.Count -ne 0) {
    throw "SIMION build left temporary GEM files: $($temporaryGem.FullName -join ', ')"
  }

  $iob = Join-Path $simionDir 'oatof_ideal_grounded.iob'
  $ion = Join-Path $simionDir 'oatof_comsol_524amu_gaussian_N100.ion'
  $flyLog = Join-Path $package.log_dir 'simion_n100.log'
  $flyError = Join-Path $package.log_dir 'simion_n100.stderr.log'
  Invoke-SimionHidden -Arguments @(
    '--default-num-particles', '100', '--nogui', 'fly',
    '--trajectory-quality', '8', '--retain-trajectories', '0',
    '--particles', $ion,
    '--adjustable', 'trajectory_quality=8',
    '--adjustable', 'trajectory_log_enable=1',
    $iob
  ) -WorkingDirectory $simionDir -Stdout $flyLog -Stderr $flyError

  $particleCsv = Join-Path $package.result_dir 'simion_particles.csv'
  $diagnostics = & $analyzer -Log $flyLog -IonFile $ion -Mode 'source_built' `
    -Distribution 'fixedN100' -ParticleCsv $particleCsv
  if ($LASTEXITCODE -ne 0) { throw 'Python SIMION diagnostics failed.' }
  if ([int]$diagnostics.Emitted -ne 100 -or [int]$diagnostics.Crossed -ne 100 -or
      [int]$diagnostics.Hit -ne 100) {
    throw "SIMION diagnostic census failed: $($diagnostics | ConvertTo-Json -Compress)"
  }
  $diagnosticsPath = Join-Path $package.result_dir 'solver_diagnostics.json'
  $diagnostics | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $diagnosticsPath -Encoding UTF8
  Write-RunJson -Path $package.summary -Value ([ordered]@{
    schema_version = 1
    role = 'oa_tof_simion_n100_source_build_and_track_summary'
    status = 'success'
    particles = 100
    detector_crossings = 100
    detector_hits = 100
    mean_tof_us = [double]$diagnostics.MeanTofUs
    required_builder_arguments = 'reflectron,flight_tube,detector verified'
    temporary_gem_files_remaining = 0
    diagnostics_entry = 'analysis/solver_diagnostics.py'
    formal_modified = $false
  })
  $outputs = @(
    $iob,
    (Join-Path $simionDir 'SHA256SUMS.csv'),
    (Join-Path $simionDir 'stage_summary.json'),
    $flyLog,
    $particleCsv,
    $diagnosticsPath,
    $package.summary
  )
  Write-RunManifest -Python $package.python -RepoRoot $repoRoot `
    -RunConfig $package.run_config -Status success -Software $software -Outputs $outputs
  & $package.python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') `
    (Join-Path $package.run_dir 'run_manifest.json') --require-status success
  if ($LASTEXITCODE -ne 0) { throw 'SIMION run manifest verification failed.' }
  Write-Output "OATOF_SIMION_N100=PASS RUN_ID=$RunId RUN_DIR=$($package.run_dir)"
}
catch {
  $reason = $_.Exception.Message
  Complete-FailedRun -Python $package.python -RepoRoot $repoRoot `
    -RunConfig $package.run_config -Summary $package.summary `
    -SummaryRole 'oa_tof_simion_n100_source_build_and_track_summary' `
    -Reason $reason -Software $software
  $failedOutputs = @($package.summary)
  $failedOutputs += @(Get-ChildItem -LiteralPath $package.log_dir -File |
    ForEach-Object { $_.FullName })
  Write-RunManifest -Python $package.python -RepoRoot $repoRoot `
    -RunConfig $package.run_config -Status failed -Software $software `
    -Outputs $failedOutputs
  throw
}
