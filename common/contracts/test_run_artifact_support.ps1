[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-Equal {
  param(
    [Parameter(Mandatory)][object]$Actual,
    [Parameter(Mandatory)][object]$Expected,
    [Parameter(Mandatory)][string]$Message
  )
  if ($Actual -ne $Expected) {
    throw "$Message Expected='$Expected' Actual='$Actual'"
  }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$projectRoot = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer'
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ("run_artifact_support_" + [guid]::NewGuid().ToString('N'))
$executionRoot = Join-Path 'C:\tmp\ms' ("run_artifact_support_" + [guid]::NewGuid().ToString('N'))
$originalPythonPath=[Environment]::GetEnvironmentVariable('PYTHONPATH')
$originalNoUserSite=[Environment]::GetEnvironmentVariable('PYTHONNOUSERSITE')

try {
  . (Join-Path $PSScriptRoot 'run_artifact_support.ps1')
  $originalLocation=(Get-Location).Path
  [Environment]::SetEnvironmentVariable('PYTHONPATH','run-artifact-test-pythonpath')
  [Environment]::SetEnvironmentVariable('PYTHONNOUSERSITE','run-artifact-test-nousersite')
  $context=Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
    [pscustomobject]@{
      location=(Get-Location).Path
      python_path=$env:PYTHONPATH
      no_user_site=$env:PYTHONNOUSERSITE
    }
  }
  Assert-Equal $context.location $repoRoot 'Tool context did not use RepoRoot.'
  Assert-Equal $context.python_path $repoRoot 'Tool context did not bind PYTHONPATH.'
  Assert-Equal $context.no_user_site '1' 'Tool context did not disable user site.'
  Assert-Equal (Get-Location).Path $originalLocation 'Tool context did not restore location.'
  Assert-Equal ([Environment]::GetEnvironmentVariable('PYTHONPATH')) 'run-artifact-test-pythonpath' `
    'Tool context did not restore PYTHONPATH.'
  Assert-Equal ([Environment]::GetEnvironmentVariable('PYTHONNOUSERSITE')) 'run-artifact-test-nousersite' `
    'Tool context did not restore PYTHONNOUSERSITE.'

  $interruptedDir = Join-Path $testRoot '20260723_170001__test__cross__lifecycle-interrupted__n100'
  New-Item -ItemType Directory -Path $interruptedDir -Force | Out-Null
  Initialize-RunRecord -RunDir $interruptedDir `
    -RunId (Split-Path -Leaf $interruptedDir) -Project 'single_reflection_oa_tof_mass_analyzer' -Mode 'contract_test' `
    -ProjectRoot $projectRoot -RepoRoot $repoRoot -Python $python `
    -ProvisionalSummaryRole 'oa_tof_provisional_run_summary' `
    -TerminalSummaryRole 'oa_tof_terminal_run_summary'

  $config = Get-Content -LiteralPath (Join-Path $interruptedDir 'run_config.json') `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  $summary = Get-Content -LiteralPath (Join-Path $interruptedDir 'summary.json') `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  $manifest = Get-Content -LiteralPath (Join-Path $interruptedDir 'run_manifest.json') `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  Assert-Equal $config.project_root $projectRoot 'Initialize-RunRecord changed project_root.'
  Assert-Equal $summary.role 'oa_tof_terminal_run_summary' 'Initialization summary role changed.'
  Assert-Equal $summary.status 'interrupted' 'Initialization summary status changed.'
  Assert-Equal $summary.reason 'Run package initialized.' 'Initialization reason changed.'
  Assert-Equal $manifest.status 'interrupted' 'Initialization manifest status changed.'
  Assert-Equal @($manifest.outputs).Count 1 'Initialization manifest must record summary.json.'
  Assert-Equal (Split-Path -Leaf $manifest.outputs[0].path) 'summary.json' `
    'Initialization manifest output path changed.'

  Write-TerminalRunRecord -RunDir $interruptedDir -Status failed `
    -Reason 'synthetic failure' -RepoRoot $repoRoot -Python $python `
    -SummaryRole 'oa_tof_terminal_run_summary'
  $failedSummary = Get-Content -LiteralPath (Join-Path $interruptedDir 'summary.json') `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  $failedManifest = Get-Content -LiteralPath (Join-Path $interruptedDir 'run_manifest.json') `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  Assert-Equal $failedSummary.status 'failed' 'Failed summary status changed.'
  Assert-Equal $failedSummary.reason 'synthetic failure' 'Failed summary reason changed.'
  Assert-Equal $failedManifest.status 'failed' 'Failed manifest status changed.'

  $v2FailedDir = Join-Path (Join-Path $testRoot 'runs') '20260723_170004__test__cross__native-grid-failure__n1'
  New-Item -ItemType Directory -Path (Join-Path $v2FailedDir 'simion') -Force | Out-Null
  $v2Config = Join-Path $v2FailedDir 'run_config.json'
  $v2Summary = Join-Path $v2FailedDir 'summary.json'
  Write-RunJson -Path $v2Config -Value ([ordered]@{
    schema_version=2;run_id=(Split-Path -Leaf $v2FailedDir);project='single_reflection_oa_tof_mass_analyzer'
    mode='native_ideal_grid_smoke';project_root=$repoRoot;inputs=[ordered]@{}
    artifact_retention=[ordered]@{policy_version=1;class='compact';reason=$null}
  })
  'synthetic builder failure' | Set-Content -LiteralPath (Join-Path $v2FailedDir 'simion\accelerator_builder.stderr.log') -Encoding UTF8
  Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $v2Config -Summary $v2Summary `
    -SummaryRole 'oa_tof_native_ideal_grid_smoke_summary' -SummarySchemaVersion 2 `
    -Reason 'grid2 electrode has zero raw PA points' -FailureClass 'native_ideal_grid_smoke_failed' `
    -FailureStage 'accelerator_raw_pa_family_or_grid_row_audit' -ThresholdResultEligible $false `
    -AdditionalSummaryProperties ([ordered]@{cache_policy='require_existing';snapshot_completed=$false}) `
    -Software @('synthetic SIMION')
  $v2FailedSummary = Get-Content -LiteralPath $v2Summary -Raw -Encoding UTF8 | ConvertFrom-Json
  $v2FailedManifest = Get-Content -LiteralPath (Join-Path $v2FailedDir 'run_manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
  Assert-Equal $v2FailedSummary.schema_version 2 'Failed native-grid summary schema changed.'
  Assert-Equal $v2FailedSummary.failure_stage 'accelerator_raw_pa_family_or_grid_row_audit' 'Failed native-grid stage changed.'
  Assert-Equal $v2FailedSummary.threshold_result_eligible $false 'Failed native-grid result became threshold eligible.'
  Assert-Equal $v2FailedSummary.cache_policy 'require_existing' 'Additional failed summary property changed.'
  Assert-Equal $v2FailedSummary.snapshot_completed $false 'Pre-snapshot failure flag changed.'
  Assert-Equal $v2FailedManifest.status 'failed' 'Failed native-grid manifest status changed.'
  Assert-Equal $v2FailedManifest.artifact_retention.class 'compact' 'Failed native-grid retention changed.'
  $v2SummaryOutput = @($v2FailedManifest.outputs | Where-Object {
    [IO.Path]::GetFullPath([string]$_.path).Equals(
      [IO.Path]::GetFullPath($v2Summary), [StringComparison]::OrdinalIgnoreCase
    )
  })
  Assert-Equal $v2SummaryOutput.Count 1 'Failed summary manifest output changed.'
  Assert-Equal $v2SummaryOutput[0].sha256 `
    (Get-FileHash -LiteralPath $v2Summary -Algorithm SHA256).Hash `
    'Failed summary manifest SHA differs from final summary.'
  Assert-Equal ([int64]$v2SummaryOutput[0].bytes) `
    ([int64](Get-Item -LiteralPath $v2Summary).Length) `
    'Failed summary manifest bytes differ from final summary.'

  $successDir = Join-Path $testRoot '20260723_170002__test__cross__lifecycle-success__n100'
  New-Item -ItemType Directory -Path $successDir -Force | Out-Null
  $successConfig = Join-Path $successDir 'run_config.json'
  $successSummary = Join-Path $successDir 'summary.json'
  Write-RunJson -Path $successConfig -Value ([ordered]@{
    schema_version=1;run_id=(Split-Path -Leaf $successDir);project='single_reflection_oa_tof_mass_analyzer'
    mode='contract_test';project_root=$projectRoot;inputs=[ordered]@{}
  })
  Write-RunJson -Path $successSummary -Value ([ordered]@{
    schema_version=1;role='oa_tof_contract_test_summary';status='success'
  })
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot `
    -RunConfig $successConfig -Status success -Outputs @($successSummary)
  $successManifest = Get-Content -LiteralPath (Join-Path $successDir 'run_manifest.json') `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  Assert-Equal $successManifest.status 'success' 'Success manifest status changed.'

  $budgetPackage=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $testRoot `
    -RunId '20260723_170003__test__cross__resource-budget__n100' `
    -Project 'single_reflection_oa_tof_mass_analyzer' -Mode 'contract_test' `
    -Software @('contract test') -RetentionContractEnabled -RetentionClass compact
  $usagePath=Join-Path $budgetPackage.result_dir 'resource_usage.json'
  Write-RunJson -Path $usagePath -Value ([ordered]@{
    schema_version=1;role='multipole_resource_usage';status='running'
    failure_class=$null;limit_name='wall_clock_seconds'
    peak_run_directory_bytes=0;final_retained_bytes=$null
    limits=[ordered]@{compact_final_retained_bytes=26214400}
  })
  Complete-FailedRun -Python $python -RepoRoot $repoRoot `
    -RunConfig $budgetPackage.run_config -Summary $budgetPackage.summary `
    -SummaryRole 'resource_budget_test_summary' -Reason 'wall clock exceeded' `
    -Software @('contract test') -Status interrupted `
    -FailureClass resource_budget_exceeded -ResourceUsagePath $usagePath
  $budgetSummary=Get-Content -LiteralPath $budgetPackage.summary -Raw|ConvertFrom-Json
  $budgetManifest=Get-Content -LiteralPath (Join-Path $budgetPackage.run_dir 'run_manifest.json') -Raw|ConvertFrom-Json
  $budgetUsage=Get-Content -LiteralPath $usagePath -Raw|ConvertFrom-Json
  Assert-Equal $budgetSummary.status 'interrupted' 'Resource budget summary must be interrupted.'
  Assert-Equal $budgetSummary.failure_class 'resource_budget_exceeded' 'Resource budget failure class changed.'
  Assert-Equal $budgetManifest.status 'interrupted' 'Resource budget manifest must be interrupted.'
  Assert-Equal $budgetUsage.status 'interrupted' 'Resource usage must leave running state on failure.'
  Assert-Equal $budgetUsage.failure_class 'resource_budget_exceeded' `
    'Resource usage failure class changed.'

  $shortPackage=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $testRoot `
    -RunId '20260723_170005__test__cross__short-execution-path__n1' `
    -Project 'single_reflection_oa_tof_mass_analyzer' -Mode 'contract_test' `
    -Software @('contract test') -UseShortExecutionPath -ExecutionRoot $executionRoot
  Assert-Equal ([IO.Path]::GetFullPath($shortPackage.artifact_run_dir)) `
    ([IO.Path]::GetFullPath((Join-Path $testRoot 'runs\20260723_170005__test__cross__short-execution-path__n1'))) `
    'Short package artifact run path changed.'
  if (-not $shortPackage.execution_alias -or
      -not ([IO.Path]::GetFullPath($shortPackage.run_dir).StartsWith(
        [IO.Path]::GetFullPath($executionRoot) + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
      ))) {
    throw 'Short package did not return an execution-root alias.'
  }
  $shortManifest = Join-Path $shortPackage.run_dir 'run_manifest.json'
  $shortInput = Join-Path $shortPackage.input_dir 'short_execution_input.json'
  Set-Content -LiteralPath $shortInput -Value '{"role":"short_execution_probe"}' -Encoding UTF8
  $shortConfig = Get-Content -LiteralPath $shortPackage.run_config -Raw -Encoding UTF8 |
    ConvertFrom-Json -AsHashtable
  $shortConfig.inputs = [ordered]@{ short_execution_probe = $shortInput }
  Write-RunJson -Path $shortPackage.run_config -Value $shortConfig
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot `
    -RunConfig $shortPackage.run_config -Status interrupted -Software @('contract test') `
    -Outputs @($shortPackage.summary)
  $shortManifestDocument = Get-Content -LiteralPath $shortManifest -Raw -Encoding UTF8 | ConvertFrom-Json
  Assert-Equal ([IO.Path]::GetFullPath([string]$shortManifestDocument.run_config.path)) `
    ([IO.Path]::GetFullPath((Join-Path $shortPackage.artifact_run_dir 'run_config.json'))) `
    'Manifest must resolve the short execution alias to the artifact run.'
  Assert-Equal ([IO.Path]::GetFullPath([string]$shortManifestDocument.inputs.short_execution_probe.path)) `
    ([IO.Path]::GetFullPath((Join-Path $shortPackage.artifact_run_dir 'inputs\short_execution_input.json'))) `
    'Manifest must resolve short execution input paths to the artifact run.'
  Remove-RunPackageExecutionAlias -Package $shortPackage
  if (Test-Path -LiteralPath $shortPackage.execution_alias) {
    throw 'Short execution alias remained after cleanup.'
  }
  if (-not (Test-Path -LiteralPath $shortPackage.artifact_run_dir -PathType Container)) {
    throw 'Short execution alias cleanup removed the artifact run.'
  }
  Assert-Equal $shortPackage.execution_path_capacity.role 'run_package_execution_path_capacity' `
    'Short package path capacity role changed.'
  if (-not $shortPackage.execution_path_capacity.legacy_windows_compatible) {
    throw 'Short execution alias did not satisfy legacy Windows path capacity.'
  }

  $directTarget=Join-Path $testRoot 'direct_execution_target'
  New-Item -ItemType Directory -Path $directTarget -Force|Out-Null
  $directAlias=New-RunExecutionAlias -TargetDirectory $directTarget `
    -ExecutionRoot $executionRoot -ExpectedExecutionRelativePaths @('simion\nested\result.json')
  if(-not(Test-Path -LiteralPath $directAlias.execution_alias -PathType Container)){
    throw 'Generic short execution alias was not created.'
  }
  Remove-RunExecutionAlias -ExecutionAlias $directAlias.execution_alias -TargetDirectory $directTarget
  if(Test-Path -LiteralPath $directAlias.execution_alias){
    throw 'Generic short execution alias remained after cleanup.'
  }
  if(-not(Test-Path -LiteralPath $directTarget -PathType Container)){
    throw 'Generic short execution alias cleanup removed its target.'
  }
  try {
    $tooLongRelativePath = ('x' * 260) + '.json'
    New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $testRoot `
      -RunId '20260723_170006__test__cross__short-path-capacity__n1' `
      -Project 'single_reflection_oa_tof_mass_analyzer' -Mode 'contract_test' `
      -Software @('contract test') -UseShortExecutionPath -ExecutionRoot $executionRoot `
      -ExpectedExecutionRelativePaths $tooLongRelativePath | Out-Null
    throw 'Expected execution path capacity rejection did not occur.'
  } catch {
    if ($_.Exception.Message -notmatch 'EXECUTION_PATH_CAPACITY=FAIL') { throw }
  }
  if (Test-Path -LiteralPath (Join-Path $testRoot 'runs\20260723_170006__test__cross__short-path-capacity__n1')) {
    throw 'Path-capacity rejection created an artifact run directory.'
  }

  $writeError = ''
  try {
    Write-VerifiedRunManifest -Python (Join-Path $testRoot 'missing-python.exe') `
      -RepoRoot $repoRoot -RunConfig $successConfig -Status failed
  } catch {
    $writeError = $_.Exception.Message
  }
  if ($writeError -notlike 'Could not publish verified failed run manifest:*') {
    throw "Manifest write failure message changed. Actual='$writeError'"
  }

  $timeoutRejected = $false
  try {
    Write-RunManifest -Python $python -RepoRoot $repoRoot `
      -RunConfig $successConfig -Status timeout
  } catch {
    $timeoutRejected = $true
  }
  Assert-Equal $timeoutRejected $true `
    'PowerShell manifest support must not reinterpret candidate-workflow timeout.'

  Write-Output 'RUN_ARTIFACT_SUPPORT=PASS'
} finally {
  [Environment]::SetEnvironmentVariable('PYTHONPATH',$originalPythonPath)
  [Environment]::SetEnvironmentVariable('PYTHONNOUSERSITE',$originalNoUserSite)
  if (Test-Path -LiteralPath $testRoot) {
    [IO.Directory]::Delete($testRoot, $true)
  }
  if (Test-Path -LiteralPath $executionRoot) {
    [IO.Directory]::Delete($executionRoot, $true)
  }
}
