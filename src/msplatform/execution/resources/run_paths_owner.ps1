<# Explicit JSON transport for the original run-path/alias implementation. #>
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$request=[Console]::In.ReadToEnd()|ConvertFrom-Json -AsHashtable
. (Join-Path $PSScriptRoot 'run_paths.ps1')
switch($request.action){
 'capacity' {$value=Get-ExecutionPathCapacity -RunDirectory $request.run_directory -AdditionalDirectories @($request.additional_directories) -ExpectedExecutionRelativePaths @($request.expected_relative_paths)}
 'create' {$value=New-ManagedExecutionAlias -TargetDirectory $request.run_directory -ExecutionRoot $request.execution_root -AdditionalDirectories @($request.additional_directories) -ExpectedExecutionRelativePaths @($request.expected_relative_paths)}
 'remove' {Remove-ManagedExecutionAlias -ExecutionAlias $request.execution_alias -TargetDirectory $request.run_directory;$value=@{removed=$true}}
 default {throw 'Unsupported execution path operation.'}
}
[Console]::Out.WriteLine('EXECUTION_PATH_RESULT='+($value|ConvertTo-Json -Depth 16 -Compress))
