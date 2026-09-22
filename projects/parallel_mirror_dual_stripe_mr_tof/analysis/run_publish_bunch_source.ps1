[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$SourceDefinitionPath,
  [Parameter(Mandatory)][string]$GeometryContractPath,
  [string]$RunId='',
  [string]$PythonExe=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$sourceDefinition=(Resolve-Path -LiteralPath $SourceDefinitionPath).Path
$geometryContract=(Resolve-Path -LiteralPath $GeometryContractPath).Path
if([string]::IsNullOrWhiteSpace($RunId)){
  $RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__analysis__python__mrtof-bunch-source-n100'
}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$artifactProjectRoot=Join-Path $workspaceRoot "artifacts\projects\$projectId"
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactProjectRoot `
  -RunId $RunId -Project $projectId -Mode 'deterministic_bunch_source_materialization' `
  -Software @('Python 3.11') -RetentionContractEnabled -RetentionClass compact `
  -CapacityLedgerLifecycleEnabled
$runConfig=$package.run_config
$summary=$package.summary
$resultDir=$package.result_dir
$logDir=$package.log_dir
$terminalized=$false
$failureStage='preflight'
$capacitySession=$null
try{
  $failureStage='capacity_startup'
  $capacitySession=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -RunDirectory $package.artifact_run_dir `
    -CommittedNewBytes 1048576 -ProtectedPaths @($package.artifact_run_dir) `
    -Owner "mrtof-publish-bunch-source:$RunId"
  $startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $startupPath -Depth 14 -Value $capacitySession

  $failureStage='freeze_inputs'
  $frozenDefinition=Copy-VerifiedRunInput -Source $sourceDefinition `
    -Destination (Join-Path $package.input_dir 'bunch_source_definition.json')
  $frozenGeometry=Copy-VerifiedRunInput -Source $geometryContract `
    -Destination (Join-Path $package.input_dir 'geometry_contract.json')
  $configuration=Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $configuration.inputs=[ordered]@{
    bunch_source_definition=$frozenDefinition
    geometry_contract=$frozenGeometry
  }
  $configuration.parameters=[ordered]@{
    lifecycle_stage='candidate_functional_source_materialization'
    solver_execution='none'
    source_authority='complete_frozen_definition_checked_against_resolved_accelerator_release'
  }
  Write-RunJson -Path $runConfig -Value $configuration

  $failureStage='materialize_source'
  $stateTable=Join-Path $resultDir 'bunch_source_states.csv'
  $fly2=Join-Path $resultDir 'bunch_source.fly2'
  $receipt=Join-Path $resultDir 'bunch_source_receipt.json'
  $log=Join-Path $logDir 'publish_bunch_source.log'
  Push-Location -LiteralPath $repoRoot
  $saved=$env:PYTHONPATH
  try{
    $env:PYTHONPATH=$repoRoot
    & $python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.bunch_source_and_schedule `
      materialize-source --definition $frozenDefinition --geometry-contract $frozenGeometry `
      --state-table $stateTable --fly2 $fly2 --receipt $receipt 2>&1|Tee-Object -FilePath $log
    if($LASTEXITCODE-ne 0){throw 'Bunch source materialization failed.'}
  }finally{
    $env:PYTHONPATH=$saved
    Pop-Location
  }
  $receiptData=Get-Content -LiteralPath $receipt -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  Write-RunJson -Path $summary -Depth 14 -Value ([ordered]@{
    schema_version=1
    role='mrtof_deterministic_bunch_source_run_summary'
    status='success'
    qualification='candidate_functional_source_only__no_simion_flight'
    source_receipt=$receiptData
  })

  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $terminal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -Session $capacitySession -RemainingCommittedNewBytes 0
  $capacitySession=$terminal.session
  $terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json'
  Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig `
    -Status success -Software @('Python 3.11') `
    -Outputs @($summary,$stateTable,$fly2,$receipt,$startupPath,$terminalPath,$retention,$log)
  $terminalized=$true
  Write-Host "MRTOF_BUNCH_SOURCE_RUN=PASS RUN_ID=$RunId N=$($receiptData.particle_count)"
}catch{
  if(-not$terminalized){
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
      -SummaryRole 'mrtof_deterministic_bunch_source_run_summary' -Reason $_.Exception.Message `
      -Software @('Python 3.11') -Status failed -FailureStage $failureStage
    $terminalized=$true
  }
  throw
}finally{
  try{
    if(-not$terminalized-and(Test-Path -LiteralPath $runConfig)){
      Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
        -SummaryRole 'mrtof_deterministic_bunch_source_run_summary' `
        -Reason 'Bunch source publication stopped before terminal publication.' `
        -Software @('Python 3.11') -Status interrupted -FailureStage $failureStage
    }
  }finally{
    if($null-ne$capacitySession){$null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession}
  }
}
