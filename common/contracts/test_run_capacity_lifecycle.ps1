[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python=Join-Path $repoRoot '.venv\Scripts\python.exe'
$temporary=Join-Path ([IO.Path]::GetTempPath()) ('run_capacity_lifecycle_'+[guid]::NewGuid().ToString('N'))
$savedState=$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH
$savedPython=$env:SIMULATION_PYTHON_EXE
try{
  $env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=Join-Path $temporary 'host.sqlite3'
  $env:SIMULATION_PYTHON_EXE=$python
  . (Join-Path $PSScriptRoot 'run_artifact_support.ps1')
  $artifactRoot=Join-Path $temporary 'artifacts'
  $projectRoot=Join-Path $artifactRoot 'projects\fixture'
  New-Item -ItemType Directory -Force -Path $projectRoot,(Join-Path $artifactRoot 'common')|Out-Null
  Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
    & $python -c "from pathlib import Path; from common.contracts.capacity_ledger import initialize_capacity_ledger; initialize_capacity_ledger(Path(r'$artifactRoot'), objects=[])"
    if($LASTEXITCODE-ne0){throw 'Fixture ledger initialization failed.'}
  }

  $package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $projectRoot `
    -CapacityLedgerArtifactRoot $artifactRoot -CapacityLedgerLifecycleEnabled `
    -RetentionContractEnabled -RetentionClass compact `
    -RunId '20260723_170007__test__cross__capacity-ledger-lifecycle__n1' `
    -Project fixture -Mode contract_test -Software @('contract test')
  $ledger=Get-Content -LiteralPath (Join-Path $artifactRoot 'common\capacity_ledger.json') -Raw|ConvertFrom-Json
  $entry=@($ledger.objects|Where-Object{$_.path-like'projects/fixture/runs/*capacity-ledger-lifecycle*'})[0]
  if($entry.class-ne'rebuildable_payload'-or$entry.status-ne'writing'){throw 'New run was not registered as rebuildable_payload/writing.'}

  $oversized=Join-Path $package.result_dir 'oversized_summary.json'
  $stream=[IO.File]::Open($oversized,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
  try{$stream.SetLength(26214401)}finally{$stream.Dispose()}
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config
  $warnings=@()
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config `
    -Status success -Software @('contract test') -Outputs @($package.summary,$retention) `
    -WarningVariable warnings
  if((@($warnings)-join"`n")-notmatch'RUN_LIGHT_EVIDENCE_BUDGET_EXCEEDED'){throw 'Oversized light evidence did not warn.'}
  if(-not(Test-Path -LiteralPath $oversized -PathType Leaf)){throw 'Oversized light evidence was deleted.'}
  $ledger=Get-Content -LiteralPath (Join-Path $artifactRoot 'common\capacity_ledger.json') -Raw|ConvertFrom-Json
  $entry=@($ledger.objects|Where-Object{$_.path-like'projects/fixture/runs/*capacity-ledger-lifecycle*'})[0]
  [int64]$actual=(Get-ChildItem -LiteralPath $package.artifact_run_dir -Recurse -File|Measure-Object Length -Sum).Sum
  if($entry.class-ne'light_evidence'-or$entry.status-ne'ready'-or[int64]$entry.bytes-ne$actual){throw 'Terminal run was not recorded as exact light_evidence/ready.'}

  $unretained=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $projectRoot `
    -CapacityLedgerArtifactRoot $artifactRoot -CapacityLedgerLifecycleEnabled `
    -RetentionContractEnabled -RetentionClass compact `
    -RunId '20260723_170008__test__cross__capacity-ledger-unretained__n1' `
    -Project fixture -Mode contract_test -Software @('contract test')
  $rejected=$false
  try{Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $unretained.run_config `
      -Status failed -Software @('contract test') -Outputs @($unretained.summary)}catch{$rejected=$true}
  if(-not$rejected){throw 'Terminal publication bypassed retention.'}
  $ledger=Get-Content -LiteralPath (Join-Path $artifactRoot 'common\capacity_ledger.json') -Raw|ConvertFrom-Json
  $entry=@($ledger.objects|Where-Object{$_.path-like'projects/fixture/runs/*capacity-ledger-unretained*'})[0]
  if($entry.status-ne'writing'){throw 'Pre-retention failure did not remain writing.'}
  if((Get-Content -LiteralPath (Join-Path $unretained.artifact_run_dir 'run_manifest.json') -Raw|ConvertFrom-Json).status-ne'checkpoint'){
    throw 'Pre-retention failure published a terminal manifest.'
  }

  $sessionDir=Join-Path $artifactRoot 'projects\fixture\session-consumer'
  New-Item -ItemType Directory -Force -Path $sessionDir|Out-Null
  $session=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot $artifactRoot -RunDirectory $sessionDir -CommittedNewBytes 1024 `
    -ProtectedPaths @($sessionDir)
  $updated=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -Session $session -RemainingCommittedNewBytes 512
  if([int64]$updated.session.committed_new_bytes-ne512){throw 'Session remaining commitment was not updated.'}
  $released=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $updated.session
  if(-not[bool]$released.deleted){throw 'Session lease was not released.'}
  Write-Output 'RUN_CAPACITY_LIFECYCLE=PASS'
}finally{
  $env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=$savedState
  $env:SIMULATION_PYTHON_EXE=$savedPython
  if(Test-Path -LiteralPath $temporary){[IO.Directory]::Delete($temporary,$true)}
}
