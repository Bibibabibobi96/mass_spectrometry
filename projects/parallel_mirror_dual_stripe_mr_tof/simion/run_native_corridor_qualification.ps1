[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$FrozenInputDirectory,
  [string]$ContractPath='',
  [string]$RunId='',
  [string]$SimionExe='',
  [string]$PythonExe='',
  [ValidateRange(0,8)][int]$InternalResponseId=0,
  [string]$InternalBuildDirectory='',
  [string]$InternalScratchDirectory='',
  [string]$InternalCoarseRawGeometryPath='',
  [string]$InternalCoarseOrigin=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$projectRoot=Join-Path $repoRoot "projects\$projectId"
$artifactRoot=Join-Path $workspaceRoot 'artifacts'
$projectArtifactRoot=Join-Path $artifactRoot "projects\$projectId"
$cacheRoot=Join-Path $artifactRoot 'common\simion\pa_family_cache'
$publishedPinReason='MR-TOF native adjustable analyzer PA family; rebuild only on frozen geometry identity change'
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$simion=if($SimionExe){[IO.Path]::GetFullPath($SimionExe)}else{Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'}
$contract=if($ContractPath){[IO.Path]::GetFullPath($ContractPath)}else{Join-Path $projectRoot 'config\simion_candidate_two_zone.json'}
$frozenDirectory=(Resolve-Path -LiteralPath $FrozenInputDirectory).Path
$identityPath=Join-Path $frozenDirectory 'native_corridor_identity.json'
$planPath=Join-Path $frozenDirectory 'native_corridor_plan.json'
$recipePath=Join-Path $frozenDirectory 'native_corridor_response_recipe.json'
$freezeManifestPath=Join-Path $frozenDirectory 'native_corridor_freeze_manifest.json'
$familyMembers=@('mrtof_analyzer_corridor.pa#','mrtof_analyzer_corridor.pa0')+@(1..8|ForEach-Object{'mrtof_analyzer_corridor.pa{0}'-f$_})
foreach($path in @($python,$identityPath,$planPath,$recipePath,$freezeManifestPath)){
  if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Required native-corridor input is missing: $path"}
}
if(-not$RunId){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__build__simion__mrtof-native-corridor-qualification'}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\parallel_gate_support.ps1')

function Invoke-ProjectPython {
  param([Parameter(Mandatory)][string[]]$Arguments)
  $lines=@(Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
    & $python @Arguments
    if($LASTEXITCODE-ne0){throw "Python stage failed: $($Arguments -join ' ')"}
  })
  return $lines
}

function Get-NativeCorridorTransactionArguments {
  param([string]$VerificationEvidence='')
  $arguments=@('-m','common.simion.pa_family_cache','--action','advance-transaction','--cache-root',$cacheRoot,
    '--identity',$identityPath,'--filenames',($familyMembers-join','),'--recovery-policy','none',
    '--published-pin-reason',$publishedPinReason)
  if($VerificationEvidence){$arguments+=@('--verification-evidence',$VerificationEvidence)}
  return @($arguments)
}

function Get-NativeCorridorRemainingPeakBytes {
  param(
    [Parameter(Mandatory)][pscustomobject]$Plan,
    [Parameter(Mandatory)][string]$CacheKey
  )
  [int64]$memberEstimate=[int64]([double]$Plan.family_bytes/[int]$Plan.native_family_members)
  $transactionDirectory=Join-Path $cacheRoot ".transactions\$($CacheKey.ToUpperInvariant())"
  $transactionPath=Join-Path $transactionDirectory 'transaction.json'
  $payload=Join-Path $transactionDirectory 'payload'
  [int64]$landedPayloadBytes=0
  $landedNames=@()
  if(Test-Path -LiteralPath $transactionPath -PathType Leaf){
    $transaction=Get-Content -LiteralPath $transactionPath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 40
    if([string]$transaction.role-ne'simion_pa_family_cache_transaction'-or
       [string]$transaction.cache_key-ne$CacheKey.ToUpperInvariant()-or
       [string]$transaction.status-notin@('building','prepared')){
      throw 'Existing native-corridor transaction cannot supply a remaining-space commitment.'
    }
    $declared=@($transaction.filenames|ForEach-Object{[string]$_}|Sort-Object)
    if(Compare-Object $declared @($familyMembers|Sort-Object)){
      throw 'Existing native-corridor transaction member namespace differs.'
    }
    if(Test-Path -LiteralPath $payload -PathType Container){
      $payloadChildren=@(Get-ChildItem -LiteralPath $payload -Force)
      foreach($child in $payloadChildren){
        if($child.PSIsContainer-or$child.LinkType-or$child.Name-notin$familyMembers){
          throw 'Existing native-corridor transaction payload contains an unexpected entry.'
        }
        $landedNames+=@($child.Name)
        $landedPayloadBytes+=[int64]$child.Length
      }
    }
  }
  [int64]$remaining=[Math]::Max([int64]0,([int64]$Plan.peak_additional_bytes-$landedPayloadBytes))
  if('mrtof_analyzer_corridor.pa#'-notin$landedNames){$remaining+=$memberEstimate}
  return $remaining
}

function Enter-NativeCorridorWriterLock {
  param(
    [Parameter(Mandatory)][string]$Root,
    [Parameter(Mandatory)][string]$CacheKey
  )
  if($CacheKey-notmatch'^[0-9A-Fa-f]{64}$'){throw 'Native-corridor writer lock requires one SHA-256 cache key.'}
  $directory=Join-Path ([IO.Path]::GetFullPath($Root)) '.build-locks'
  [IO.Directory]::CreateDirectory($directory)|Out-Null
  $path=Join-Path $directory ($CacheKey.ToUpperInvariant()+'.lock')
  try{
    return [IO.FileStream]::new($path,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
  }catch [IO.IOException] {
    throw "Native-corridor cache key already has an active builder: $($CacheKey.ToUpperInvariant())"
  }
}

function Exit-NativeCorridorWriterLock {
  param([IO.FileStream]$Lock)
  if($null-ne$Lock){$Lock.Dispose()}
}

function Invoke-NativeCorridorTransactionLoop {
  param(
    [Parameter(Mandatory)][scriptblock]$Advance,
    [Parameter(Mandatory)][scriptblock]$Build,
    [Parameter(Mandatory)][scriptblock]$Preverify,
    [Parameter(Mandatory)][scriptblock]$BindEvidence,
    [int]$MaximumTransitions=8
  )
  $transactionVerificationEvidence=''
  $preverificationOutput=''
  for($transition=0;$transition-lt$MaximumTransitions;$transition++){
    $state=&$Advance $transactionVerificationEvidence
    if($null-eq$state){throw 'Native-corridor transaction returned no state.'}
    switch([string]$state.action_required){
      'build' {
        &$Build $state
        $preverificationOutput=[string](&$Preverify $state)
        if([string]::IsNullOrWhiteSpace($preverificationOutput)){
          throw 'Native-corridor preverification returned no output path.'
        }
        $transactionVerificationEvidence=''
      }
      'verify' {
        if([string]::IsNullOrWhiteSpace($preverificationOutput)){
          throw 'Native-corridor payload reached sealed verification without pre-inventory Fast Adjust evidence.'
        }
        $transactionVerificationEvidence=[string](&$BindEvidence $state $preverificationOutput)
        if([string]::IsNullOrWhiteSpace($transactionVerificationEvidence)){
          throw 'Native-corridor verifier returned no evidence path.'
        }
      }
      'complete' {return $state}
      default {throw "Unsupported native-corridor transaction action: $($state.action_required)"}
    }
  }
  throw "Native-corridor transaction did not complete within $MaximumTransitions transitions."
}

function Publish-NativeCorridorBuiltMember {
  param(
    [Parameter(Mandatory)][string]$ScratchPath,
    [Parameter(Mandatory)][string]$DestinationPath
  )
  if(-not(Test-Path -LiteralPath $ScratchPath -PathType Leaf)){throw "Built scratch member is missing: $ScratchPath"}
  if(Test-Path -LiteralPath $DestinationPath){throw "Transaction member already exists and will not be overwritten: $DestinationPath"}
  Move-Item -LiteralPath $ScratchPath -Destination $DestinationPath
}

function Invoke-NativeCorridorResponseMemberBuild {
  param(
    [Parameter(Mandatory)][ValidateRange(1,8)][int]$ResponseId,
    [Parameter(Mandatory)][string]$BuildDirectory,
    [Parameter(Mandatory)][string]$ScratchDirectory,
    [Parameter(Mandatory)][string]$CoarseRawGeometryPath,
    [Parameter(Mandatory)][string]$CoarseOrigin
  )
  $name='mrtof_analyzer_corridor.pa{0}'-f$ResponseId
  $destination=Join-Path ([IO.Path]::GetFullPath($BuildDirectory)) $name
  if(Test-Path -LiteralPath $destination -PathType Leaf){
    Write-Host "MRTOF_NATIVE_CORRIDOR_MEMBER=REUSED ID=$ResponseId PATH=$destination"
    return
  }
  $memberScratch=Join-Path ([IO.Path]::GetFullPath($ScratchDirectory)) ('response-{0:D2}'-f$ResponseId)
  New-Item -ItemType Directory -Force -Path $memberScratch|Out-Null
  $plan=Get-Content -LiteralPath $planPath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 30
  $recipe=Get-Content -LiteralPath $recipePath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 30
  $record=@($recipe.response_recipes|Where-Object{[int]$_.local_id-eq$ResponseId})
  if($record.Count-ne1){throw "Frozen native-corridor recipe lacks exactly one response ID $ResponseId."}
  $coarseOriginValues=@($CoarseOrigin-split','|ForEach-Object{[double]$_.Trim()})
  $corridorOriginValues=@($plan.box_project_mm[0..2]|ForEach-Object{[double]$_})
  if($coarseOriginValues.Count-ne3-or$corridorOriginValues.Count-ne3){throw 'Native-corridor origins must have three axes.'}
  $aliases=@();$lease=$null
  try{
    $buildAlias=New-RunExecutionAlias -TargetDirectory ([IO.Path]::GetFullPath($BuildDirectory));$aliases+=@($buildAlias)
    $scratchAlias=New-RunExecutionAlias -TargetDirectory $memberScratch;$aliases+=@($scratchAlias)
    $sourceAliases=@{}
    $sourcePaths=@($record[0].source_basis_paths|ForEach-Object{(Resolve-Path -LiteralPath $_).Path})
    foreach($directory in @((Split-Path -Parent ([IO.Path]::GetFullPath($CoarseRawGeometryPath))))+@($sourcePaths|ForEach-Object{Split-Path -Parent $_})|Sort-Object -Unique){
      $alias=New-RunExecutionAlias -TargetDirectory $directory;$aliases+=@($alias)
      $sourceAliases[[IO.Path]::GetFullPath($directory)]=[string]$alias.execution_alias
    }
    $rawFinal=Join-Path ([string]$buildAlias.execution_alias) 'mrtof_analyzer_corridor.pa#'
    if(-not(Test-Path -LiteralPath (Join-Path ([IO.Path]::GetFullPath($BuildDirectory)) 'mrtof_analyzer_corridor.pa#') -PathType Leaf)){
      throw 'Native-corridor raw geometry must be complete before response dispatch.'
    }
    $coarseRawExecution=Join-Path $sourceAliases[[IO.Path]::GetFullPath((Split-Path -Parent $CoarseRawGeometryPath))] (Split-Path -Leaf $CoarseRawGeometryPath)
    $sourceExecution=@($sourcePaths|ForEach-Object{
      Join-Path $sourceAliases[[IO.Path]::GetFullPath((Split-Path -Parent $_))] (Split-Path -Leaf $_)
    })
    $scratchMember=Join-Path ([string]$scratchAlias.execution_alias) $name
    $basis=$sourceExecution-join'|'
    $sourceActive=@($record[0].physical_ids|ForEach-Object{[int]$_})-join','
    $lease=Enter-HostExecutionLease -Role SIMION -Stage dirichlet_response_refine -RunId $RunId
    & $simion --nogui --noprompt lua (Join-Path $repoRoot 'common\simion\build_dirichlet_patch_basis.lua') `
      $rawFinal $scratchMember $basis ([string]$ResponseId) ($coarseOriginValues-join',') ($corridorOriginValues-join',') '-' $coarseRawExecution $sourceActive '10000'
    if($LASTEXITCODE-ne0){throw "Native-corridor response build failed for ID $ResponseId"}
    Publish-NativeCorridorBuiltMember -ScratchPath (Join-Path $memberScratch $name) -DestinationPath $destination
    Exit-HostExecutionLease -Lease $lease -Outcome success -RunId $RunId;$lease=$null
    Write-Host "MRTOF_NATIVE_CORRIDOR_MEMBER=BUILT ID=$ResponseId PATH=$destination"
  }finally{
    if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome failed -RunId $RunId}
    foreach($alias in @($aliases)){Remove-RunExecutionAlias -ExecutionAlias ([string]$alias.execution_alias) -TargetDirectory ([string]$alias.target_directory)}
  }
}

function Invoke-NativeCorridorResponseWave {
  param(
    [Parameter(Mandatory)][int[]]$ResponseIds,
    [Parameter(Mandatory)][string]$BuildDirectory,
    [Parameter(Mandatory)][string]$ScratchDirectory,
    [Parameter(Mandatory)][string]$CoarseRawGeometryPath,
    [Parameter(Mandatory)][string]$CoarseOrigin
  )
  $records=@()
  try{
    foreach($id in $ResponseIds){
      $stdout=Join-Path $resultDir ('native_corridor_response_{0:D2}.stdout.log'-f$id)
      $stderr=Join-Path $resultDir ('native_corridor_response_{0:D2}.stderr.log'-f$id)
      $arguments=@('-NoProfile','-File',$PSCommandPath,'-FrozenInputDirectory',$frozenDirectory,
        '-RunId',$RunId,'-SimionExe',$simion,'-PythonExe',$python,'-InternalResponseId',([string]$id),
        '-InternalBuildDirectory',$BuildDirectory,'-InternalScratchDirectory',$ScratchDirectory,
        '-InternalCoarseRawGeometryPath',$CoarseRawGeometryPath,'-InternalCoarseOrigin',$CoarseOrigin)
      $argumentText=@($arguments|ForEach-Object{ConvertTo-GateProcessArgument ([string]$_)})-join' '
      $process=Start-Process -FilePath (Get-Process -Id $PID).Path -ArgumentList $argumentText `
        -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr -Environment @{
          MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN=''
          MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID=''
          MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE=''
        } -PassThru
      $records+=,[pscustomobject]@{id=$id;process=$process;stdout=$stdout;stderr=$stderr}
    }
    foreach($record in $records){$record.process.WaitForExit()}
    $failed=@($records|Where-Object{[int]$_.process.ExitCode-ne0})
    if($failed.Count-gt0){
      throw ('Native-corridor response workers failed: '+(@($failed|ForEach-Object{"pa$($_.id)=$($_.process.ExitCode)"})-join', '))
    }
  }finally{
    foreach($record in $records){
      if(-not$record.process.HasExited){$record.process.Kill($true);$record.process.WaitForExit()}
      $record.process.Dispose()
      $script:nativeCorridorDispatchArtifacts+=@($record.stdout,$record.stderr)
    }
  }
}

function Invoke-NativeCorridorFamilyBuild {
  param(
    [Parameter(Mandatory)][pscustomobject]$State,
    [Parameter(Mandatory)][pscustomobject]$CapacitySession,
    [Parameter(Mandatory)][string]$CacheKey,
    [Parameter(Mandatory)][string]$CoarseRawGeometryPath,
    [Parameter(Mandatory)][string]$CoarseOrigin
  )
  $buildDirectory=[IO.Path]::GetFullPath([string]$State.build_directory)
  $scratchDirectory=[IO.Path]::GetFullPath([string]$State.scratch_directory)
  $missing=@($State.missing_files|ForEach-Object{[string]$_})
  if($missing.Count-eq0){throw 'Build action did not identify missing family members.'}
  foreach($name in $missing){if($name-notin$familyMembers){throw "Transaction requested an unknown family member: $name"}}
  New-Item -ItemType Directory -Force -Path $buildDirectory,$scratchDirectory|Out-Null
  foreach($name in $familyMembers){
    if($name-notin$missing-and-not(Test-Path -LiteralPath (Join-Path $buildDirectory $name) -PathType Leaf)){
      throw "Transaction inventory omitted a missing family member: $name"
    }
  }
  foreach($path in @($contract,$simion,$CoarseRawGeometryPath,$recipePath,$planPath)){
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Native-corridor build input is missing: $path"}
  }
  $plan=Get-Content -LiteralPath $planPath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 30
  $recipe=Get-Content -LiteralPath $recipePath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 30
  $recipes=@($recipe.response_recipes|Sort-Object {[int]$_.local_id})
  if([string]$plan.role-ne'mrtof_analyzer_full_flight_native_corridor'-or
     @($plan.response_ids).Count-ne8-or$recipes.Count-ne8){
    throw 'Frozen native-corridor plan or response recipe differs.'
  }
  $coarseOriginValues=@($CoarseOrigin-split','|ForEach-Object{[double]$_.Trim()})
  $corridorOriginValues=@($plan.box_project_mm[0..2]|ForEach-Object{[double]$_})
  if($coarseOriginValues.Count-ne3-or$corridorOriginValues.Count-ne3){throw 'Native-corridor origins must have three axes.'}
  $aliases=@();$lease=$null
  try{
    Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $CapacitySession `
      -ProtectedPaths @($buildDirectory,$scratchDirectory) -ProtectedCacheKeys @($CacheKey)|Out-Null
    $buildAlias=New-RunExecutionAlias -TargetDirectory $buildDirectory;$aliases+=@($buildAlias)
    $scratchAlias=New-RunExecutionAlias -TargetDirectory $scratchDirectory;$aliases+=@($scratchAlias)
    $buildExecution=[string]$buildAlias.execution_alias
    $scratchExecution=[string]$scratchAlias.execution_alias
    $lease=Enter-HostExecutionLease -Role SIMION -Stage pa_refine -RunId $RunId
    $buildLog=Join-Path $scratchDirectory 'native_corridor_build.log'
    $rawFinal=Join-Path $buildExecution 'mrtof_analyzer_corridor.pa#'
    if('mrtof_analyzer_corridor.pa#'-in$missing){
      $gem=Join-Path $scratchDirectory 'mrtof_analyzer_corridor.gem'
      $physicalRaw=Join-Path $scratchExecution 'physical_corridor.pa#'
      $rawScratch=Join-Path $scratchExecution 'mrtof_analyzer_corridor.pa#'
      & $python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_corridor_geometry --contract $contract --output $gem
      if($LASTEXITCODE-ne0){throw 'Canonical corridor GEM generation failed.'}
      & $simion --nogui --noprompt gem2pa $gem $physicalRaw 2>&1|Set-Content -LiteralPath $buildLog
      if($LASTEXITCODE-ne0){throw 'Canonical corridor GEM compilation failed.'}
      $mapping=@($plan.physical_to_local_electrode_id.PSObject.Properties|Sort-Object {[int]$_.Name}|ForEach-Object{"$($_.Name):$($_.Value)"})-join','
      & $simion --nogui --noprompt lua (Join-Path $repoRoot 'common\simion\remap_pa_electrode_ids.lua') $physicalRaw $rawScratch $mapping 2>&1|Add-Content -LiteralPath $buildLog
      if($LASTEXITCODE-ne0){throw 'Canonical corridor electrode remap failed.'}
      Publish-NativeCorridorBuiltMember -ScratchPath (Join-Path $scratchDirectory 'mrtof_analyzer_corridor.pa#') -DestinationPath (Join-Path $buildDirectory 'mrtof_analyzer_corridor.pa#')
    }
    if('mrtof_analyzer_corridor.pa0'-in$missing){
      $controllerDirectory=Join-Path $scratchDirectory 'controller'
      New-Item -ItemType Directory -Force -Path $controllerDirectory|Out-Null
      $controllerAlias=New-RunExecutionAlias -TargetDirectory $controllerDirectory;$aliases+=@($controllerAlias)
      $controllerRaw=Join-Path $controllerDirectory 'mrtof_analyzer_corridor.pa#'
      $controllerRawExecution=Join-Path ([string]$controllerAlias.execution_alias) 'mrtof_analyzer_corridor.pa#'
      $controllerScratch=Join-Path ([string]$controllerAlias.execution_alias) 'mrtof_analyzer_corridor.pa0'
      Copy-Item -LiteralPath (Join-Path $buildDirectory 'mrtof_analyzer_corridor.pa#') -Destination $controllerRaw
      try{
        & $simion --nogui --noprompt lua (Join-Path $PSScriptRoot 'create_native_corridor_controller.lua') $controllerRawExecution $controllerScratch 2>&1|Add-Content -LiteralPath $buildLog
        if($LASTEXITCODE-ne0){throw 'Native-corridor controller creation failed.'}
        Publish-NativeCorridorBuiltMember -ScratchPath (Join-Path $controllerDirectory 'mrtof_analyzer_corridor.pa0') -DestinationPath (Join-Path $buildDirectory 'mrtof_analyzer_corridor.pa0')
      }finally{
        Remove-Item -LiteralPath $controllerRaw -Force -ErrorAction SilentlyContinue
      }
    }
    Exit-HostExecutionLease -Lease $lease -Outcome success -RunId $RunId;$lease=$null
    $responseIds=@(1..8|Where-Object{('mrtof_analyzer_corridor.pa{0}'-f$_)-in$missing})
    if($responseIds.Count-gt0){
      Invoke-NativeCorridorResponseWave -ResponseIds $responseIds -BuildDirectory $buildDirectory `
        -ScratchDirectory $scratchDirectory -CoarseRawGeometryPath $CoarseRawGeometryPath -CoarseOrigin $CoarseOrigin
    }
  }finally{
    if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome failed -RunId $RunId}
    foreach($alias in @($aliases)){Remove-RunExecutionAlias -ExecutionAlias ([string]$alias.execution_alias) -TargetDirectory ([string]$alias.target_directory)}
  }
}

function Invoke-NativeCorridorFamilyPreverification {
  param(
    [Parameter(Mandatory)][pscustomobject]$State,
    [Parameter(Mandatory)][string]$OutputPath
  )
  if(-not(Test-Path -LiteralPath $simion -PathType Leaf)){throw "SIMION executable is missing: $simion"}
  $buildDirectory=[IO.Path]::GetFullPath([string]$State.build_directory)
  $verifier=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'verify_native_corridor_family.lua')).Path
  $alias=$null;$lease=$null
  try{
    $alias=New-RunExecutionAlias -TargetDirectory $buildDirectory
    $lease=Enter-HostExecutionLease -Role SIMION -Stage prepare -RunId $RunId
    $controller=Join-Path ([string]$alias.execution_alias) 'mrtof_analyzer_corridor.pa0'
    $lines=@(& $simion --nogui --noprompt lua $verifier $controller 2>&1|Tee-Object -FilePath $OutputPath)
    if($LASTEXITCODE-ne0-or-not(@($lines|ForEach-Object{"$_"})-contains'MRTOF_NATIVE_CORRIDOR_FAMILY_VERIFY=PASS members=pa0..pa8 fast_adjust=verified')){
      throw 'Persisted native-corridor family failed SIMION verification.'
    }
    Exit-HostExecutionLease -Lease $lease -Outcome success -RunId $RunId;$lease=$null
  }finally{
    if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome failed -RunId $RunId}
    if($null-ne$alias){Remove-RunExecutionAlias -ExecutionAlias ([string]$alias.execution_alias) -TargetDirectory ([string]$alias.target_directory)}
  }
  return (Resolve-Path -LiteralPath $OutputPath).Path
}

function Write-NativeCorridorFamilyVerificationEvidence {
  param(
    [Parameter(Mandatory)][pscustomobject]$State,
    [Parameter(Mandatory)][string]$VerifiedOutputPath,
    [Parameter(Mandatory)][string]$EvidencePath
  )
  if([string]::IsNullOrWhiteSpace([string]$State.inventory_sha256)){
    throw 'Native-corridor verification evidence requires the final sealed inventory identity.'
  }
  $resolvedOutput=(Resolve-Path -LiteralPath $VerifiedOutputPath).Path
  $verifier=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'verify_native_corridor_family.lua')).Path
  Write-RunJson -Path $EvidencePath -Depth 10 -Value ([ordered]@{
    schema_version=1;role='simion_pa_family_verification';status='pass'
    cache_key=[string]$State.cache_key;inventory_sha256=[string]$State.inventory_sha256
    solver_release='SIMION 2020';verifier_path=$verifier
    verifier_sha256=(Get-FileHash -LiteralPath $verifier -Algorithm SHA256).Hash.ToUpperInvariant()
    verification_output_path=$resolvedOutput
    verification_output_sha256=(Get-FileHash -LiteralPath $resolvedOutput -Algorithm SHA256).Hash.ToUpperInvariant()
  })
  return (Resolve-Path -LiteralPath $EvidencePath).Path
}

if($InternalResponseId-gt0){
  foreach($value in @($InternalBuildDirectory,$InternalScratchDirectory,$InternalCoarseRawGeometryPath,$InternalCoarseOrigin)){
    if([string]::IsNullOrWhiteSpace($value)){throw 'Internal response worker requires complete transaction paths and coarse origin.'}
  }
  Invoke-NativeCorridorResponseMemberBuild -ResponseId $InternalResponseId `
    -BuildDirectory $InternalBuildDirectory -ScratchDirectory $InternalScratchDirectory `
    -CoarseRawGeometryPath $InternalCoarseRawGeometryPath -CoarseOrigin $InternalCoarseOrigin
  exit 0
}
if(@($InternalBuildDirectory,$InternalScratchDirectory,$InternalCoarseRawGeometryPath,$InternalCoarseOrigin)|Where-Object{-not[string]::IsNullOrWhiteSpace($_)}){
  throw 'Internal response worker paths are forbidden without InternalResponseId.'
}

$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $projectArtifactRoot `
  -RunId $RunId -Project $projectId -Mode 'native_corridor_pa_family_qualification' `
  -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass compact `
  -CapacityLedgerLifecycleEnabled -UseShortExecutionPath
$runConfig=$package.run_config;$summary=$package.summary;$resultDir=$package.result_dir
$startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json'
$terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json'
$publicationPath=Join-Path $resultDir 'pa_family_cache_publication.json'
$verificationLog=Join-Path $resultDir 'native_corridor_family_verification.log'
$verificationEvidence=Join-Path $resultDir 'native_corridor_family_verification.json'
$nativeCorridorDispatchArtifacts=@()
$capacitySession=$null;$writerLock=$null;$terminalized=$false;$failureStage='frozen_input_validation';$cacheKey=''
try{
  $freezeManifest=Get-Content -LiteralPath $freezeManifestPath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 20
  if([string]$freezeManifest.role-ne'mrtof_native_corridor_frozen_inputs'-or[string]$freezeManifest.status-ne'frozen'){throw 'Frozen native-corridor package differs.'}
  foreach($record in @($freezeManifest.files)){
    $path=Join-Path $frozenDirectory ([string]$record.name)
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)-or[int64](Get-Item -LiteralPath $path).Length-ne[int64]$record.bytes-or
       (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash-ne[string]$record.sha256){throw "Frozen input identity differs: $path"}
  }
  $probe=(@(Invoke-ProjectPython -Arguments @('-m','common.simion.pa_family_cache','--action','probe','--cache-root',$cacheRoot,'--identity',$identityPath,'--filenames',($familyMembers-join',')))-join"`n")|ConvertFrom-Json -Depth 30
  if([string]$probe.disposition-notin@('hit','miss')){throw "Native-corridor cache is unusable: $($probe.detail)"}
  $cacheKey=[string]$probe.cache_key
  [int64]$remainingPeakBytes=0;$coarseRaw='';$coarseOrigin=''
  if([string]$probe.disposition-eq'miss'){
    $plan=Get-Content -LiteralPath $planPath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 30
    $remainingPeakBytes=Get-NativeCorridorRemainingPeakBytes -Plan $plan -CacheKey $cacheKey
    $recipe=Get-Content -LiteralPath $recipePath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 30
    $coarseKey=([string]$recipe.coarse_raw_generation_identity.cache_key).ToUpperInvariant()
    $coarseGeneration=([string]$recipe.coarse_raw_generation_identity.generation_sha256).ToUpperInvariant()
    $coarseGenerationDirectory=Join-Path $cacheRoot "$coarseKey\generations\$coarseGeneration"
    $coarseManifest=Get-Content -LiteralPath (Join-Path $coarseGenerationDirectory 'cache_manifest.json') -Raw -Encoding UTF8|ConvertFrom-Json -Depth 30
    $coarseRaw=Join-Path $coarseGenerationDirectory ([string]$recipe.coarse_raw_member.name)
    if(-not(Test-Path -LiteralPath $coarseRaw -PathType Leaf)){throw "Frozen coarse raw member is missing: $coarseRaw"}
    $coarseOrigin=@($coarseManifest.identity.grid_phase.analyzer_origin_mm)-join','
  }
  $failureStage='capacity_startup'
  $capacitySession=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot $artifactRoot -RunDirectory $package.artifact_run_dir -CommittedNewBytes $remainingPeakBytes `
    -ProtectedPaths @($package.artifact_run_dir,$frozenDirectory) -ProtectedCacheKeys @($cacheKey) -Owner "mrtof-native-corridor:$RunId"
  Write-RunJson -Path $startupPath -Depth 14 -Value $capacitySession.startup_gate
  if([string]$probe.disposition-eq'miss'){
    $failureStage='transaction_writer_lock'
    $writerLock=Enter-NativeCorridorWriterLock -Root $cacheRoot -CacheKey $cacheKey
  }
  $advance={param($evidence)
    $arguments=Get-NativeCorridorTransactionArguments -VerificationEvidence $evidence
    return ((@(Invoke-ProjectPython -Arguments $arguments)-join"`n")|ConvertFrom-Json -Depth 40)
  }
  $build={param($state)
    $script:failureStage='transaction_build'
    Invoke-NativeCorridorFamilyBuild -State $state -CapacitySession $capacitySession `
      -CacheKey $cacheKey -CoarseRawGeometryPath $coarseRaw -CoarseOrigin $coarseOrigin
  }
  $preverify={param($state)
    $script:failureStage='transaction_preverify'
    Invoke-NativeCorridorFamilyPreverification -State $state -OutputPath $verificationLog
  }
  $bindEvidence={param($state,$verifiedOutput)
    $script:failureStage='transaction_bind_verification_evidence'
    Write-NativeCorridorFamilyVerificationEvidence -State $state -VerifiedOutputPath $verifiedOutput -EvidencePath $verificationEvidence
  }
  $publication=Invoke-NativeCorridorTransactionLoop -Advance $advance -Build $build `
    -Preverify $preverify -BindEvidence $bindEvidence
  if([string]$publication.status-ne'published'-or[string]$publication.action_required-ne'complete'){throw 'Native-corridor transaction did not publish.'}
  Write-RunJson -Path $publicationPath -Depth 30 -Value $publication
  $failureStage='capacity_terminal'
  $terminal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession `
    -ProtectedPaths @($package.artifact_run_dir,$frozenDirectory) -ProtectedCacheKeys @($cacheKey) -RemainingCommittedNewBytes 0
  $capacitySession=$terminal.session;Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  Write-RunJson -Path $summary -Depth 20 -Value ([ordered]@{schema_version=1;role='mrtof_native_corridor_pa_family_qualification';status='success';qualification='native_family_cached__materialization_iob_equivalence_and_flight_pending';cache_key=$cacheKey;generation_sha256=[string]$publication.generation_sha256})
  $config=Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $config.inputs=[ordered]@{frozen_input_directory=$frozenDirectory;frozen_identity=$identityPath;frozen_plan=$planPath;frozen_response_recipe=$recipePath;frozen_manifest=$freezeManifestPath}
  $config.parameters=[ordered]@{cache_key=$cacheKey;transaction_state='published';startup_peak_commitment_bytes=$remainingPeakBytes;remaining_peak_commitment_bytes=0}
  Write-RunJson -Path $runConfig -Depth 30 -Value $config
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $outputs=@(@($summary,$publicationPath,$verificationLog,$verificationEvidence,$startupPath,$terminalPath,$retention)+@($nativeCorridorDispatchArtifacts))|Where-Object{Test-Path -LiteralPath $_ -PathType Leaf}
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success -Software @('SIMION 2020','Python 3.11') -Outputs $outputs
  $terminalized=$true
  Write-Host "MRTOF_NATIVE_CORRIDOR_QUALIFICATION=PASS RUN_ID=$RunId CACHE_KEY=$cacheKey"
}catch{
  if(-not$terminalized){
    $outputs=@(@($verificationLog,$verificationEvidence,$startupPath)+@($nativeCorridorDispatchArtifacts))|Where-Object{Test-Path -LiteralPath $_ -PathType Leaf}
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
      -SummaryRole 'mrtof_native_corridor_pa_family_qualification' -Reason $_.Exception.Message `
      -Software @('SIMION 2020','Python 3.11') -Status failed -FailureStage $failureStage -AdditionalOutputs $outputs
    $terminalized=$true
  }
  throw
}finally{
  try{Exit-NativeCorridorWriterLock -Lock $writerLock}
  finally{
    try{if($null-ne$capacitySession){$null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession}}
    finally{Remove-RunPackageExecutionAlias -Package $package}
  }
}
