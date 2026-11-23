param([string]$HostContextJson,[string]$WorkingDirectory,[string]$ComsolLauncherPath,[string]$MatlabRootPath,[string]$TaskScript,[string]$ReportPath,[int]$StartupAttempts,[string]$RunId,[string]$RunDir,[string]$CompletionPath)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
# Inert fixture: no COMSOL or MATLAB is launched.
$context=$HostContextJson | ConvertFrom-Json
$control=Get-Content -Raw -LiteralPath (Join-Path $context.workspace 'scalar-inert-control.json') | ConvertFrom-Json
$root=Split-Path -Parent (Split-Path -Parent $TaskScript)
Copy-Item -LiteralPath $control.potential -Destination (Join-Path $root 'scalar/field_v.pa')
Copy-Item -LiteralPath $control.mask -Destination (Join-Path $root 'scalar/field_valid.pa')
Copy-Item -LiteralPath $control.report -Destination (Join-Path $root 'results/export_world_scalar.json')
'STATUS=PASS' | Set-Content -LiteralPath $ReportPath -Encoding utf8NoBOM
if($control.case -eq 'tamper') {[IO.File]::AppendAllText((Join-Path $root 'inputs/scalar_support/0/assembly_scalar_fill.py'),' ')}
$nested=Start-Process -FilePath (Get-Process -Id $PID).Path -ArgumentList @('-NoProfile','-Command','exit 0') -WindowStyle Hidden -PassThru
$started=$nested.StartTime.ToUniversalTime().Ticks
$nested.WaitForExit()
$receipt=@{schema_version=1;role='comsol_launcher_completion';run_id=$RunId;operations=@(@{observation=@{exit_confirmed=$true;returncode=$nested.ExitCode;process_id=$nested.Id;process_started_at_utc_ticks=$started}});host_release=@{inherited=$true;token=$null;result=$null;error=$null}}
$receipt | ConvertTo-Json -Depth 10 -Compress | Set-Content -LiteralPath $CompletionPath -Encoding utf8NoBOM
