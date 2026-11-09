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
$guards=[Collections.Generic.List[string]]::new()
try{
  $lease=Enter-HostExecutionLease -Role $request.role -Stage $request.stage -RunId $request.run_id
  $protected=$request.ContainsKey('immutable_input_records')-and@($request.immutable_input_records).Count-gt0
  if($protected){
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
  $observation=Invoke-ResourceBudgetedProcess -Limits $limits -RunDir $request.run_directory `
    -UsagePath $request.usage_path -FilePath $request.executable -ArgumentList @($request.argument_line) `
    -WorkingDirectory $request.working_directory -RedirectStandardOutput $request.stdout_path `
    -RedirectStandardError $request.stderr_path -Environment $request.environment -WindowStyle $windowStyle -RequireImmutableInputDrain:$protected `
    -ProcessObservationMetadata @{run_id=$request.run_id;role=$request.role;stage=$request.stage}
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
    $release=@{inherited=[bool]$lease.inherited;token=[string]$lease.token;result=$null;error=$null}
    try{$release.result=Exit-HostResourceStage -Lease $lease -PassThru}
    catch{$release.error=$_.Exception.Message}
  }
}
$envelope=@{observation=$observation;error=$failure;host_release=$release}
[Console]::Out.WriteLine('EXECUTION_PROCESS_RESULT='+($envelope|ConvertTo-Json -Depth 24 -Compress))
if($null-ne$failure-or$null-eq$release-or$release.error-or
  (-not$release.inherited-and($null-eq$release.result-or$release.result.status-ne'released'))){exit 1}
exit 0
