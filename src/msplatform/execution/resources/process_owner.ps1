<# JSON transport to the one installed host/process owner. No scientific policy. #>
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$request=[Console]::In.ReadToEnd()|ConvertFrom-Json -AsHashtable
$windowStyle=if($request.ContainsKey('window_style')){$request.window_style}else{'Hidden'}
if($windowStyle-isnot[string]-or@('Hidden','Normal')-cnotcontains$windowStyle){throw 'window_style requires exactly Hidden or Normal'}
. (Join-Path $PSScriptRoot 'host_execution_lease.ps1') -HostContext $request.context
. (Join-Path $PSScriptRoot 'resource_process_support.ps1')
$lease=$null;$failure=$null;$observation=$null;$release=$null
$native=$null;$bindingId=$null;$parentStarted=$null
function Write-NativeControlJson($Path,$Value){
  $temporary="$Path.tmp"
  [IO.File]::WriteAllText($temporary,($Value|ConvertTo-Json -Depth 30 -Compress),[Text.UTF8Encoding]::new($false))
  Move-Item -LiteralPath $temporary -Destination $Path -Force
}
function Test-NativeParentAlive {
  try{$p=Get-Process -Id ([int]$native.parent_pid) -ErrorAction Stop
    return $p.StartTime.ToUniversalTime().Ticks-eq$parentStarted
  }catch{return $false}
}
$guards=[Collections.Generic.List[string]]::new()
try{
  $lease=Enter-HostExecutionLease -Role $request.role -Stage $request.stage -RunId $request.run_id
  if($request.ContainsKey('native_artifact')){
    $native=$request.native_artifact
    if($lease.inherited){throw 'Protected native operation requires its own non-inherited host owner.'}
    if($native.nonce-cnotmatch'^[a-f0-9]{32}$'){throw 'Invalid native control nonce.'}
    $parentStarted=(Get-Process -Id ([int]$native.parent_pid) -ErrorAction Stop).StartTime.ToUniversalTime().Ticks
    Write-NativeControlJson $native.host @{nonce=$native.nonce;token=$lease.token;inherited=$false}
    while(-not(Test-Path -LiteralPath $native.ack -PathType Leaf)){
      if(-not(Test-NativeParentAlive)){throw 'Native controller exited before launch authorization.'}
      Start-Sleep -Milliseconds 30
    }
    $ack=Get-Content -LiteralPath $native.ack -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    if($ack.nonce-cne$native.nonce-or-not$ack.binding_id){throw 'Native launch authorization differs.'}
    $bindingId=[string]$ack.binding_id
  }
  $sessionProtected=$request.ContainsKey('immutable_input_session')
  $protected=($request.ContainsKey('immutable_input_records')-and@($request.immutable_input_records).Count-gt0)-or$sessionProtected
  if($sessionProtected){
    $credential=$request.immutable_input_session
    $expectedCredential=@('schema_version','role','run_id','operation_id','lease_id','artifact_root','lease_owner','holder_pid','holder_started_at_utc_ticks')
    if(@($credential.Keys|Where-Object{$_-cnotin$expectedCredential}).Count-ne0-or
       @($expectedCredential|Where-Object{-not$credential.ContainsKey($_)}).Count-ne0-or
       $credential.schema_version-ne1-or$credential.role-cne'run_immutable_input_session'-or
       $credential.run_id-cne$request.run_id-or$credential.operation_id-isnot[string]-or-not$credential.operation_id-or
       $credential.lease_id-isnot[string]-or-not$credential.lease_id-or
       $credential.artifact_root-isnot[string]-or-not[IO.Path]::IsPathFullyQualified($credential.artifact_root)-or
       $credential.lease_owner-isnot[string]-or-not$credential.lease_owner-or
       $credential.holder_pid-isnot[long]-and$credential.holder_pid-isnot[int]-or$credential.holder_pid-le0-or
       $credential.holder_started_at_utc_ticks-isnot[long]-or$credential.holder_started_at_utc_ticks-le0){throw 'Invalid immutable input session credential.'}
    $holder=Get-Process -Id $credential.holder_pid -ErrorAction Stop
    if($holder.StartTime.ToUniversalTime().Ticks-ne$credential.holder_started_at_utc_ticks){
      throw 'Immutable input session holder identity differs.'
    }
    $leaseState=& $request.context.python_executable -I -B -c 'import sys;from pathlib import Path;sys.path.insert(0,str(Path(sys.argv[4]).parents[2]));from msplatform.execution.capacity_protection import load_capacity_protection_leases;view=load_capacity_protection_leases(Path(sys.argv[1]));matches=[row for row in view["audit"] if row.get("lease_id")==sys.argv[2] and row.get("status")=="active" and row.get("owner")==sys.argv[3]];print("ACTIVE" if len(matches)==1 else "INVALID")' $credential.artifact_root $credential.lease_id $credential.lease_owner $PSScriptRoot
    if($LASTEXITCODE-ne0-or$leaseState-cne'ACTIVE'){throw 'Immutable input session capacity lease is not active.'}
  }
  if($request.ContainsKey('immutable_input_records')-and@($request.immutable_input_records).Count-gt0){
    . (Join-Path $PSScriptRoot 'payload_file_support.ps1') -UnbufferedIdentityReader {
      param([string]$Source,[int64]$Length)
      $digest=& $request.context.python_executable -I -B -c 'from msplatform.io.file_identity import file_sha256_unbuffered;import sys;print(file_sha256_unbuffered(sys.argv[1]))' $Source
      if($LASTEXITCODE-ne0){throw 'Immutable input unbuffered identity verification failed.'}
      $digest
    }
    foreach($record in $request.immutable_input_records){
      if(-not[IO.Path]::IsPathFullyQualified([string]$record.path)-or$record.exists-isnot[bool]-or-not$record.exists-or
         $record.bytes-is[bool]-or$record.bytes-isnot[long]-and$record.bytes-isnot[int]-or$record.bytes-lt0-or
         [string]$record.sha256-cnotmatch'^[A-Fa-f0-9]{64}$'){throw 'Invalid immutable input record.'}
      $guard=Protect-ImmutablePaSource -Source $record.path -ExpectedBytes $record.bytes -ExpectedSha256 $record.sha256
      if(-not$guard.already_protected){$guards.Add([string]$guard.path)}
    }
  }
  $limits=if($null-eq$request.limits){$null}else{[pscustomobject]$request.limits}
  $onStarted=$null
  if($null-ne$native){
    $onStarted={param($Process,$Started)
      $null=Register-HostResourceProcess -Lease $lease -ProcessId $Process.Id
      $registered=[int64]$lease.registered_work_processes[[string]$Process.Id]
      Write-NativeControlJson $native.worker @{nonce=$native.nonce;binding_id=$bindingId;
        process_id=[int]$Process.Id;started_at_utc_ticks=$registered}
      while(-not(Test-Path -LiteralPath $native.'worker-ack' -PathType Leaf)){
        if(-not(Test-NativeParentAlive)){break}
        Start-Sleep -Milliseconds 30
      }
      if(Test-Path -LiteralPath $native.'worker-ack' -PathType Leaf){
        $workerAck=Get-Content -LiteralPath $native.'worker-ack' -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
        if($workerAck.nonce-cne$native.nonce-or$workerAck.binding_id-cne$bindingId){throw 'Native worker acknowledgement differs.'}
      }
    }
  }
  $observation=Invoke-ResourceBudgetedProcess -Limits $limits -RunDir $request.run_directory `
    -UsagePath $request.usage_path -FilePath $request.executable -ArgumentList @($request.argument_line) `
    -WorkingDirectory $request.working_directory -RedirectStandardOutput $request.stdout_path `
    -RedirectStandardError $request.stderr_path -Environment $request.environment -WindowStyle $windowStyle -RequireImmutableInputDrain:($protected-or$null-ne$native) `
    -ProcessObservationMetadata @{run_id=$request.run_id;role=$request.role;stage=$request.stage} -OnStarted $onStarted
}catch{
  $failure=@{type=$_.Exception.GetType().FullName;message=$_.Exception.Message;data=@{}}
  foreach($key in $_.Exception.Data.Keys){$failure.data[[string]$key]=$_.Exception.Data[$key]}
}finally{
  foreach($path in $guards){
    try{$null=Unprotect-ImmutablePaSource -Source $path}
    catch{if($null-eq$failure){$failure=@{type=$_.Exception.GetType().FullName;message=$_.Exception.Message;data=@{}}}
      else{$failure.data['immutable_input_release_error']=$_.Exception.Message}}
  }
  if($null-ne$lease){
    $release=@{inherited=[bool]$lease.inherited;token=[string]$lease.token;result=$null;error=$null
      admission_wait_seconds=[double]$lease.admission_wait_seconds;initial_wait_reason=[string]$lease.initial_wait_reason}
    try{$release.result=Exit-HostResourceStage -Lease $lease -PassThru}
    catch{$release.error=$_.Exception.Message}
  }
}
$envelope=@{observation=$observation;error=$failure;host_release=$release}
if($null-ne$native-and$bindingId){
  Write-NativeControlJson $native.receipt @{nonce=$native.nonce;binding_id=$bindingId;receipt=$envelope}
}
[Console]::Out.WriteLine('EXECUTION_PROCESS_RESULT='+($envelope|ConvertTo-Json -Depth 24 -Compress))
if($null-ne$failure-or$null-eq$release-or$release.error-or
  (-not$release.inherited-and($null-eq$release.result-or$release.result.status-ne'released'))){exit 1}
exit 0
