param([string]$HostContextJson,[string]$WorkingDirectory,[string]$ComsolLauncherPath,[string]$MatlabRootPath,[string]$TaskScript,[string]$ReportPath,[int]$StartupAttempts,[string]$RunId,[string]$RunDir,[string]$CompletionPath)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
# Synthetic launcher for test transport only; it does not run MATLAB or COMSOL.
$context=$HostContextJson | ConvertFrom-Json
$control=Get-Content -Raw -LiteralPath (Join-Path $context.workspace 'inert-control.json') | ConvertFrom-Json
$op=[IO.Path]::GetFileNameWithoutExtension($TaskScript)
$root=Split-Path -Parent (Split-Path -Parent $TaskScript)
$request=Get-Content -Raw -LiteralPath (Join-Path $root 'inputs/electrostatic_request.json') | ConvertFrom-Json
$baseline=Get-Content -Raw -LiteralPath (Join-Path $root 'inputs/geometry/reopen_geometry.json') | ConvertFrom-Json
$output=Join-Path $root 'assembly-electrostatic-unsolved.mph'
if($op -eq 'build_model') {[IO.File]::WriteAllBytes($output,[Text.Encoding]::UTF8.GetBytes('SYNTHETIC_NOT_A_COMSOL_MODEL'))}
if($control.case -eq 'model_tamper' -and $op -eq 'reopen_model') {[IO.File]::WriteAllBytes($output,[Text.Encoding]::UTF8.GetBytes('TAMPERED_SYNTHETIC_MODEL'))}
$mode=if($op -eq 'build_model') {'build'} else {'reopen'}
$report=[ordered]@{operation=$mode;scope='assembly_electrostatic_unsolved';model_path=$output;group_keys=@($baseline.group_keys);group_faces=@($baseline.group_faces);vacuum_domains=@($baseline.vacuum_domains);outer_faces=@($baseline.outer_faces);group_voltages_v=@($request.group_voltages | ForEach-Object {$_.voltage_v});relative_permittivity=$request.relative_permittivity;exterior_voltage_v=$request.exterior.voltage_v;mesh=$request.mesh;compute_calls=0;solution_count=0;model_rewritten=($mode -eq 'build')}
$report | ConvertTo-Json -Depth 50 -Compress | Set-Content -LiteralPath (Join-Path $root "results/$op.json") -Encoding utf8NoBOM
'STATUS=PASS' | Set-Content -LiteralPath $ReportPath -Encoding utf8NoBOM
$nestedCode=if($control.case -eq 'process_failure' -and $op -eq 'build_model') {23} else {0}
$nested=Start-Process -FilePath (Get-Process -Id $PID).Path -ArgumentList @('-NoProfile','-Command',"Start-Sleep -Milliseconds 250; exit $nestedCode") -WindowStyle Hidden -PassThru
$nestedStarted=$nested.StartTime.ToUniversalTime().Ticks
$nested.WaitForExit()
$receipt=@{schema_version=1;role='comsol_launcher_completion';run_id=$RunId;operations=@(@{observation=@{exit_confirmed=$true;returncode=$nested.ExitCode;process_id=$nested.Id;process_started_at_utc_ticks=$nestedStarted}});host_release=@{inherited=$true;token=$null;result=$null;error=$null}}
$receipt | ConvertTo-Json -Depth 10 -Compress | Set-Content -LiteralPath $CompletionPath -Encoding utf8NoBOM
if($control.case -eq 'source_tamper' -and $op -eq 'build_model') {[IO.File]::AppendAllText([string]$control.source_path,' ')}
if($control.case -eq 'process_failure' -and $op -eq 'build_model') {exit 23}
