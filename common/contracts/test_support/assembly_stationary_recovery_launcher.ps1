param([string]$HostContextJson,[string]$WorkingDirectory,[string]$ComsolLauncherPath,[string]$MatlabRootPath,[string]$TaskScript,[string]$ReportPath,[int]$StartupAttempts,[string]$RunId,[string]$RunDir,[string]$CompletionPath)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$context=$HostContextJson | ConvertFrom-Json
$control=Get-Content -Raw -LiteralPath (Join-Path $context.workspace 'inert-control.json') | ConvertFrom-Json
$op=[IO.Path]::GetFileNameWithoutExtension($TaskScript)
$root=Split-Path -Parent (Split-Path -Parent $TaskScript)
$raw=Join-Path $root 'assembly-stationary-computed-raw.mph'
$output=Join-Path $root 'assembly-stationary-field.mph'
if($op -eq 'solve_stationary') {
 [IO.File]::WriteAllBytes($raw,[Text.Encoding]::UTF8.GetBytes('INERT_RAW'))
 if($control.case -eq 'reopen_failure') {
  [IO.File]::WriteAllBytes($output,[Text.Encoding]::UTF8.GetBytes('INERT_FINAL'))
  $report=@{operation='compute';scope='single_stationary_workpoint';model_path=$output;compute_calls=1;group_keys=@('rf/drive');group_faces=@(,@(2,3));vacuum_domains=@(1);outer_faces=@(4,5);solution=@{study_tag='std1';solution_tag='sol1';dataset_tag='assembly_field_solution';dataset_solution='sol1';solution_empty=$false;solution_count=1;stored_main_solutions=1;solution_dofs=4;solver_policy='comsol_stationary_default';solver_type='stationary';solver_sequence_type='Stationary';solver_features=@('s1');comsol_version='synthetic'}}
  $report | ConvertTo-Json -Depth 20 -Compress | Set-Content -LiteralPath (Join-Path $root 'results/solve_stationary.json') -Encoding utf8NoBOM
 }
}
if($control.case -eq 'recovery') {
 if($op -ne 'reopen_solution') { throw 'Recovery must only reopen' }
 if(-not (Get-Content -Raw -LiteralPath $TaskScript).Contains("'recover'")) { throw 'Task is not recovery mode' }
 $borrowed=[string]$control.borrowed_model
 if(-not (Test-Path -LiteralPath $borrowed -PathType Leaf)) { throw 'Borrowed source missing' }
 $report=@{operation='recover';scope='single_stationary_workpoint';model_path=$borrowed;compute_calls=0;group_keys=@('rf/drive');group_faces=@(,@(2,3));vacuum_domains=@(1);outer_faces=@(4,5);solution=@{study_tag='std1';solution_tag='sol1';dataset_tag='assembly_field_solution';dataset_solution='sol1';solution_empty=$false;solution_count=1;stored_main_solutions=1;solution_dofs=4;solver_policy='comsol_stationary_default';solver_type='stationary';solver_sequence_type='Stationary';solver_features=@('s1');comsol_version='synthetic'}}
 $report | ConvertTo-Json -Depth 20 -Compress | Set-Content -LiteralPath (Join-Path $root 'results/reopen_solution.json') -Encoding utf8NoBOM
}
'STATUS=PASS' | Set-Content -LiteralPath $ReportPath -Encoding utf8NoBOM
$code=if(($control.case -eq 'compute_failure' -and $op -eq 'solve_stationary') -or ($control.case -eq 'reopen_failure' -and $op -eq 'reopen_solution')) {23} else {0}
$child=Start-Process -FilePath (Get-Process -Id $PID).Path -ArgumentList @('-NoProfile','-Command',"Start-Sleep -Milliseconds 250; exit $code") -WindowStyle Hidden -PassThru
$ticks=$child.StartTime.ToUniversalTime().Ticks
$child.WaitForExit()
$receipt=@{schema_version=1;role='comsol_launcher_completion';run_id=$RunId;operations=@(@{observation=@{exit_confirmed=$true;returncode=$child.ExitCode;process_id=$child.Id;process_started_at_utc_ticks=$ticks}});host_release=@{inherited=$true;token=$null;result=$null;error=$null}}
$receipt | ConvertTo-Json -Depth 10 -Compress | Set-Content -LiteralPath $CompletionPath -Encoding utf8NoBOM
if($code -ne 0) {exit $code}
