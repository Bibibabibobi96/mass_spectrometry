[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$Request,
  [string]$RunId='',
  [string]$PythonExe='',
  [string]$RepoRoot=(Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)))
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$repoRoot=(Resolve-Path -LiteralPath $RepoRoot).Path
. (Join-Path $repoRoot 'common/require_powershell7.ps1')
. (Join-Path $repoRoot 'common/contracts/run_artifact_support.ps1')
. (Join-Path $repoRoot 'integrations/runtime/dependencies.ps1')
$python=if($PythonExe){(Resolve-Path -LiteralPath $PythonExe).Path}else{Join-Path $repoRoot '.venv/Scripts/python.exe'}
$requestPath=(Resolve-Path -LiteralPath $Request).Path
$requestDocument=Get-Content -LiteralPath $requestPath -Raw|ConvertFrom-Json -Depth 100
$requestDirectory=Split-Path -Parent $requestPath
$sourceManifest=[IO.Path]::GetFullPath([string]$requestDocument.source.manifest.path,$requestDirectory)
$receiverManifest=[IO.Path]::GetFullPath([string]$requestDocument.receiver.manifest.path,$requestDirectory)
$parentPlan=[IO.Path]::GetFullPath([string]$requestDocument.composition_plan.path,$requestDirectory)
if(-not$RunId){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__analysis__python__multipole-ip-preparation'}
$workspace=Split-Path -Parent $repoRoot
$package=New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $workspace 'artifacts/projects/instrument_assembly') `
  -RunId $RunId -Project instrument_assembly -Mode multipole_ip_preparation `
  -Software @('Python 3.11') -RetentionContractEnabled -RetentionClass compact -CapacityLedgerLifecycleEnabled
$capacity=$null;$lease=$null;$terminalized=$false;$stage='capacity_startup'
try{
  $capacity=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot (Join-Path $workspace 'artifacts') -RunDirectory $package.artifact_run_dir `
    -CommittedNewBytes 16777216 -ProtectedPaths @($package.artifact_run_dir,(Split-Path $sourceManifest -Parent),(Split-Path $receiverManifest -Parent)) `
    -Owner "instrument-assembly-multipole-ip:$RunId"
  $stage='freeze_inputs'
  $dependencyPath=Join-Path $repoRoot 'integrations/config/runtime_dependencies.json'
  $frozen=Freeze-ConsumerDependencies -RepoRoot $repoRoot -ContractPath $dependencyPath -InputDir $package.input_dir -OwnerId instrument_assembly -ConsumerId multipole_ip
  $frozenRequest=Join-Path $package.input_dir 'multipole_ip_request.json'
  # Resolve only transport paths before freezing; author geometry and state stay unchanged.
  $requestDocument.source.manifest.path=$sourceManifest
  $requestDocument.receiver.manifest.path=$receiverManifest
  $requestDocument.composition_plan.path=$parentPlan
  Write-RunJson -Path $frozenRequest -Depth 100 -Value $requestDocument
  $configuration=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
  $configuration.inputs=[ordered]@{request=$frozenRequest;source_manifest=$sourceManifest;receiver_manifest=$receiverManifest;code_inventory=$frozen.code_inventory_path;dependency_contract=$frozen.dependency_contract_path}
  foreach($identity in $frozen.identities){$configuration.inputs[$identity.frozen_input_name]=$identity.snapshot_path}
  Write-RunJson -Path $package.run_config -Depth 50 -Value $configuration
  $stage='prepare'
  $lease=Enter-HostExecutionLease -Role GATE
  $log=Join-Path $package.log_dir 'prepare.log'
  try{
    Invoke-RunToolRootContext -RepoRoot $frozen.execution_root -Operation {
      & $python -B -m integrations.workflows.multipole_ip.prepare --request $frozenRequest --run $package.artifact_run_dir 2>&1|Tee-Object -FilePath $log
      if($LASTEXITCODE-ne0){throw "Multipole to IP preparation failed; see $log"}
    }
  }finally{
    $parentInput=Join-Path $package.input_dir 'parent_composition_plan.json'
    if(Test-Path -LiteralPath $parentInput){
      $configuration.inputs.composition_plan=$parentInput
      Write-RunJson -Path $package.run_config -Depth 50 -Value $configuration
    }
  }
  Exit-HostExecutionLease -Lease $lease;$lease=$null
  $receipt=Get-Content -LiteralPath (Join-Path $package.result_dir 'multipole_ip/preparation_receipt.json') -Raw|ConvertFrom-Json -AsHashtable
  foreach($name in @('clock_authority','instrument_epoch')){$configuration.inputs[$name]=Join-Path $package.input_dir "$name.json"}
  Write-RunJson -Path $package.run_config -Depth 50 -Value $configuration
  Write-RunJson -Path $package.summary -Depth 40 -Value ([ordered]@{schema_version=1;role='multipole_ip_preparation_run_summary';status='success';preparation=$receipt})
  $stage='terminal_publication'
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config
  $terminal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity -RemainingCommittedNewBytes 0
  $capacity=$terminal.session
  Write-RunJson -Path (Join-Path $package.result_dir 'artifact_capacity_gate_terminal.json') -Depth 14 -Value $terminal
  $outputs=@(Get-ChildItem -LiteralPath $package.result_dir -Recurse -File|ForEach-Object{$_.FullName})+@($package.summary,$log,$retention)
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Status success -Software @('Python 3.11') -Outputs $outputs
  $terminalized=$true
  Write-Output "MULTIPOLE_IP_PREPARATION=PASS RUN_ID=$RunId SOLVER_EXECUTED=False"
}catch{
  if(-not$terminalized){
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Summary $package.summary `
      -SummaryRole multipole_ip_preparation_run_summary -Reason $_.Exception.Message -Software @('Python 3.11') -Status failed -FailureStage $stage
  }
  throw
}finally{
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease}
  if($null-ne$capacity){$null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity}
}
