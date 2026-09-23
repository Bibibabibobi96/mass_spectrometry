Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'require_powershell7.ps1')
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'host_execution_lease.ps1')

function Invoke-RunToolRootContext {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][scriptblock]$Operation
  )
  $root=(Resolve-Path -LiteralPath $RepoRoot).Path
  $names=@('PYTHONPATH','PYTHONNOUSERSITE')
  $saved=Save-RunEnvironment -Names $names
  try{
    $env:PYTHONPATH=$root
    $env:PYTHONNOUSERSITE='1'
    Push-Location -LiteralPath $root
    try{& $Operation}finally{Pop-Location}
  }finally{
    Restore-RunEnvironment -Names $names -Snapshot $saved
  }
}

function Get-VerifiedRunManifestInputRecord {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][System.Collections.IDictionary]$Records,
    [Parameter(Mandatory)][string]$Name,
    [Parameter(Mandatory)][string]$Label
  )
  if(-not$Records.Contains($Name)-or-not($Records[$Name]-is[System.Collections.IDictionary])){
    throw "Run manifest lacks the required $Label input record."
  }
  $record=$Records[$Name]
  if(-not$record.exists-or[string]::IsNullOrWhiteSpace([string]$record.path)-or
     [string]::IsNullOrWhiteSpace([string]$record.sha256)){
    throw "Run manifest has an incomplete $Label input record."
  }
  return $record
}

function Assert-VerifiedRunRecordHash {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Path,
    [Parameter(Mandatory)][System.Collections.IDictionary]$Record,
    [Parameter(Mandatory)][string]$Label
  )
  $actual=(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
  if($actual-ne([string]$Record.sha256).ToUpperInvariant()){
    throw "Frozen $Label differs from the verified parent run manifest."
  }
}

function Invoke-ArtifactCapacityGate {
  <# Invoke the repository-owned artifact reconciler and require an applied
     receipt.  This is deliberately a lifecycle adapter: projects supply their
     own protected paths and cache identities; global watermarks come only
     from artifact_capacity_policy.json. #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$ArtifactRoot,
    [string[]]$ProtectedPaths=@(),
    [string[]]$ProtectedCacheKeys=@(),
    [string]$CapacityProtectionLeaseId='',
    [ValidateSet('startup','maintenance')][string]$ExecutionMode='startup',
    [Nullable[double]]$MaintenanceTargetGiB=$null
  )
  if($null-ne$MaintenanceTargetGiB-and$ExecutionMode-ne'maintenance'){
    throw 'MaintenanceTargetGiB requires maintenance execution mode.'
  }
  if($ExecutionMode-eq'startup'-and[string]::IsNullOrWhiteSpace($CapacityProtectionLeaseId)){
    throw 'Artifact capacity startup requires CapacityProtectionLeaseId.'
  }
  # Capacity work uses shared host admission and inherits the caller's permit.
  # Light admission is not a cache-consumption or deletion lock; the reconciler
  # must separately enforce artifact protection and retention rules.
  $capacityLease=Enter-HostExecutionLease -Role GATE
  try{
  $arguments=@(
    '-m','common.contracts.reconcile_artifact_capacity',
    '--artifact-root',$ArtifactRoot,
    '--execution-mode',$ExecutionMode,
    '--capacity-ledger',(Join-Path $ArtifactRoot 'common\capacity_ledger.json'),
    '--apply'
  )
  if($null-ne$MaintenanceTargetGiB){
    $arguments+=@('--maintenance-target-gib',([string]$MaintenanceTargetGiB))
  }
  foreach($path in @($ProtectedPaths|Where-Object{ -not [string]::IsNullOrWhiteSpace($_) }|Select-Object -Unique)){
    $arguments+=@('--protect-path',$path)
  }
  foreach($key in @($ProtectedCacheKeys|Select-Object -Unique)){
    if($key-notmatch '^[0-9a-fA-F]{64}$'){throw 'Protected cache key must be one SHA-256 key.'}
    $arguments+=@('--protect-cache-key',$key)
  }
  if(-not[string]::IsNullOrWhiteSpace($CapacityProtectionLeaseId)){
    $arguments+=@('--capacity-protection-lease-id',$CapacityProtectionLeaseId)
  }
  $output=@(Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
    & $Python @arguments
    if($LASTEXITCODE-ne 0){throw "Artifact capacity gate exit_code=$LASTEXITCODE"}
  })
  $receipt=((@($output)-join "`n")|ConvertFrom-Json)
  if($receipt.satisfied_after_apply -ne $true){
    if($ExecutionMode-eq'maintenance'){
      throw ("Artifact capacity gate blocked maintenance: CAPACITY_TARGET_NOT_MET; measured_after_bytes={0}; free_bytes_after={1}; required_free_bytes={2}; target_bytes={3}; removed_bytes={4}" -f $receipt.measured_after_bytes,$receipt.free_bytes_after,$receipt.required_free_bytes,$receipt.target_bytes,$receipt.removed_bytes)
    }
    $reason=[string]$receipt.blocking_reason
    if([string]::IsNullOrWhiteSpace($reason)){$reason='UNSPECIFIED'}
    throw ("Artifact capacity gate blocked startup: {0}; resident_bytes={1}; active_commitment_bytes={2}; projected_bytes={3}; target_bytes={4}" -f $reason,$receipt.resident_bytes,$receipt.total_active_lease_committed_new_bytes,$receipt.projected_bytes,$receipt.target_bytes)
  }
  # The JSON root is one object; NoEnumerate wraps it and changes nested-array access.
  Write-Output $receipt
  }finally{
    Exit-HostExecutionLease -Lease $capacityLease
  }
}

function Invoke-RunCapacityLifecycleAdapter {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][ValidateSet('register-writing-range','register-writing','assert-retention','finalize-ready')][string]$Action,
    [Parameter(Mandatory)][string]$ArtifactRoot,
    [string]$RunConfig='',
    [string]$RunDirectory=''
  )
  if($Action-eq'register-writing-range'){
    if([string]::IsNullOrWhiteSpace($RunDirectory)-or-not[string]::IsNullOrWhiteSpace($RunConfig)){
      throw 'register-writing-range requires RunDirectory only.'
    }
    $runArgument=@('--run-directory',$RunDirectory)
  }else{
    if([string]::IsNullOrWhiteSpace($RunConfig)-or-not[string]::IsNullOrWhiteSpace($RunDirectory)){
      throw "$Action requires RunConfig only."
    }
    $runArgument=@('--run-config',$RunConfig)
  }
  $output=@(Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
    & $Python -m common.contracts.run_capacity_lifecycle --action $Action `
      --artifact-root $ArtifactRoot @runArgument
    if($LASTEXITCODE-ne 0){throw "Run capacity lifecycle $Action failed."}
  })
  return ((@($output)-join "`n")|ConvertFrom-Json)
}

function Enter-ArtifactWorkflowCapacitySession {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$ArtifactRoot,[Parameter(Mandatory)][string]$RunDirectory,
    [Parameter(Mandatory)][long]$CommittedNewBytes,[string]$Owner='',
    [int]$LeaseTtlSeconds=21600,[string[]]$ProtectedPaths=@(),
    [string[]]$ProtectedCacheKeys=@()
  )
  if($CommittedNewBytes-lt0-or$LeaseTtlSeconds-le0){throw 'Workflow capacity session requires nonnegative bytes and a positive TTL.'}
  $leaseId='workflow-'+[guid]::NewGuid().ToString('N')
  if([string]::IsNullOrWhiteSpace($Owner)){$Owner="run-artifact-support:$([IO.Path]::GetFileName($RunDirectory))"}
  $paths=@([IO.Path]::GetFullPath($RunDirectory))+$ProtectedPaths|Select-Object -Unique
  $arguments=@('-m','common.contracts.reconcile_artifact_capacity','--artifact-root',$ArtifactRoot,
    '--create-protection-lease',$leaseId,'--lease-owner',$Owner,
    '--lease-ttl-seconds',([string]$LeaseTtlSeconds),'--committed-new-bytes',([string]$CommittedNewBytes))
  foreach($path in $paths){$arguments+=@('--protect-path',$path)}
  foreach($key in $ProtectedCacheKeys){$arguments+=@('--protect-cache-key',$key)}
  try{
    $leaseOutput=@(Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
      & $Python @arguments;if($LASTEXITCODE-ne0){throw 'Workflow capacity lease creation failed.'}
    })
    # The active lease is the single reservation source.
    $gateParameters=@{Python=$Python;RepoRoot=$RepoRoot;ArtifactRoot=$ArtifactRoot;
      ProtectedPaths=$paths;ProtectedCacheKeys=$ProtectedCacheKeys;
      CapacityProtectionLeaseId=$leaseId;ExecutionMode='startup'}
    $gate=Invoke-ArtifactCapacityGate @gateParameters
    return [pscustomobject]@{schema_version=1;role='artifact_workflow_capacity_session';
      status='active';artifact_root=[IO.Path]::GetFullPath($ArtifactRoot);lease_id=$leaseId;
      owner=$Owner;lease_ttl_seconds=$LeaseTtlSeconds;committed_new_bytes=$CommittedNewBytes;
      protected_paths=@($paths);protected_cache_keys=@($ProtectedCacheKeys|Select-Object -Unique);
      lease=((@($leaseOutput)-join"`n")|ConvertFrom-Json);startup_gate=$gate}
  }catch{
    try{
      Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
        & $Python -m common.contracts.reconcile_artifact_capacity --artifact-root $ArtifactRoot `
          --delete-protection-lease $leaseId|Out-Null
      }
    }catch{
      Write-Warning "CAPACITY_WORKFLOW_LEASE_CLEANUP_FAILED lease_id=$leaseId error=$($_.Exception.Message)"
    }
    throw
  }
}

function Update-ArtifactWorkflowCapacitySession {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][pscustomobject]$Session,[string[]]$ProtectedPaths=@(),
    [string[]]$ProtectedCacheKeys=@(),[Nullable[long]]$RemainingCommittedNewBytes=$null
  )
  if([string]$Session.status-ne'active'){throw 'Workflow capacity session is not active.'}
  if($null-ne$RemainingCommittedNewBytes-and$RemainingCommittedNewBytes-lt0){throw 'Remaining committed bytes must be nonnegative.'}
  [int64]$priorCommitment=$Session.committed_new_bytes
  $arguments=@('-m','common.contracts.reconcile_artifact_capacity','--artifact-root',[string]$Session.artifact_root,
    '--renew-protection-lease',[string]$Session.lease_id,'--lease-owner',[string]$Session.owner,
    '--lease-ttl-seconds',([string]$Session.lease_ttl_seconds))
  if($null-ne$RemainingCommittedNewBytes){$arguments+=@('--committed-new-bytes',([string]$RemainingCommittedNewBytes))}
  foreach($path in $ProtectedPaths){$arguments+=@('--protect-path',$path)}
  foreach($key in $ProtectedCacheKeys){$arguments+=@('--protect-cache-key',$key)}
  $output=@(Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
    & $Python @arguments;if($LASTEXITCODE-ne0){throw 'Workflow capacity lease renewal failed.'}
  })
  if($null-ne$RemainingCommittedNewBytes){$Session.committed_new_bytes=[int64]$RemainingCommittedNewBytes}
  $Session.protected_paths=@($Session.protected_paths)+@($ProtectedPaths)|Select-Object -Unique
  $Session.protected_cache_keys=@($Session.protected_cache_keys)+@($ProtectedCacheKeys)|Select-Object -Unique
  $gate=$null
  if($null-ne$RemainingCommittedNewBytes-and[int64]$RemainingCommittedNewBytes-gt$priorCommitment){
    # The larger commitment is already durable.  Re-admission may fail, but
    # failure leaves the conservative larger reservation visible to peers.
    $gate=Invoke-ArtifactCapacityGate -Python $Python -RepoRoot $RepoRoot `
      -ArtifactRoot ([string]$Session.artifact_root) `
      -ProtectedPaths @($Session.protected_paths) `
      -ProtectedCacheKeys @($Session.protected_cache_keys) `
      -CapacityProtectionLeaseId ([string]$Session.lease_id) -ExecutionMode startup
  }
  return [pscustomobject]@{session=$Session;renewal=((@($output)-join"`n")|ConvertFrom-Json);admission_gate=$gate}
}

function Exit-ArtifactWorkflowCapacitySession {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][pscustomobject]$Session
  )
  if([string]$Session.status-ne'active'){return [pscustomobject]@{deleted=$false;status=[string]$Session.status}}
  $output=@(Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
    & $Python -m common.contracts.reconcile_artifact_capacity `
      --artifact-root ([string]$Session.artifact_root) `
      --delete-protection-lease ([string]$Session.lease_id)
    if($LASTEXITCODE-ne0){throw 'Workflow capacity lease deletion failed.'}
  })
  $Session.status='released'
  return ((@($output)-join"`n")|ConvertFrom-Json)
}

function Write-RunJson {
  [CmdletBinding()]
  param([Parameter(Mandatory)][object]$Value,[Parameter(Mandatory)][string]$Path,[int]$Depth=8)
  $Value | ConvertTo-Json -Depth $Depth | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Write-RunManifest {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$RunConfig,
    [Parameter(Mandatory)][ValidateSet('success','failed','interrupted','checkpoint','superseded')][string]$Status,
    [string[]]$Software=@(),
    [string]$Manifest='',
    [string[]]$Outputs=@(),
    [switch]$PassThru
  )
  Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
    $arguments=@((Join-Path $RepoRoot 'common\contracts\write_run_manifest.py'),'--run-config',$RunConfig,'--status',$Status)
    if(-not[string]::IsNullOrWhiteSpace($Manifest)){$arguments+=@('--manifest',$Manifest)}
    foreach($item in $Software){$arguments+=@('--software',$item)}
    foreach($item in $Outputs){$arguments+=@('--output',$item)}
    $writerOutput=& $Python @arguments
    if($LASTEXITCODE-ne 0){throw "Run manifest failed for status $Status."}
    if($PassThru){$writerOutput}
  }
}

function Write-VerifiedRunManifest {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$RunConfig,
    [Parameter(Mandatory)][ValidateSet('success','failed','interrupted','checkpoint','superseded')][string]$Status,
    [string[]]$Software=@(),
    [string]$Manifest='',
    [string[]]$Outputs=@()
  )
  if([string]::IsNullOrWhiteSpace($Manifest)){
    $Manifest=Join-Path (Split-Path -Parent $RunConfig) 'run_manifest.json'
  }
  $capacityLifecycle=$null
  $terminalCapacityLifecycle=$Status-in@('success','failed','interrupted')
  if($terminalCapacityLifecycle){
    $runConfiguration=Get-Content -LiteralPath $RunConfig -Raw -Encoding UTF8|ConvertFrom-Json
    if($null-ne$runConfiguration.PSObject.Properties['capacity_ledger_lifecycle']-and
       [bool]$runConfiguration.capacity_ledger_lifecycle.enabled){
      $capacityLifecycle=$runConfiguration.capacity_ledger_lifecycle
      $null=Invoke-RunCapacityLifecycleAdapter -Python $Python -RepoRoot $RepoRoot `
        -Action assert-retention -ArtifactRoot ([string]$capacityLifecycle.artifact_root) `
        -RunConfig $RunConfig
    }
  }
  $manifestDirectory=Split-Path -Parent $Manifest
  $manifestName=[IO.Path]::GetFileNameWithoutExtension($Manifest)
  $manifestExtension=[IO.Path]::GetExtension($Manifest)
  $candidateManifest=Join-Path $manifestDirectory `
    ('.{0}.{1}.candidate{2}'-f$manifestName,[guid]::NewGuid().ToString('N'),$manifestExtension)
  $manifestPublished=$false
  try{
    Write-RunManifest -Python $Python -RepoRoot $RepoRoot -RunConfig $RunConfig `
      -Status $Status -Software $Software -Manifest $candidateManifest -Outputs $Outputs -PassThru
    & $Python (Join-Path $RepoRoot 'common\contracts\verify_run_manifest.py') `
      $candidateManifest --require-status $Status
    if($LASTEXITCODE-ne 0){throw "Could not verify $Status run manifest."}
    Move-Item -LiteralPath $candidateManifest -Destination $Manifest -Force
    $manifestPublished=$true
    if($null-ne$capacityLifecycle){
      $capacityFinal=Invoke-RunCapacityLifecycleAdapter -Python $Python -RepoRoot $RepoRoot `
        -Action finalize-ready -ArtifactRoot ([string]$capacityLifecycle.artifact_root) `
        -RunConfig $RunConfig
      if([bool]$capacityFinal.light_evidence_budget_exceeded){
        $largest=@($capacityFinal.largest_files|ForEach-Object{"$($_.path)=$($_.bytes)B"})-join', '
        Write-Warning ("RUN_LIGHT_EVIDENCE_BUDGET_EXCEEDED RUN={0} BYTES={1} BUDGET={2} LARGEST=[{3}]"-f `
          $capacityFinal.run_directory,$capacityFinal.bytes,$capacityFinal.light_evidence_budget_bytes,$largest) `
          -WarningAction Continue
      }
    }
  }catch{
    if($manifestPublished-and$null-ne$capacityLifecycle){
      throw "Verified $Status run manifest was published, but capacity ledger finalization failed; the run remains writing for recovery: $($_.Exception.Message)"
    }
    throw "Could not publish verified $Status run manifest: $($_.Exception.Message)"
  }finally{
    Remove-Item -LiteralPath $candidateManifest -Force -ErrorAction SilentlyContinue
  }
}

function Write-TerminalRunRecord {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RunDir,
    [Parameter(Mandatory)][ValidateSet('failed','interrupted')][string]$Status,
    [Parameter(Mandatory)][string]$Reason,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$SummaryRole,
    [string[]]$Software=@()
  )
  $config=Join-Path $RunDir 'run_config.json'
  $summary=Join-Path $RunDir 'summary.json'
  Write-RunJson -Path $summary -Depth 4 -Value ([ordered]@{
    schema_version=1;role=$SummaryRole;status=$Status;reason=$Reason
  })
  Write-VerifiedRunManifest -Python $Python -RepoRoot $RepoRoot -RunConfig $config `
    -Manifest (Join-Path $RunDir 'run_manifest.json') -Status $Status `
    -Software $Software -Outputs @($summary)
}

function Initialize-RunRecord {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RunDir,
    [Parameter(Mandatory)][string]$RunId,
    [Parameter(Mandatory)][string]$Project,
    [Parameter(Mandatory)][string]$Mode,
    [Parameter(Mandatory)][string]$ProjectRoot,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$ProvisionalSummaryRole,
    [Parameter(Mandatory)][string]$TerminalSummaryRole,
    [string[]]$Software=@()
  )
  # New governed runs must reserve their complete range before any checkpoint
  # file is written.  This legacy helper remains for non-governed fixtures and
  # historical readers, but cannot create a new run below the artifacts root.
  $runParent=[IO.DirectoryInfo][IO.Path]::GetFullPath($RunDir)
  while($null-ne$runParent){
    if($runParent.Name-eq'artifacts'){
      throw 'Initialize-RunRecord cannot create a run beneath artifacts; use New-RunPackage with retention and capacity-ledger lifecycle.'
    }
    $runParent=$runParent.Parent
  }
  $config=Join-Path $RunDir 'run_config.json'
  $summary=Join-Path $RunDir 'summary.json'
  Write-RunJson -Path $config -Depth 5 -Value ([ordered]@{
    schema_version=1;run_id=$RunId;project=$Project;mode=$Mode
    project_root=$ProjectRoot;formal_gate_passed=$false;inputs=[ordered]@{}
  })
  Write-RunJson -Path $summary -Depth 4 -Value ([ordered]@{
    schema_version=1;role=$ProvisionalSummaryRole;status='checkpoint'
    reason='Run package initialized; task-specific inputs are not frozen yet.'
  })
  # Initialization is an incomplete, resumable checkpoint, not a solver
  # interruption.  Reserve `interrupted` for a run that actually stopped.
  Write-VerifiedRunManifest -Python $Python -RepoRoot $RepoRoot -RunConfig $config `
    -Status checkpoint -Software $Software -Outputs @($summary)
}

function Get-RunPackagePathCapacity {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RunDirectory,
    [string[]]$AdditionalDirectories=@(),
    [string[]]$ExpectedExecutionRelativePaths=@()
  )
  # 259 is the largest path accepted by legacy Win32 callers (MAX_PATH minus
  # the terminating NUL).  This is deliberately a compatibility diagnostic,
  # not a claim about a particular solver's own path limit.
  $legacyWindowsPathLimit=259
  $relativePaths=@(
    'inputs','results','logs','run_config.json','summary.json','run_manifest.json'
  )
  $relativePaths+=$AdditionalDirectories
  $relativePaths+=$ExpectedExecutionRelativePaths
  $entries=foreach($relative in $relativePaths|Sort-Object -Unique){
    if([string]::IsNullOrWhiteSpace($relative)){
      throw 'Execution path capacity entries must not be empty.'
    }
    if([IO.Path]::IsPathRooted($relative)-or
       $relative.Split([IO.Path]::DirectorySeparatorChar,[IO.Path]::AltDirectorySeparatorChar)-contains'..'){
      throw "Execution path capacity entry must be a contained relative path: $relative"
    }
    $path=[IO.Path]::GetFullPath((Join-Path $RunDirectory $relative))
    [pscustomobject]@{
      relative_path=$relative.Replace('\','/');path=$path;length=$path.Length
      legacy_windows_path_limit=$legacyWindowsPathLimit
      remaining_legacy_windows_characters=$legacyWindowsPathLimit-$path.Length
      legacy_windows_compatible=($path.Length-le$legacyWindowsPathLimit)
    }
  }
  $longest=@($entries|Sort-Object length -Descending|Select-Object -First 1)
  return [pscustomobject]@{
    schema_version=1;role='run_package_execution_path_capacity'
    run_directory=[IO.Path]::GetFullPath($RunDirectory)
    legacy_windows_path_limit=$legacyWindowsPathLimit
    entries=@($entries);longest_path=$longest[0]
    legacy_windows_compatible=(@($entries|Where-Object{-not$_.legacy_windows_compatible}).Count-eq 0)
  }
}

function Get-RunPackageCopiedSourcePaths {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string[]]$SourceRelativeDirectories,
    [Parameter(Mandatory)][string[]]$Extensions,
    [string]$DestinationRoot = 'inputs/code'
  )
  $repo = [IO.Path]::GetFullPath($RepoRoot)
  $paths = foreach ($relativeDirectory in $SourceRelativeDirectories) {
    $source = [IO.Path]::GetFullPath((Join-Path $repo $relativeDirectory))
    if (-not $source.StartsWith($repo + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase) -or
        -not (Test-Path -LiteralPath $source -PathType Container)) {
      throw "Copied source directory is not one repository-local directory: $relativeDirectory"
    }
    Get-ChildItem -LiteralPath $source -Recurse -File |
      Where-Object { $_.Extension -in $Extensions } |
      ForEach-Object {
        $nested = $_.FullName.Substring($source.Length).TrimStart([char[]]@(92,47))
        ($DestinationRoot.TrimEnd([char[]]@(92,47)) + '/' +
          $relativeDirectory.Trim([char[]]@(92,47)) + '/' + $nested).Replace([string][char]92,'/')
      }
  }
  return @($paths | Sort-Object -Unique)
}

function Assert-RunPackagePathCapacity {
  [CmdletBinding()]
  param([Parameter(Mandatory)][pscustomobject]$Report)
  if($Report.legacy_windows_compatible){return $Report}
  $overLimit=@($Report.entries|Where-Object{-not$_.legacy_windows_compatible}|Select-Object -First 1)[0]
  throw ('EXECUTION_PATH_CAPACITY=FAIL PATH={0} LENGTH={1} LEGACY_WINDOWS_LIMIT={2} '+
    'REMEDIATION=choose a shorter MASS_SPECTROMETRY_EXECUTION_ROOT or shorten the declared relative path.' -f
    $overLimit.path,$overLimit.length,$overLimit.legacy_windows_path_limit)
}

function New-RunExecutionAlias {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$TargetDirectory,
    [string[]]$AdditionalDirectories=@(),
    [string[]]$ExpectedExecutionRelativePaths=@(),
    [string]$ExecutionRoot=''
  )
  $target=[IO.Path]::GetFullPath($TargetDirectory)
  if(-not(Test-Path -LiteralPath $target -PathType Container)){
    throw "Execution alias target directory is missing: $target"
  }
  if([string]::IsNullOrWhiteSpace($ExecutionRoot)){
    $ExecutionRoot=if($env:MASS_SPECTROMETRY_EXECUTION_ROOT){
      $env:MASS_SPECTROMETRY_EXECUTION_ROOT
    }else{
      # Desktop children can be denied C:\tmp.  The shared artifact root is
      # writable to every project workflow and keeps aliases in one audited
      # disposable location rather than falling back to a long path.
      Join-Path (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))) 'artifacts\common\execution_aliases'
    }
  }
  $executionRootPath=[IO.Path]::GetFullPath($ExecutionRoot)
  $alias=Join-Path $executionRootPath ('run_'+[guid]::NewGuid().ToString('N'))
  $pathCapacity=Get-RunPackagePathCapacity -RunDirectory $alias `
    -AdditionalDirectories $AdditionalDirectories `
    -ExpectedExecutionRelativePaths $ExpectedExecutionRelativePaths
  $null=Assert-RunPackagePathCapacity -Report $pathCapacity
  New-Item -ItemType Directory -Force -Path $executionRootPath|Out-Null
  try{
    New-Item -ItemType Junction -Path $alias -Target $target|Out-Null
  }catch{
    throw "Could not create short execution alias $alias for target ${target}: $($_.Exception.Message)"
  }
  return [pscustomobject]@{
    target_directory=$target;execution_alias=$alias;execution_path_capacity=$pathCapacity
  }
}

function Remove-RunExecutionAlias {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$ExecutionAlias,
    [Parameter(Mandatory)][string]$TargetDirectory
  )
  $alias=[IO.Path]::GetFullPath($ExecutionAlias)
  $targetDirectory=[IO.Path]::GetFullPath($TargetDirectory)
  if(-not(Test-Path -LiteralPath $alias -PathType Container)){return}
  $item=Get-Item -LiteralPath $alias -Force
  if($item.LinkType-ne'Junction'){
    throw "Execution alias is not a junction: $alias"
  }
  $target=[IO.Path]::GetFullPath([string]@($item.Target)[0])
  if(-not $target.Equals($targetDirectory,[StringComparison]::OrdinalIgnoreCase)){
    throw "Execution alias target differs from expected target: $alias"
  }
  [IO.Directory]::Delete($alias)
}

function New-RunPackage {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$ArtifactRoot,
    [Parameter(Mandatory)][string]$RunId,
    [Parameter(Mandatory)][string]$Project,
    [Parameter(Mandatory)][string]$Mode,
    [Parameter(Mandatory)][string[]]$Software,
    [switch]$RetentionContractEnabled,
    [ValidateSet('compact','qualification','solver_review')][string]$RetentionClass='compact',
    [string]$RetentionReason='',
    [string[]]$AdditionalDirectories=@(),
    [switch]$CapacityLedgerLifecycleEnabled,
    [string]$CapacityLedgerArtifactRoot='',
    [switch]$UseShortExecutionPath,
    [string]$ExecutionRoot='',
    [string[]]$ExpectedExecutionRelativePaths=@()
  )
  if($RetentionContractEnabled-and$RetentionClass-ne'compact'-and[string]::IsNullOrWhiteSpace($RetentionReason)){
    throw "RetentionReason is required for artifact retention class $RetentionClass."
  }
  if($RetentionContractEnabled-and$RetentionClass-eq'compact'-and-not[string]::IsNullOrWhiteSpace($RetentionReason)){
    throw 'RetentionReason must be empty for compact artifact retention.'
  }
  if(-not$RetentionContractEnabled-and(
      $RetentionClass-ne'compact'-or-not[string]::IsNullOrWhiteSpace($RetentionReason))){
    throw 'RetentionContractEnabled is required when selecting run artifact retention.'
  }
  if($CapacityLedgerLifecycleEnabled-and-not$RetentionContractEnabled){
    throw 'CapacityLedgerLifecycleEnabled requires RetentionContractEnabled.'
  }
  if(-not$CapacityLedgerLifecycleEnabled-and-not[string]::IsNullOrWhiteSpace($CapacityLedgerArtifactRoot)){
    throw 'CapacityLedgerArtifactRoot requires CapacityLedgerLifecycleEnabled.'
  }
  # Shared artifacts are governed ranges.  Reject an incomplete lifecycle
  # declaration before this helper creates the run directory or checkpoint.
  $artifactParent=[IO.DirectoryInfo][IO.Path]::GetFullPath($ArtifactRoot)
  $governedArtifactsRoot=$null
  while($null-ne$artifactParent){
    if($artifactParent.Name-eq'artifacts'){$governedArtifactsRoot=$artifactParent;break}
    $artifactParent=$artifactParent.Parent
  }
  if($null-ne$governedArtifactsRoot-and(-not$RetentionContractEnabled-or-not$CapacityLedgerLifecycleEnabled)){
    throw 'Runs beneath artifacts require retention and capacity-ledger lifecycle before package creation.'
  }
  if($CapacityLedgerLifecycleEnabled){
    if([string]::IsNullOrWhiteSpace($CapacityLedgerArtifactRoot)){
      if($null-eq$governedArtifactsRoot){
        throw 'Could not derive the workspace artifacts root for capacity-ledger lifecycle.'
      }
      $CapacityLedgerArtifactRoot=$governedArtifactsRoot.FullName
    }
    $CapacityLedgerArtifactRoot=[IO.Path]::GetFullPath($CapacityLedgerArtifactRoot)
  }
  $python=[IO.Path]::GetFullPath($Python)
  if(-not(Test-Path -LiteralPath $python -PathType Leaf)){throw "Run Python environment is missing: $python"}
  $pythonVersion=(& $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
  if($LASTEXITCODE-ne 0 -or $pythonVersion-ne '3.11'){
    throw "Run package requires Python 3.11, found $pythonVersion at $python"
  }
  $validation=& $python (Join-Path $RepoRoot 'common\contracts\artifact_naming.py') run $RunId
  if($LASTEXITCODE-ne 0 -or -not($validation-match '^ARTIFACT_ID=PASS ')){throw "Invalid run_id: $RunId"}
  $artifactRunDir=Join-Path $ArtifactRoot "runs\$RunId"
  if(Test-Path -LiteralPath $artifactRunDir){throw "Run already exists: $artifactRunDir"}
  if($CapacityLedgerLifecycleEnabled){
    New-Item -ItemType Directory -Path $artifactRunDir -ErrorAction Stop|Out-Null
    try{
      $null=Invoke-RunCapacityLifecycleAdapter -Python $python -RepoRoot $RepoRoot `
        -Action register-writing-range -ArtifactRoot $CapacityLedgerArtifactRoot -RunDirectory $artifactRunDir
    }catch{
      [IO.Directory]::Delete($artifactRunDir,$false)
      throw
    }
  }
  $runDir=$artifactRunDir
  $executionAlias=$null
  if($UseShortExecutionPath){
    if(-not$CapacityLedgerLifecycleEnabled){New-Item -ItemType Directory -Force -Path $artifactRunDir|Out-Null}
    try{
      $aliasRecord=New-RunExecutionAlias -TargetDirectory $artifactRunDir `
        -AdditionalDirectories $AdditionalDirectories -ExecutionRoot $ExecutionRoot `
        -ExpectedExecutionRelativePaths $ExpectedExecutionRelativePaths
    }catch{
      if(-not$CapacityLedgerLifecycleEnabled){[IO.Directory]::Delete($artifactRunDir,$true)}
      throw
    }
    $executionAlias=$aliasRecord.execution_alias
    $pathCapacity=$aliasRecord.execution_path_capacity
    $runDir=$executionAlias
  }else{
    $pathCapacity=Get-RunPackagePathCapacity -RunDirectory $runDir `
      -AdditionalDirectories $AdditionalDirectories `
      -ExpectedExecutionRelativePaths $ExpectedExecutionRelativePaths
  }
  $package=[ordered]@{
    python=$python;run_dir=$runDir;input_dir=(Join-Path $runDir 'inputs');result_dir=(Join-Path $runDir 'results');
    log_dir=(Join-Path $runDir 'logs');run_config=(Join-Path $runDir 'run_config.json');summary=(Join-Path $runDir 'summary.json');
    artifact_run_dir=$artifactRunDir;execution_alias=$executionAlias;execution_path_capacity=$pathCapacity
  }
  $directories=@($package.input_dir,$package.result_dir,$package.log_dir)
  foreach($relative in $AdditionalDirectories){$directories+=Join-Path $runDir $relative}
  New-Item -ItemType Directory -Force -Path $directories|Out-Null
  $initialConfig=[ordered]@{
    schema_version=$(if($RetentionContractEnabled){2}else{1});
    run_id=$RunId;project=$Project;mode=$Mode;project_root=$RepoRoot;inputs=[ordered]@{};
    parameters=[ordered]@{lifecycle_stage='run_package_initialized'};formal_gate_passed=$false
  }
  if($RetentionContractEnabled){
    $initialConfig.artifact_retention=[ordered]@{policy_version=1;class=$RetentionClass;
      reason=$(if($RetentionClass-eq'compact'){$null}else{$RetentionReason})}
  }
  if($CapacityLedgerLifecycleEnabled){
    $capacityPolicy=Get-Content -LiteralPath (Join-Path $RepoRoot 'common\contracts\artifact_capacity_policy.json') `
      -Raw -Encoding UTF8|ConvertFrom-Json
    [int64]$lightBudget=$capacityPolicy.light_evidence_budget_bytes
    if($lightBudget-le0){throw 'Artifact capacity policy light-evidence budget must be positive.'}
    $initialConfig.capacity_ledger_lifecycle=[ordered]@{
      schema_version=1;enabled=$true;artifact_root=$CapacityLedgerArtifactRoot
      light_evidence_budget_bytes=$lightBudget
    }
  }
  Write-RunJson -Path $package.run_config -Value $initialConfig
  Write-RunJson -Path $package.summary -Value ([ordered]@{
    schema_version=1;role='run_package_initialization_summary';status='checkpoint';
    reason='Run package initialized; task-specific inputs are not frozen yet.'
  })
  $null=Write-VerifiedRunManifest -Python $python -RepoRoot $RepoRoot -RunConfig $package.run_config `
    -Status checkpoint -Software $Software -Outputs @($package.summary)
  if($CapacityLedgerLifecycleEnabled){
    $null=Invoke-RunCapacityLifecycleAdapter -Python $python -RepoRoot $RepoRoot `
      -Action register-writing -ArtifactRoot $CapacityLedgerArtifactRoot -RunConfig $package.run_config
  }
  return [pscustomobject]$package
}

function Remove-RunPackageExecutionAlias {
  [CmdletBinding()]
  param([Parameter(Mandatory)][pscustomobject]$Package)
  if($null-eq$Package.execution_alias){return}
  Remove-RunExecutionAlias -ExecutionAlias ([string]$Package.execution_alias) `
    -TargetDirectory ([string]$Package.artifact_run_dir)
}

function Apply-RunArtifactRetention {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$RunConfig,
    [string[]]$PreservePaths=@(),
    [string[]]$RemovePaths=@()
  )
  $arguments=@('apply','--run-config',$RunConfig)
  foreach($path in $PreservePaths){
    if(-not[string]::IsNullOrWhiteSpace($path)){
      $arguments+=@('--preserve-path',$path)
    }
  }
  foreach($path in $RemovePaths){
    if(-not[string]::IsNullOrWhiteSpace($path)){
      $arguments+=@('--remove-path',$path)
    }
  }
  $output=& $Python (Join-Path $RepoRoot 'common\contracts\artifact_retention.py') @arguments
  if($LASTEXITCODE-ne 0){throw 'Run artifact retention failed.'}
  Write-Verbose ($output -join [Environment]::NewLine)
  return Join-Path (Split-Path -Parent $RunConfig) 'retention_actions.json'
}

function Save-RunEnvironment {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string[]]$Names)
  $snapshot=@{};foreach($name in $Names){$snapshot[$name]=[Environment]::GetEnvironmentVariable($name)};return $snapshot
}

function Restore-RunEnvironment {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string[]]$Names,[Parameter(Mandatory)][hashtable]$Snapshot)
  foreach($name in $Names){[Environment]::SetEnvironmentVariable($name,$Snapshot[$name])}
}

function Copy-FrozenDependency {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RepoRoot,[Parameter(Mandatory)][string]$InputDir,
    [Parameter(Mandatory)][pscustomobject]$Dependency
  )
  $providerRoot=[IO.Path]::GetFullPath((Join-Path $RepoRoot (Join-Path 'projects' ([string]$Dependency.provider_project))))
  $source=[IO.Path]::GetFullPath((Join-Path $RepoRoot ([string]$Dependency.source_repo_path)))
  if(-not $source.StartsWith($providerRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){
    throw "Dependency $($Dependency.id) escapes provider project $($Dependency.provider_project)."
  }
  if(-not(Test-Path -LiteralPath $source -PathType Leaf)){throw "Dependency $($Dependency.id) is missing: $source"}
  $destination=Join-Path $InputDir ([string]$Dependency.frozen_filename);Copy-Item -LiteralPath $source -Destination $destination
  $hash=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
  if($hash-ne(Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash){throw "Dependency changed while frozen: $source"}
  return [pscustomobject]@{id=[string]$Dependency.id;provider_project=[string]$Dependency.provider_project;
    source_repo_path=[string]$Dependency.source_repo_path;frozen_input_name=[string]$Dependency.run_input_name;
    frozen_path=$destination;sha256=$hash}
}

function Copy-VerifiedRunInput {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Source,
    [Parameter(Mandatory)][string]$Destination,
    [ValidateRange(1,5)][int]$VerificationAttempts=1
  )
  $sourcePath=[IO.Path]::GetFullPath($Source);$destinationPath=[IO.Path]::GetFullPath($Destination)
  if(-not(Test-Path -LiteralPath $sourcePath -PathType Leaf)){throw "Run input is missing: $sourcePath"}
  $parent=Split-Path -Parent $destinationPath
  if(-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Path $parent -Force|Out-Null}
  foreach($attempt in 1..$VerificationAttempts){
    $sourceHashBefore=(Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash
    if(Test-Path -LiteralPath $destinationPath -PathType Leaf){(Get-Item -LiteralPath $destinationPath).IsReadOnly=$false}
    if($attempt-eq1){
      Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Force
    }else{
      $readStream=$null;$writeStream=$null
      try{
        $readStream=[IO.File]::Open($sourcePath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
        $writeStream=[IO.FileStream]::new($destinationPath,[IO.FileMode]::Create,[IO.FileAccess]::Write,[IO.FileShare]::None,8MB,[IO.FileOptions]::WriteThrough)
        $readStream.CopyTo($writeStream,8MB)
        $writeStream.Flush($true)
      }finally{
        if($null-ne$writeStream){$writeStream.Dispose()}
        if($null-ne$readStream){$readStream.Dispose()}
      }
      [IO.File]::SetLastWriteTimeUtc($destinationPath,[IO.File]::GetLastWriteTimeUtc($sourcePath))
    }
    $sourceHashAfter=(Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash
    $destinationHash=(Get-FileHash -LiteralPath $destinationPath -Algorithm SHA256).Hash
    if($sourceHashBefore-ceq$sourceHashAfter -and $sourceHashAfter-ceq$destinationHash){return $destinationPath}
  }
  throw "Run input changed or copied inconsistently while frozen after $VerificationAttempts attempt(s): $sourcePath"
}

function Write-RunDirectoryChecksumInventory {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Directory,
    [Parameter(Mandatory)][string]$OutputPath,
    [string[]]$ExcludedPatterns=@()
  )
  $outputName=[IO.Path]::GetFileName($OutputPath)
  $records=Get-ChildItem -LiteralPath $Directory -File|Where-Object{
    $name=$_.Name
    if($name-eq$outputName){return $false}
    foreach($pattern in $ExcludedPatterns){if($name-like$pattern){return $false}}
    return $true
  }|Sort-Object Name|ForEach-Object{
    [pscustomobject]@{file=$_.Name;bytes=$_.Length;sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}
  }
  $records|Export-Csv -LiteralPath $OutputPath -NoTypeInformation -Encoding UTF8
}

function Get-RunFileSha256 {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$Path)
  $fullPath=[IO.Path]::GetFullPath($Path)
  if(-not(Test-Path -LiteralPath $fullPath -PathType Leaf)){throw "Run file is missing: $fullPath"}
  return (Get-FileHash -LiteralPath $fullPath -Algorithm SHA256).Hash
}

function Test-RunFilesIdentical {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Left,
    [Parameter(Mandatory)][string]$Right
  )
  $leftPath=[IO.Path]::GetFullPath($Left);$rightPath=[IO.Path]::GetFullPath($Right)
  if(-not(Test-Path -LiteralPath $leftPath -PathType Leaf) -or
     -not(Test-Path -LiteralPath $rightPath -PathType Leaf)){return $false}
  return (Get-Item -LiteralPath $leftPath).Length -eq (Get-Item -LiteralPath $rightPath).Length -and
    (Get-RunFileSha256 -Path $leftPath) -ceq (Get-RunFileSha256 -Path $rightPath)
}

function Complete-FailedRun {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$RunConfig,[Parameter(Mandatory)][string]$Summary,
    [Parameter(Mandatory)][string]$SummaryRole,[Parameter(Mandatory)][string]$Reason,
    [Parameter(Mandatory)][string[]]$Software,
    [ValidateSet('failed','interrupted')][string]$Status='failed',
    [string]$FailureClass='',
    [int]$SummarySchemaVersion=1,
    [string]$FailureStage='',
    [Nullable[bool]]$ThresholdResultEligible=$null,
    [hashtable]$AdditionalSummaryProperties=@{},
    [string[]]$AdditionalOutputs=@(),
    [string]$ResourceUsagePath='',
    [switch]$PreserveRawOutputs,
    [string[]]$PreserveRawOutputPaths=@()
  )
  Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
  $document=Get-Content -LiteralPath $RunConfig -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if(-not $document.Contains('inputs')){$document.inputs=[ordered]@{}}
  $known=@($document.inputs.Values|ForEach-Object{if($_ -is [string]){[IO.Path]::GetFullPath($_)}})
  $runDir=Split-Path -Parent $RunConfig
  $inputDir=Join-Path $runDir 'inputs';$index=0
  if(Test-Path -LiteralPath $inputDir -PathType Container){foreach($file in Get-ChildItem -LiteralPath $inputDir -Recurse -File|Sort-Object FullName){
    if($known-notcontains$file.FullName){$index+=1;$document.inputs[("recovered_input_{0:D3}"-f$index)]=$file.FullName}
  }}
  Write-RunJson -Path $RunConfig -Value $document
  $summaryDocument=[ordered]@{
    schema_version=$SummarySchemaVersion;role=$SummaryRole;status=$Status;reason=$Reason
  }
  if(-not[string]::IsNullOrWhiteSpace($FailureClass)){
    $summaryDocument.failure_class=$FailureClass
  }
  if(-not[string]::IsNullOrWhiteSpace($FailureStage)){
    $summaryDocument.failure_stage=$FailureStage
  }
  if($null-ne$ThresholdResultEligible){
    $summaryDocument.threshold_result_eligible=[bool]$ThresholdResultEligible
  }
  foreach($key in $AdditionalSummaryProperties.Keys){
    if($key-in@('schema_version','role','status','reason','failure_class','failure_stage','threshold_result_eligible')){
      throw "Additional failed-run summary property is reserved: $key"
    }
    $summaryDocument[$key]=$AdditionalSummaryProperties[$key]
  }
  Write-RunJson -Path $Summary -Value $summaryDocument
  $retentionActions=$null
  if(-not $PreserveRawOutputs -and $PreserveRawOutputPaths.Count-ne 0){
    throw 'Recoverable raw output paths require PreserveRawOutputs.'
  }
  $preservedRawTracePaths=@()
  if($PreserveRawOutputs){
    if($PreserveRawOutputPaths.Count-eq 0){
      throw 'PreserveRawOutputs requires at least one completed SIMION batch log.'
    }
    foreach($trace in $PreserveRawOutputPaths){
      $tracePath=[IO.Path]::GetFullPath($trace)
      $traceName=[IO.Path]::GetFileName($tracePath)
      $isPrePulseTrace=$traceName-like'simion__batch*.trace.log'
      $isFullFlightStdout=$traceName-like'simion__batch*.stdout.log'
      $completionLine=if(Test-Path -LiteralPath $tracePath -PathType Leaf){
        Get-Content -LiteralPath $tracePath -Tail 1 -Encoding UTF8
      }else{''}
      if(-not $tracePath.StartsWith(([IO.Path]::GetFullPath($runDir)+[IO.Path]::DirectorySeparatorChar),[StringComparison]::OrdinalIgnoreCase) -or
         -not(Test-Path -LiteralPath $tracePath -PathType Leaf) -or
         (-not$isPrePulseTrace-and-not$isFullFlightStdout) -or
         ($isPrePulseTrace-and$completionLine-ne'status,Fly completed.') -or
         ($isFullFlightStdout-and$completionLine-notlike'status,Fly completed.*')){
        throw 'Recoverable raw output must be a completed run-local SIMION batch TRACE/stdout.'
      }
      $preservedRawTracePaths+=$tracePath
    }
  }
  $recoverableTraceDirectory=Join-Path $runDir 'logs'
  $discardedRawTracePaths=if(Test-Path -LiteralPath $recoverableTraceDirectory -PathType Container){
    @(
      Get-ChildItem -LiteralPath $recoverableTraceDirectory -File | Where-Object {
        ($_.Name -like 'simion__batch*.trace.log' -or
          $_.Name -like 'simion__batch*.stdout.log') -and
        $preservedRawTracePaths -notcontains $_.FullName
      } | Select-Object -ExpandProperty FullName
    )
  }else{@()}
  # Completed raw TRACE is an explicit, auditable recovery exception.  All
  # other compact-forbidden payload, including solver-native PA/IOB/Fly files,
  # is still removed before the terminal manifest is published.
  if([int]$document.schema_version-eq 2){
    $existingRetentionActions=Join-Path $runDir 'retention_actions.json'
    if(Test-Path -LiteralPath $existingRetentionActions -PathType Leaf){
      # A success-path publication may already have reconciled retention before
      # a later manifest verification error.  Reuse that immutable receipt when
      # terminalizing the failure; applying retention twice is both unnecessary
      # and rejected by the retention contract.
      $retentionActions=$existingRetentionActions
    }else{
      $retentionActions=Apply-RunArtifactRetention -Python $Python -RepoRoot $RepoRoot `
        -RunConfig $RunConfig -PreservePaths $preservedRawTracePaths `
        -RemovePaths $discardedRawTracePaths
    }
  }
  if(-not[string]::IsNullOrWhiteSpace($ResourceUsagePath)-and
    (Test-Path -LiteralPath $ResourceUsagePath -PathType Leaf)){
    $usage=Get-Content -LiteralPath $ResourceUsagePath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    if([string]$usage.status-eq'running'){
      $usage.status=$Status
    }
    if(-not[string]::IsNullOrWhiteSpace($FailureClass)){
      $usage.failure_class=$FailureClass
    }
    $finalBytes=[int64](Get-ChildItem -LiteralPath $runDir -Recurse -File|
      Measure-Object -Property Length -Sum).Sum
    $usage.final_retained_bytes=$finalBytes
    if([int64]$usage.peak_run_directory_bytes-lt$finalBytes){
      $usage.peak_run_directory_bytes=$finalBytes
    }
    # Scheduler-only usage receipts govern CPU/memory admission and do not
    # necessarily carry the campaign retention-byte limit.  Failed-run
    # publication must still finalize such a receipt instead of treating an
    # intentionally absent optional limit as a malformed object.
    $hasCompactFinalLimit = $usage.Contains('limits') -and
      $usage.limits -is [System.Collections.IDictionary] -and
      $usage.limits.Contains('compact_final_retained_bytes')
    if($hasCompactFinalLimit -and
        $finalBytes-gt[int64]$usage.limits.compact_final_retained_bytes){
      $usage.status='resource_budget_exceeded'
      $usage.failure_class='resource_budget_exceeded'
      $usage.limit_name='compact_final_retained_bytes'
      $Status='interrupted'
      Write-RunJson -Path $Summary -Value ([ordered]@{
        schema_version=1;role=$SummaryRole;status='interrupted';reason='Compact final retained-byte budget exceeded.'
        failure_class='resource_budget_exceeded'
      })
    }
    Write-RunJson -Path $ResourceUsagePath -Value $usage
    $AdditionalOutputs+=@($ResourceUsagePath)
  }
  $outputs=@($Summary)+@($AdditionalOutputs|Where-Object{
    -not[string]::IsNullOrWhiteSpace($_)-and(Test-Path -LiteralPath $_ -PathType Leaf)
  })
  if($retentionActions){$outputs+=$retentionActions}
  foreach($relative in @('results','logs','simion')){
    $directory=Join-Path $runDir $relative
    if(Test-Path -LiteralPath $directory -PathType Container){
      $outputs+=@(Get-ChildItem -LiteralPath $directory -Recurse -File|Sort-Object FullName|Select-Object -ExpandProperty FullName)
    }
  }
  Write-VerifiedRunManifest -Python $Python -RepoRoot $RepoRoot -RunConfig $RunConfig `
    -Status $Status -Software $Software -Outputs @($outputs|Select-Object -Unique)
  }
}
