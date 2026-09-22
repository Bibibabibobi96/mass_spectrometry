[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$FrozenInputDirectory,
  [ValidatePattern('^[0-9A-Fa-f]{64}$')][string]$TransactionCacheKey='',
  [string[]]$RecoverMembers=@(),
  [string[]]$RecoverRetainedInventoryMembers=@(),
  [string]$CorrectPublishedInventoryMember='',
  [string]$RunId='',
  [string]$SimionExe='',
  [string]$PythonExe=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

# Build the only runtime-safe source bank for the full native corridor.  This
# never opens C4's published native members: all paN files below are created in
# this transaction's private staging, exported as new standalone PA objects,
# verified, then atomically published with the response-set receipt.
$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$projectRoot=Join-Path $repoRoot "projects\$projectId"
$artifactRoot=Join-Path $workspaceRoot 'artifacts'
$projectArtifactRoot=Join-Path $artifactRoot "projects\$projectId"
$cacheRoot=Join-Path $artifactRoot 'common\simion\pa_family_cache'
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$simion=if($SimionExe){[IO.Path]::GetFullPath($SimionExe)}else{Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'}
$frozen=(Resolve-Path -LiteralPath $FrozenInputDirectory).Path
$freezeManifest=Join-Path $frozen 'native_corridor_freeze_manifest.json'
$recipePath=Join-Path $frozen 'native_corridor_response_recipe.json'
$planPath=Join-Path $frozen 'native_corridor_plan.json'
$bankModule='projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_corridor_response_bank'
$bankMembers=@('mrtof_analyzer_corridor.pa#')+@(1..8|ForEach-Object{'mrtof_analyzer_corridor.pa{0}'-f$_})+@(1..8|ForEach-Object{'mrtof_analyzer_corridor.response{0}.pa'-f$_})+@('mrtof_analyzer_corridor.standalone_responses.json')
$pinReason='MR-TOF detached native-corridor response bank required to construct private Fast Adjust execution families'
foreach($path in @($python,$simion,$freezeManifest,$recipePath,$planPath)){if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Required response-bank input is missing: $path"}}
if(-not$RunId){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__build__simion__mrtof-native-corridor-response-bank'}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\parallel_gate_support.ps1')

function Invoke-ProjectPython {
  param([Parameter(Mandatory)][string[]]$Arguments)
  $output=@(Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
    & $python @Arguments
    if($LASTEXITCODE-ne0){throw "Python stage failed: $($Arguments -join ' ')"}
  })
  return $output
}

function Invoke-Transaction {
  param([Parameter(Mandatory)][string]$IdentityPath,[string]$VerificationEvidence='',[string]$MemberRecovery='',[string]$ResponseReceipt='',[string]$RetainedInventoryRecovery='',[string]$PublicationMetadataCorrection='')
  $arguments=@('-m','common.simion.pa_family_cache','--action','advance-transaction','--cache-root',$cacheRoot,
    '--identity',$IdentityPath,'--filenames',($bankMembers-join','),'--recovery-policy','none',
    '--published-pin-reason',$pinReason)
  if($VerificationEvidence){$arguments+=@('--verification-evidence',$VerificationEvidence)}
  if($MemberRecovery){$arguments+=@('--member-recovery',$MemberRecovery)}
  if($ResponseReceipt){$arguments+=@('--response-receipt',$ResponseReceipt)}
  if($RetainedInventoryRecovery){$arguments+=@('--retained-inventory-recovery',$RetainedInventoryRecovery)}
  if($PublicationMetadataCorrection){$arguments+=@('--publication-metadata-correction',$PublicationMetadataCorrection)}
  return ((@(Invoke-ProjectPython -Arguments $arguments)-join"`n")|ConvertFrom-Json -Depth 40)
}

function Select-FrozenTransactionIdentity {
  param([Parameter(Mandatory)]$CurrentIdentity,[Parameter(Mandatory)]$Transaction,[switch]$AllowPublishedReuse)
  # A started build retains its frozen content identity. Only the receipt
  # validator may change; all physical inputs and PA-producing code must match.
  $publishedReuse=$AllowPublishedReuse-and[string]$Transaction.status-eq'published'-and$null-ne$Transaction.verification-and$null-ne$Transaction.generation_sha256
  if(-not$publishedReuse-and([string]$Transaction.status-ne'building'-or$null-ne$Transaction.verification-or$null-ne$Transaction.generation_sha256)){throw 'Frozen identity continuation requires an unverified building transaction.'}
  $comparison=$CurrentIdentity|ConvertTo-Json -Depth 60|ConvertFrom-Json -Depth 60
  $comparison.builder_identity.response_set_contract_sha256=$Transaction.identity.builder_identity.response_set_contract_sha256
  if(($comparison|ConvertTo-Json -Depth 60 -Compress)-cne($Transaction.identity|ConvertTo-Json -Depth 60 -Compress)){throw 'Frozen response-bank physics or PA builder identity differs.'}
  return $Transaction.identity
}

function New-ResponseBankMemberRecovery {
  param([Parameter(Mandatory)]$Transaction,[Parameter(Mandatory)]$Receipt,[Parameter(Mandatory)][string[]]$Names)
  $members=@()
  if(@($Names|Sort-Object -Unique).Count-ne$Names.Count){throw 'Recovery members must be unique.'}
  foreach($name in $Names){
    $sealed=@($Transaction.files|Where-Object name -CEQ $name)
    if($sealed.Count-ne1){throw "Recovery member is not a unique sealed member: $name"}
    $matches=@()
    for($index=0;$index-lt$Receipt.responses.Count;$index++){
      foreach($role in @('source','standalone')){
        $expected=$Receipt.responses[$index].$role
        if([string]$expected.name-ceq$name){$matches+=@(@{sealed=$sealed[0];expected=$expected;receipt_record_path=@('responses',$index,$role)})}
      }
    }
    if($sealed.Count-ne1-or$matches.Count-ne1){throw "Recovery member is not a unique response: $name"}
    if([string]$sealed[0].sha256-ceq[string]$matches[0].expected.sha256-and[int64]$sealed[0].bytes-eq[int64]$matches[0].expected.bytes){throw "Recovery member has no receipt mismatch: $name"}
    $members+=$matches
  }
  $receiptRecord=@($Transaction.files|Where-Object name -CEQ 'mrtof_analyzer_corridor.standalone_responses.json')
  if($receiptRecord.Count-ne1){throw 'Recovery requires one sealed response receipt.'}
  return [ordered]@{schema_version=1;role='simion_pa_family_member_recovery';cache_key=$Transaction.cache_key;owner=$Transaction.owner;inventory_sha256=$Transaction.inventory_sha256;receipt=$receiptRecord[0];members=$members}
}

function Invoke-CacheProbe {
  param([Parameter(Mandatory)][string]$IdentityPath)
  $arguments=@('-m','common.simion.pa_family_cache','--action','probe','--cache-root',$cacheRoot,
    '--identity',$IdentityPath,'--filenames',($bankMembers-join','))
  return ((@(Invoke-ProjectPython -Arguments $arguments)-join"`n")|ConvertFrom-Json -Depth 40)
}

function Move-NewMember {
  param([Parameter(Mandatory)][string]$Source,[Parameter(Mandatory)][string]$Destination)
  if(-not(Test-Path -LiteralPath $Source -PathType Leaf)){throw "Response-bank member was not produced: $Source"}
  if(Test-Path -LiteralPath $Destination){throw "Response-bank member is already present: $Destination"}
  Move-Item -LiteralPath $Source -Destination $Destination
}

function Get-CoarseInputs {
  $recipe=Get-Content -LiteralPath $recipePath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 40
  $key=([string]$recipe.coarse_raw_generation_identity.cache_key).ToUpperInvariant()
  $generation=([string]$recipe.coarse_raw_generation_identity.generation_sha256).ToUpperInvariant()
  if($key-notmatch'^[0-9A-F]{64}$'-or$generation-notmatch'^[0-9A-F]{64}$'){throw 'Frozen response recipe has invalid coarse generation identity.'}
  $directory=Join-Path $cacheRoot "$key\generations\$generation"
  $raw=Join-Path $directory ([string]$recipe.coarse_raw_member.name)
  $manifest=Get-Content -LiteralPath (Join-Path $directory 'cache_manifest.json') -Raw -Encoding UTF8|ConvertFrom-Json -Depth 30
  if(-not(Test-Path -LiteralPath $raw -PathType Leaf)){throw 'Frozen coarse raw geometry is unavailable.'}
  return [pscustomobject]@{raw=$raw;origin=(@($manifest.identity.grid_phase.analyzer_origin_mm)-join',')}
}

function Get-ResponseBankPeakBytes {
  $plan=Get-Content -LiteralPath $planPath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 30
  [int64]$familyBytes=$plan.family_bytes
  [int64]$nativeMembers=$plan.native_family_members
  # A response bank has raw geometry plus eight native and eight detached
  # response arrays.  The physical-ID compilation intermediate is explicitly
  # released before any response construction, so it is not part of the
  # workflow peak.  The receipt is negligible and recorded at publication.
  [int64]$arrayMembers=$bankMembers.Count-1
  if($familyBytes-le0-or$nativeMembers-le0-or($familyBytes%$nativeMembers)-ne0){throw 'Frozen native corridor plan has no integral PA-array byte estimate.'}
  return ($familyBytes/$nativeMembers)*$arrayMembers
}

function Get-ExistingTransactionPayloadBytes {
  param([Parameter(Mandatory)][string]$CacheKey)
  $payload=Join-Path $cacheRoot ('.transactions\'+$CacheKey+'\payload')
  if(-not(Test-Path -LiteralPath $payload -PathType Container)){return [int64]0}
  return [int64](Get-ChildItem -LiteralPath $payload -File -ErrorAction Stop|Measure-Object -Property Length -Sum).Sum
}

function Build-RawGeometry {
  param([Parameter(Mandatory)][string]$BuildDirectory,[Parameter(Mandatory)][string]$ScratchDirectory)
  $destination=Join-Path $BuildDirectory 'mrtof_analyzer_corridor.pa#'
  if(Test-Path -LiteralPath $destination -PathType Leaf){return}
  $aliases=@();$lease=$null
  try {
    $buildAlias=New-RunExecutionAlias -TargetDirectory $BuildDirectory;$aliases+=@($buildAlias)
    $scratchAlias=New-RunExecutionAlias -TargetDirectory $ScratchDirectory;$aliases+=@($scratchAlias)
    $gem=Join-Path ([string]$scratchAlias.execution_alias) 'mrtof_analyzer_corridor.gem'
    $physical=Join-Path ([string]$scratchAlias.execution_alias) 'physical_corridor.pa#'
    $raw=Join-Path ([string]$scratchAlias.execution_alias) 'mrtof_analyzer_corridor.pa#'
    & $python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_corridor_geometry --contract (Join-Path $projectRoot 'config\simion_candidate_two_zone.json') --output $gem
    if($LASTEXITCODE-ne0){throw 'Canonical native corridor GEM generation failed.'}
    # The generator reads the current contract only as a deterministic compiler;
    # the frozen package remains authoritative.  A changed contract must fail
    # here rather than silently create a bank under stale frozen identity.
    $frozenIdentity=Get-Content -LiteralPath (Join-Path $frozen 'native_corridor_identity.json') -Raw -Encoding UTF8|ConvertFrom-Json -Depth 30
    $generatedGemHash=(Get-FileHash -LiteralPath (Join-Path $ScratchDirectory 'mrtof_analyzer_corridor.gem') -Algorithm SHA256).Hash.ToUpperInvariant()
    if($generatedGemHash-ne[string]$frozenIdentity.gem.sha256){throw 'Current corridor compiler output differs from the frozen native geometry identity.'}
    $plan=Get-Content -LiteralPath $planPath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 30
    $mapping=@($plan.physical_to_local_electrode_id.PSObject.Properties|Sort-Object {[int]$_.Name}|ForEach-Object{"$($_.Name):$($_.Value)"})-join','
    $lease=Enter-HostExecutionLease -Role SIMION -Stage pa_refine -RunId $RunId
    & $simion --nogui --noprompt gem2pa $gem $physical
    if($LASTEXITCODE-ne0){throw 'Native corridor GEM compilation failed.'}
    & $simion --nogui --noprompt lua (Join-Path $repoRoot 'common\simion\remap_pa_electrode_ids.lua') $physical $raw $mapping
    if($LASTEXITCODE-ne0){throw 'Native corridor electrode remap failed.'}
    Remove-Item -LiteralPath (Join-Path $ScratchDirectory 'physical_corridor.pa#') -Force
    Move-NewMember -Source (Join-Path $ScratchDirectory 'mrtof_analyzer_corridor.pa#') -Destination $destination
    Exit-HostExecutionLease -Lease $lease -Outcome success -RunId $RunId;$lease=$null
  } finally {
    if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome failed -RunId $RunId}
    foreach($alias in @($aliases)){Remove-RunExecutionAlias -ExecutionAlias ([string]$alias.execution_alias) -TargetDirectory ([string]$alias.target_directory)}
  }
}

function Build-DetachedResponse {
  param([Parameter(Mandatory)][ValidateRange(1,8)][int]$ResponseId,[Parameter(Mandatory)][string]$BuildDirectory,[Parameter(Mandatory)][string]$ScratchDirectory,[Parameter(Mandatory)]$Coarse)
  $nativeName='mrtof_analyzer_corridor.pa{0}'-f$ResponseId
  $detachedName='mrtof_analyzer_corridor.response{0}.pa'-f$ResponseId
  $native=Join-Path $BuildDirectory $nativeName;$detached=Join-Path $BuildDirectory $detachedName
  if(-not(Test-Path -LiteralPath $native -PathType Leaf)){
    & (Join-Path $PSScriptRoot 'run_native_corridor_qualification.ps1') -FrozenInputDirectory $frozen -RunId $RunId `
      -SimionExe $simion -PythonExe $python -InternalResponseId $ResponseId -InternalBuildDirectory $BuildDirectory `
      -InternalScratchDirectory $ScratchDirectory -InternalCoarseRawGeometryPath $Coarse.raw -InternalCoarseOrigin $Coarse.origin
    if($LASTEXITCODE-ne0){throw "Private native response build failed for ID $ResponseId"}
  }
  if(Test-Path -LiteralPath $detached -PathType Leaf){return}
  $alias=$null;$lease=$null
  try {
    $alias=New-RunExecutionAlias -TargetDirectory $BuildDirectory
    $lease=Enter-HostExecutionLease -Role SIMION -Stage prepare -RunId $RunId
    & $simion --nogui --noprompt lua (Join-Path $repoRoot 'common\simion\export_standalone_pa.lua') `
      (Join-Path ([string]$alias.execution_alias) $nativeName) (Join-Path ([string]$alias.execution_alias) $detachedName)
    if($LASTEXITCODE-ne0){throw "Detached response export failed for ID $ResponseId"}
    Exit-HostExecutionLease -Lease $lease -Outcome success -RunId $RunId;$lease=$null
  } finally {
    if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome failed -RunId $RunId}
    if($null-ne$alias){Remove-RunExecutionAlias -ExecutionAlias ([string]$alias.execution_alias) -TargetDirectory ([string]$alias.target_directory)}
  }
}

function Verify-PrivateResponseBank {
  param([Parameter(Mandatory)][string]$BuildDirectory,[Parameter(Mandatory)][string]$OutputPath)
  $alias=$null;$lease=$null
  try {
    $alias=New-RunExecutionAlias -TargetDirectory $BuildDirectory
    $arguments=@((Join-Path ([string]$alias.execution_alias) 'mrtof_analyzer_corridor.pa#'))
    foreach($identifier in 1..8){$arguments+=@( (Join-Path ([string]$alias.execution_alias) ('mrtof_analyzer_corridor.pa{0}'-f$identifier)),(Join-Path ([string]$alias.execution_alias) ('mrtof_analyzer_corridor.response{0}.pa'-f$identifier)) )}
    $lease=Enter-HostExecutionLease -Role SIMION -Stage prepare -RunId $RunId
    $lines=@(& $simion --nogui --noprompt lua (Join-Path $PSScriptRoot 'verify_native_corridor_response_bank.lua') @arguments 2>&1|Tee-Object -FilePath $OutputPath)
    if($LASTEXITCODE-ne0-or-not(@($lines|ForEach-Object{"$_"})-contains'MRTOF_NATIVE_CORRIDOR_RESPONSE_BANK_VERIFY=PASS responses=8 detached_runtime_only=true')){throw 'Private response-bank SIMION verification failed.'}
    Exit-HostExecutionLease -Lease $lease -Outcome success -RunId $RunId;$lease=$null
  } finally {
    if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome failed -RunId $RunId}
    if($null-ne$alias){Remove-RunExecutionAlias -ExecutionAlias ([string]$alias.execution_alias) -TargetDirectory ([string]$alias.target_directory)}
  }
}

$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $projectArtifactRoot -RunId $RunId `
  -Project $projectId -Mode 'native_corridor_detached_response_bank' -Software @('SIMION 2020','Python 3.11') `
  -RetentionContractEnabled -RetentionClass compact -CapacityLedgerLifecycleEnabled -UseShortExecutionPath
$resultDir=$package.result_dir;$summary=$package.summary;$runConfig=$package.run_config
$identityPath=Join-Path $resultDir 'response_bank_identity.json';$verificationLog=Join-Path $resultDir 'response_bank_private_verify.log';$evidencePath=Join-Path $resultDir 'response_bank_verification.json'
$terminalized=$false;$failureStage='identity';$capacitySession=$null;$publication=$null
$continuationOutputs=@();$memberRecoveryPath='';$retainedInventoryRecoveryPath='';$publishedReuse=$false
$publicationCorrectionPath='';$correctPublication=-not[string]::IsNullOrWhiteSpace($CorrectPublishedInventoryMember)
try {
  Invoke-ProjectPython -Arguments @('-m',$bankModule,'--frozen-input-directory',$frozen,'--simion-executable',$simion,'--simion-release','SIMION 2020','--output',$identityPath)|Out-Null
  if($RecoverMembers.Count-gt0-and-not$TransactionCacheKey){throw 'Member recovery requires an explicit frozen transaction key.'}
  if($RecoverRetainedInventoryMembers.Count-gt0-and(-not$TransactionCacheKey-or$RecoverMembers.Count-gt0)){throw 'Retained inventory repair requires an explicit frozen transaction and cannot rebuild members.'}
  if($correctPublication-and(-not$TransactionCacheKey-or$RecoverMembers.Count-gt0-or$RecoverRetainedInventoryMembers.Count-gt0)){throw 'Published inventory correction requires one explicit transaction and cannot rebuild members.'}
  if($TransactionCacheKey){
    $transactionPath=Join-Path $cacheRoot ('.transactions/'+$TransactionCacheKey.ToUpperInvariant()+'/transaction.json')
    $transaction=Get-Content -LiteralPath $transactionPath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 60
    $currentIdentity=Get-Content -LiteralPath $identityPath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 60
    $isPublished=[string]$transaction.status-eq'published'
    $publishedReuse=$isPublished-and-not$correctPublication
    if($isPublished-and($RecoverMembers.Count-gt0-or$RecoverRetainedInventoryMembers.Count-gt0)){throw 'Published bank reuse cannot recover or rebuild members.'}
    if($correctPublication-and-not$isPublished){throw 'Published inventory correction requires a published transaction.'}
    $frozenIdentity=Select-FrozenTransactionIdentity -CurrentIdentity $currentIdentity -Transaction $transaction -AllowPublishedReuse:$isPublished
    $continuationPath=Join-Path $resultDir 'response_bank_identity_continuation.json'
    Write-RunJson -Path $continuationPath -Depth 60 -Value ([ordered]@{schema_version=1;role='mrtof_response_bank_frozen_identity_continuation';cache_key=$TransactionCacheKey.ToUpperInvariant();transaction_sha256=(Get-FileHash -LiteralPath $transactionPath -Algorithm SHA256).Hash;frozen_identity=$frozenIdentity;current_execution_identity=$currentIdentity})
    $continuationOutputs+=@($continuationPath)
    Write-RunJson -Path $identityPath -Depth 60 -Value $frozenIdentity
    if($publishedReuse){
      $verifiedOutput=[string]$transaction.verification.verification_output_path
      if((Get-FileHash -LiteralPath $verifiedOutput -Algorithm SHA256).Hash-ne[string]$transaction.verification.verification_output_sha256){throw 'Published bank verification evidence changed.'}
      $null=Copy-VerifiedRunInput -Source $verifiedOutput -Destination $verificationLog
      Write-RunJson -Path $evidencePath -Depth 20 -Value $transaction.verification
    }
    if($RecoverRetainedInventoryMembers.Count-gt0){
      $retainedInventoryRecoveryPath=Join-Path $resultDir 'response_bank_retained_inventory_recovery.json'
      Write-RunJson -Path $retainedInventoryRecoveryPath -Depth 20 -Value ([ordered]@{
        schema_version=1;cache_key=$TransactionCacheKey.ToUpperInvariant();owner=$transaction.owner
        inventory_sha256=$transaction.inventory_sha256;names=@($RecoverRetainedInventoryMembers)
      })
      $continuationOutputs+=@($retainedInventoryRecoveryPath)
    }
    if($RecoverMembers.Count-gt0){
      $receipt=Get-Content -LiteralPath (Join-Path (Split-Path -Parent $transactionPath) 'payload/mrtof_analyzer_corridor.standalone_responses.json') -Raw -Encoding UTF8|ConvertFrom-Json -Depth 30
      $memberRecoveryPath=Join-Path $resultDir 'response_bank_member_recovery.json'
      Write-RunJson -Path $memberRecoveryPath -Depth 40 -Value (New-ResponseBankMemberRecovery -Transaction $transaction -Receipt $receipt -Names $RecoverMembers)
      $continuationOutputs+=@($memberRecoveryPath)
    }
  }
  # A pending owner correction deliberately withdraws the old pointer.  The
  # explicit transaction identifies this operation; it must not fall through
  # the ordinary cache-miss/build path on retry.
  $probe=if($correctPublication){[pscustomobject]@{cache_key=$transaction.cache_key;disposition='publication_metadata_correction'}}else{Invoke-CacheProbe -IdentityPath $identityPath}
  if($TransactionCacheKey-and[string]$probe.cache_key-cne$TransactionCacheKey.ToUpperInvariant()){throw 'Frozen response-bank transaction key differs.'}
  $responseReceiptPath=''
  $receiptAlreadyPresent=Test-Path -LiteralPath (Join-Path $cacheRoot ('.transactions/'+[string]$probe.cache_key+'/payload/mrtof_analyzer_corridor.standalone_responses.json'))
  # Continue legacy sealed receipts as they stand; new builds and explicit
  # member recovery let the common owner derive receipt from its sole scan.
  if(-not$correctPublication-and[string]$probe.disposition-ne'hit'-and(-not$receiptAlreadyPresent-or$RecoverMembers.Count-gt0)){
    $responseReceiptPath=Join-Path $resultDir 'response_bank_receipt_recipe.json'
    Write-RunJson -Path $responseReceiptPath -Depth 20 -Value ([ordered]@{
      schema_version=1;receipt_name='mrtof_analyzer_corridor.standalone_responses.json'
      exporter_path=(Join-Path $repoRoot 'common\simion\export_standalone_pa.lua')
      exports=@(1..8|ForEach-Object{[ordered]@{
        response_id=$_;source_name=('mrtof_analyzer_corridor.pa{0}'-f$_)
        standalone_name=('mrtof_analyzer_corridor.response{0}.pa'-f$_)
      }})
    })
    $continuationOutputs+=@($responseReceiptPath)
  }
  # A resumed transaction already occupies its payload bytes.  Reserve only
  # space still capable of being added; otherwise a failed final seal can
  # falsely block its own no-Refine recovery.
  [int64]$peakBytes=0
  if(-not$correctPublication-and[string]$probe.disposition-ne'hit'){
    [int64]$existingPayloadBytes=Get-ExistingTransactionPayloadBytes -CacheKey ([string]$probe.cache_key)
    [int64]$remainingPeakBytes=(Get-ResponseBankPeakBytes)-$existingPayloadBytes
    $peakBytes=[math]::Max([int64]0,$remainingPeakBytes)
  }
  if($RecoverRetainedInventoryMembers.Count-gt0){
    [int64]$snapshotBytes=(@($transaction.files|Where-Object{$_.name-in$RecoverRetainedInventoryMembers})|Measure-Object -Property bytes -Maximum).Maximum
    $peakBytes=[math]::Max($peakBytes,$snapshotBytes)
  }
  $coarseRecipe=Get-Content -LiteralPath $recipePath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 40
  $coarseKey=([string]$coarseRecipe.coarse_raw_generation_identity.cache_key).ToUpperInvariant()
  $capacitySession=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -RunDirectory $package.artifact_run_dir -CommittedNewBytes $peakBytes -ProtectedPaths @($package.artifact_run_dir,$frozen,(Join-Path $cacheRoot ('.transactions\'+([string]$probe.cache_key)+'\payload'))) `
    -ProtectedCacheKeys @([string]$probe.cache_key,$coarseKey) -Owner "mrtof-native-corridor-response-bank:$RunId"
  if($correctPublication){
    $priorCorrection=$transaction.PSObject.Properties['publication_metadata_correction']
    if($null-ne$priorCorrection){
      $correctionRequest=$priorCorrection.Value.request|ConvertTo-Json -Depth 30|ConvertFrom-Json -AsHashtable
      if([string]$correctionRequest.member_name-cne$CorrectPublishedInventoryMember){throw 'Published inventory correction retry selects a different member.'}
    }else{
      $sealed=@($transaction.files|Where-Object name -CEQ $CorrectPublishedInventoryMember)
      $retained=@($transaction.member_recovery.files|Where-Object name -CEQ $CorrectPublishedInventoryMember)
      if($sealed.Count-ne1-or$retained.Count-ne1){throw 'Published inventory correction requires one original retained inventory member.'}
      $correctionRequest=[ordered]@{schema_version=1;cache_key=$transaction.cache_key;owner=$transaction.owner;
        generation_sha256=$transaction.generation_sha256;inventory_sha256=$transaction.inventory_sha256;
        member_name=$CorrectPublishedInventoryMember;sealed_sha256=$sealed[0].sha256;retained_sha256=$retained[0].sha256}
    }
    $correctionRequest.capacity_lease_id=$capacitySession.lease_id
    $correctionRequest.capacity_lease_owner=$capacitySession.owner
    $publicationCorrectionPath=Join-Path $resultDir 'response_bank_publication_metadata_correction_request.json'
    Write-RunJson -Path $publicationCorrectionPath -Depth 30 -Value $correctionRequest
    $continuationOutputs+=@($publicationCorrectionPath)
  }
  $evidence=''
  for($step=0;$step-lt4;$step++){
    $state=Invoke-Transaction -IdentityPath $identityPath -VerificationEvidence $evidence -MemberRecovery $memberRecoveryPath -ResponseReceipt $responseReceiptPath -RetainedInventoryRecovery $retainedInventoryRecoveryPath -PublicationMetadataCorrection $publicationCorrectionPath
    $memberRecoveryPath=''
    $retainedInventoryRecoveryPath=''
    if([string]$state.action_required-eq'complete'){
      $publication=$state;break
    }
    if($correctPublication){throw 'Published metadata correction must not build PA or reopen published native members in SIMION.'}
    if([string]$state.action_required-eq'build'){
      if($RecoverRetainedInventoryMembers.Count-gt0){throw 'Retained inventory repair must never trigger PA rebuilding.'}
      $failureStage='private_response_build'
      $build=[IO.Path]::GetFullPath([string]$state.build_directory);$scratch=[IO.Path]::GetFullPath([string]$state.scratch_directory)
      [int64]$remainingBytes=[math]::Max([int64]0,((Get-ResponseBankPeakBytes)-(Get-ExistingTransactionPayloadBytes -CacheKey ([string]$state.cache_key))))
      $reservation=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession -RemainingCommittedNewBytes $remainingBytes
      $capacitySession=$reservation.session
      New-Item -ItemType Directory -Force -Path $build,$scratch|Out-Null
      Build-RawGeometry -BuildDirectory $build -ScratchDirectory $scratch
      $coarse=Get-CoarseInputs
      foreach($identifier in 1..8){Build-DetachedResponse -ResponseId $identifier -BuildDirectory $build -ScratchDirectory $scratch -Coarse $coarse}
      if(-not$responseReceiptPath){Invoke-ProjectPython -Arguments @('-m',$bankModule,'--write-receipt-directory',$build)|Out-Null}
      $evidence='';continue
    }
    if([string]$state.action_required-eq'verify'){
      $failureStage='private_response_verify';Verify-PrivateResponseBank -BuildDirectory ([string]$state.build_directory) -OutputPath $verificationLog
      $failureStage='receipt_verify';$transactionInventory=(Join-Path ([string]$state.transaction_directory) 'transaction.json');Invoke-ProjectPython -Arguments @('-m','common.simion.standalone_pa_response_set','--validate-sealed-receipt','--generation-directory',([string]$state.build_directory),'--inventory',$transactionInventory,'--receipt-name','mrtof_analyzer_corridor.standalone_responses.json','--expected-response-ids','1,2,3,4,5,6,7,8')|Out-Null
      $outputHash=(Get-FileHash -LiteralPath $verificationLog -Algorithm SHA256).Hash.ToUpperInvariant();$verifier=(Join-Path $PSScriptRoot 'verify_native_corridor_response_bank.lua')
      Write-RunJson -Path $evidencePath -Depth 10 -Value ([ordered]@{schema_version=1;role='simion_pa_family_verification';status='pass';cache_key=[string]$state.cache_key;inventory_sha256=[string]$state.inventory_sha256;solver_release='SIMION 2020';verifier_path=$verifier;verifier_sha256=(Get-FileHash -LiteralPath $verifier -Algorithm SHA256).Hash.ToUpperInvariant();verification_output_path=$verificationLog;verification_output_sha256=$outputHash})
      $evidence=$evidencePath;continue
    }
    throw "Unsupported response-bank transaction action: $($state.action_required)"
  }
  if($null-eq$publication){throw 'Response-bank transaction did not publish within four transitions.'}
  if($correctPublication){
    $correctionReceipt=Copy-VerifiedRunInput -Source ([string]$publication.publication_metadata_correction_receipt) -Destination (Join-Path $resultDir 'response_bank_publication_metadata_correction.json')
    $continuationOutputs+=@($correctionReceipt)
  }
  $failureStage='publish_run'
  $publicationPath=Join-Path $resultDir 'pa_family_cache_publication.json';Write-RunJson -Path $publicationPath -Depth 30 -Value $publication
  $terminal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession -ProtectedCacheKeys @([string]$publication.cache_key) -RemainingCommittedNewBytes 0;$capacitySession=$terminal.session
  Write-RunJson -Path $summary -Depth 20 -Value ([ordered]@{schema_version=1;role='mrtof_native_corridor_detached_response_bank';status='success';cache_key=[string]$publication.cache_key;generation_sha256=[string]$publication.generation_sha256;published_bank_reused=$publishedReuse;published_inventory_corrected=$correctPublication;solver_rerun_for_metadata_correction=$false;runtime_input='detached_standalone_responses_only';native_published_member_opening='forbidden'})
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $outputs=@($summary,$identityPath,$publicationPath,$retention)+$continuationOutputs
  foreach($path in @($verificationLog,$evidencePath)){if(Test-Path -LiteralPath $path -PathType Leaf){$outputs+=@($path)}}
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success -Software @('SIMION 2020','Python 3.11') -Outputs $outputs
  $terminalized=$true;Write-Host "MRTOF_NATIVE_CORRIDOR_RESPONSE_BANK=PASS RUN_ID=$RunId CACHE_KEY=$($publication.cache_key)"
} catch {
  if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_native_corridor_detached_response_bank' -Reason $_.Exception.Message -Software @('SIMION 2020','Python 3.11') -Status failed -FailureStage $failureStage;$terminalized=$true}
  throw
} finally {
  try{if($null-ne$capacitySession){$null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession}}
  finally{Remove-RunPackageExecutionAlias -Package $package}
}
