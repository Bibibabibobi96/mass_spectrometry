[CmdletBinding(SupportsShouldProcess)]
param(
  [Parameter(Mandatory)][string]$ArtifactRoot,
  [Parameter(Mandatory)][string]$RepositoryRoot,
  [Parameter(Mandatory)][string]$TargetRun,
  [string]$ReplacementRun='',
  [string]$CompatibilityAssertion='',
  [string]$Owner='',
  [string]$OwnerAbandonmentReason='',
  [string]$RuntimeCheckpoint='',
  [switch]$ConfirmWritingStopped,
  [string[]]$ApprovedStoppedConsumers=@(),
  [string[]]$CompatibilityInputRoles=@(),
  [string[]]$CompatibilityInputRoleMaps=@(),
  [string[]]$SelectedHeavyPaths=@(),
  [string]$RepairPreservedFile='',
  [string]$RepairEvidenceRun='',
  [string]$ExpectedManifestSha256='',
  [string]$ExpectedRetirementSha256='',
  [switch]$Apply
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\host_execution_lease.ps1')
$python = Join-Path $RepositoryRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { $python = 'python' }
$arguments = @('-m','common.contracts.solver_review_retirement','--artifact-root',$ArtifactRoot,
  '--repository-root',$RepositoryRoot,'--target-run',$TargetRun)
if($RepairPreservedFile){
  if(-not$Owner.Trim()-or-not$ConfirmWritingStopped-or-not$RepairEvidenceRun-or
     -not$ExpectedManifestSha256-or-not$ExpectedRetirementSha256-or$ReplacementRun-or
     $CompatibilityAssertion-or$OwnerAbandonmentReason-or$RuntimeCheckpoint-or
     $ApprovedStoppedConsumers.Count-or$CompatibilityInputRoles.Count-or$CompatibilityInputRoleMaps.Count-or$SelectedHeavyPaths.Count){
    throw 'Preserved payload repair requires owner, stopped-writing confirmation, audit run and original SHA identities; retirement options are forbidden.'
  }
  $arguments+=@('--repair-preserved-file',$RepairPreservedFile,'--repair-evidence-run',$RepairEvidenceRun,
    '--expected-manifest-sha256',$ExpectedManifestSha256,'--expected-retirement-sha256',$ExpectedRetirementSha256,
    '--owner',$Owner,'--confirm-writing-stopped')
  if(-not$Apply){& $python @arguments;exit $LASTEXITCODE}
  if(-not$PSCmdlet.ShouldProcess($TargetRun,'replace one preserved PA object with verified identical bytes; retain old object')){return}
  . (Join-Path $PSScriptRoot 'run_artifact_support.ps1')
  $lease=Enter-HostExecutionLease -Role GATE -Stage artifact_retirement -RunId ([IO.Path]::GetFileName($RepairEvidenceRun))
  $session=$null
  try{
    $raw=@(& $python @arguments)
    if($LASTEXITCODE-ne0){throw 'Preserved payload repair preflight failed.'}
    $plan=($raw-join"`n")|ConvertFrom-Json
    $session=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $RepositoryRoot -ArtifactRoot $ArtifactRoot `
      -RunDirectory $RepairEvidenceRun -CommittedNewBytes ([long]$plan.committed_new_bytes) `
      -ProtectedPaths @($TargetRun,$RepairEvidenceRun) -Owner "owned-payload-view-repair:$($Owner):$([IO.Path]::GetFileName($RepairEvidenceRun))"
    & $python @arguments --capacity-lease-id $session.lease_id --apply
    if($LASTEXITCODE-ne0){throw 'Preserved payload repair failed; retain its pending audit and replay the same identities.'}
  }finally{
    try{
      if($session){$null=Exit-ArtifactWorkflowCapacitySession -Session $session -Python $python -RepoRoot $RepositoryRoot}
    }finally{Exit-HostExecutionLease -Lease $lease}
  }
  return
}
if($RepairEvidenceRun-or$ExpectedManifestSha256-or$ExpectedRetirementSha256){throw 'Repair options require RepairPreservedFile.'}
if ($Owner -or $OwnerAbandonmentReason) {
  if (-not $Owner.Trim() -or -not $OwnerAbandonmentReason.Trim()) {
    throw 'Owner completion requires owner and a nonempty abandonment reason.'
  }
  if ($ReplacementRun -or $CompatibilityAssertion -or $CompatibilityInputRoles.Count -or $CompatibilityInputRoleMaps.Count) {
    throw 'Owner completion and superseded modes are mutually exclusive.'
  }
  $arguments += @('--owner',$Owner,'--owner-abandonment-reason',$OwnerAbandonmentReason)
} else {
  if (-not $ReplacementRun -or -not $CompatibilityAssertion) {
    throw 'Superseded mode requires replacement and compatibility assertion.'
  }
  if ($CompatibilityInputRoles.Count -eq 0 -and $CompatibilityInputRoleMaps.Count -eq 0) {
    throw 'At least one compatibility input role or role mapping is required.'
  }
  $arguments += @('--replacement-run',$ReplacementRun,'--compatibility-assertion',$CompatibilityAssertion)
}
foreach ($role in $CompatibilityInputRoles) { $arguments += @('--compatibility-input-role',$role) }
foreach ($mapping in $CompatibilityInputRoleMaps) { $arguments += @('--compatibility-input-role-map',$mapping) }
foreach ($path in $SelectedHeavyPaths) { $arguments += @('--selected-heavy-path',$path) }
if ($RuntimeCheckpoint -or $ConfirmWritingStopped) {
  if (-not $Owner.Trim() -or -not $OwnerAbandonmentReason.Trim() -or -not $RuntimeCheckpoint -or -not $ConfirmWritingStopped) {
    throw 'Stopped runtime retirement requires owner, abandonment reason, checkpoint and stopped-writing confirmation.'
  }
  $arguments += @('--runtime-checkpoint',$RuntimeCheckpoint,'--confirm-writing-stopped')
}
if ($ApprovedStoppedConsumers.Count -gt 0) {
  if (-not $RuntimeCheckpoint -or -not $ConfirmWritingStopped -or -not $Owner.Trim() -or -not $OwnerAbandonmentReason.Trim()) {
    throw 'Stopped consumer approval requires the confirmed owner runtime retirement scope.'
  }
  foreach ($consumer in $ApprovedStoppedConsumers) { $arguments += @('--approved-stopped-consumer',$consumer) }
}
if (-not $Apply) { & $python @arguments; exit $LASTEXITCODE }
if (-not $PSCmdlet.ShouldProcess($TargetRun, "retire governed solver_review heavy payload")) { return }
$lease = Enter-HostExecutionLease -Role GATE -Stage artifact_retirement -RunId ([IO.Path]::GetFileName($TargetRun))
try {
  & $python @arguments --apply
  if ($LASTEXITCODE -ne 0) { throw "solver_review retirement failed with exit code $LASTEXITCODE" }
  try {
    if ($SelectedHeavyPaths.Count -gt 0) {
      Write-Warning 'Partial payload retirement complete; public capacity reseal pending. Use seal-stopped-payload with the original owner and retention reason.'
    } else {
    $runConfig = Join-Path $TargetRun 'run_config.json'
    $config = Get-Content -LiteralPath $runConfig -Raw | ConvertFrom-Json -AsHashtable
    if ($config.ContainsKey('capacity_ledger_lifecycle') -and
        $config['capacity_ledger_lifecycle']['enabled'] -eq $true -and -not $RuntimeCheckpoint) {
      # Keep the retirement receipt as the wrapper's sole JSON stdout document.
      $null = & $python -m common.contracts.run_capacity_lifecycle --action finalize-ready --artifact-root $ArtifactRoot --run-config $runConfig
      if ($LASTEXITCODE -ne 0) { throw "finalize-ready failed with exit code $LASTEXITCODE" }
    }
    }
  } catch {
    throw "Payload retirement completed, but capacity ledger finalization is pending; recover with run_capacity_lifecycle, do not repeat deletion. $($_.Exception.Message)"
  }
} finally {
  Exit-HostExecutionLease -Lease $lease
}
