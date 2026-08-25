Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

if(-not('MultipoleMemoryStatus' -as[type])){
  Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class MultipoleMemoryStatus {
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Auto)]
  public class Status {
    public uint length=(uint)Marshal.SizeOf(typeof(Status));
    public uint load; public ulong totalPhysical; public ulong availablePhysical;
    public ulong totalPage; public ulong availablePage; public ulong totalVirtual;
    public ulong availableVirtual; public ulong availableExtended;
  }
  [DllImport("kernel32.dll", CharSet=CharSet.Auto, SetLastError=true)]
  static extern bool GlobalMemoryStatusEx([In,Out] Status status);
  public static ulong AvailableBytes() {
    var status=new Status();
    if(!GlobalMemoryStatusEx(status)) throw new InvalidOperationException("GlobalMemoryStatusEx failed.");
    return status.availablePhysical;
  }
}
'@
}

function Get-RunDirectoryBytes {
  param([Parameter(Mandatory)][string]$RunDir)
  if(-not(Test-Path -LiteralPath $RunDir -PathType Container)){return [int64]0}
  $sum=(Get-ChildItem -LiteralPath $RunDir -Recurse -File -ErrorAction SilentlyContinue|
    Measure-Object -Property Length -Sum).Sum
  return $(if($null-eq$sum){[int64]0}else{[int64]$sum})
}

function Get-ProcessTreeWorkingSetBytes {
  param([Parameter(Mandatory)][int]$RootProcessId)
  $processes=@(Get-Process -ErrorAction SilentlyContinue)
  $ids=[Collections.Generic.HashSet[int]]::new()
  $null=$ids.Add($RootProcessId)
  $changed=$true
  while($changed){
    $changed=$false
    foreach($process in $processes){
      try{$parentId=[int]$process.Parent.Id}catch{continue}
      if($ids.Contains($parentId)-and$ids.Add([int]$process.Id)){$changed=$true}
    }
  }
  $sum=[int64]0
  foreach($processId in $ids){
    try{$sum+=[int64](Get-Process -Id $processId -ErrorAction Stop).WorkingSet64}catch{}
  }
  return $sum
}

function Write-ResourceUsage {
  param([Parameter(Mandatory)][hashtable]$Usage,[Parameter(Mandatory)][string]$Path)
  $temporary="$Path.tmp"
  $Usage|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $temporary -Encoding UTF8
  Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Invoke-ResourceBudgetedProcess {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$ResolvedBudgetPath,
    [Parameter(Mandatory)][string]$RunDir,
    [Parameter(Mandatory)][string]$UsagePath,
    [Parameter(Mandatory)][string]$FilePath,
    [Parameter(Mandatory)][string[]]$ArgumentList,
    [string]$WorkingDirectory='',
    [string]$RedirectStandardOutput='',
    [string]$RedirectStandardError='',
    [hashtable]$Environment=@{},
    [ValidateRange(0,2147483647)][int]$CalibrationDurationSeconds=0
  )
  $budget=Get-Content -LiteralPath $ResolvedBudgetPath -Raw -Encoding UTF8|ConvertFrom-Json
  $limits=$budget.limits
  $directorySampleProperty=$limits.PSObject.Properties[
    'transient_run_directory_sample_interval_seconds'
  ]
  $directorySampleIntervalSeconds=[double]0.5
  if($null-ne$directorySampleProperty){
    try{$directorySampleIntervalSeconds=[convert]::ToDouble(
      $directorySampleProperty.Value,[Globalization.CultureInfo]::InvariantCulture)}catch{
      throw 'Transient run-directory sample interval must be one positive integer.'
    }
    if($directorySampleProperty.Value-is[bool]-or
        $directorySampleIntervalSeconds-lt 1-or
        $directorySampleIntervalSeconds-ne[math]::Floor($directorySampleIntervalSeconds)){
      throw 'Transient run-directory sample interval must be one positive integer.'
    }
  }
  if(Test-Path -LiteralPath $UsagePath -PathType Leaf){
    $usage=Get-Content -LiteralPath $UsagePath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    $started=[datetimeoffset]::Parse([string]$usage.started_at_utc)
  }else{
    $started=[datetimeoffset]::UtcNow
    $usage=[ordered]@{
      schema_version=1;role='multipole_resource_usage';status='running'
      failure_class=$null;limit_name=$null;started_at_utc=$started.ToString('o')
      wall_clock_seconds=0.0;peak_process_tree_working_set_bytes=[int64]0
      minimum_system_available_memory_bytes=$null;warning_names=@();peak_run_directory_bytes=[int64]0
      final_retained_bytes=$null;limits=$limits
      final_retained_measurement_scope='run_directory_before_terminal_manifest'
    }
  }
  $startArguments=@{FilePath=$FilePath;ArgumentList=$ArgumentList;PassThru=$true;WindowStyle='Hidden'}
  if(-not[string]::IsNullOrWhiteSpace($WorkingDirectory)){$startArguments.WorkingDirectory=$WorkingDirectory}
  if(-not[string]::IsNullOrWhiteSpace($RedirectStandardOutput)){
    $startArguments.RedirectStandardOutput=$RedirectStandardOutput
  }
  if(-not[string]::IsNullOrWhiteSpace($RedirectStandardError)){
    $startArguments.RedirectStandardError=$RedirectStandardError
  }
  if($Environment.Count-gt 0){$startArguments.Environment=$Environment}
  $process=Start-Process @startArguments
  $resourceCalibrationComplete=$false
  $lastDirectorySampleAt=$null
  while(-not$process.HasExited){
    $now=[datetimeoffset]::UtcNow
    $elapsed=($now-$started).TotalSeconds
    $treeBytes=Get-ProcessTreeWorkingSetBytes -RootProcessId $process.Id
    $availableBytes=[int64][MultipoleMemoryStatus]::AvailableBytes()
    $sampleDirectory=$null-eq$lastDirectorySampleAt-or
      ($now-$lastDirectorySampleAt).TotalSeconds-ge$directorySampleIntervalSeconds
    if($sampleDirectory){
      $directoryBytes=Get-RunDirectoryBytes -RunDir $RunDir
      $lastDirectorySampleAt=$now
      $usage.peak_run_directory_bytes=[math]::Max(
        [int64]$usage.peak_run_directory_bytes,$directoryBytes)
    }
    $usage.wall_clock_seconds=[math]::Round($elapsed,3)
    $usage.peak_process_tree_working_set_bytes=[math]::Max(
      [int64]$usage.peak_process_tree_working_set_bytes,$treeBytes)
    $usage.minimum_system_available_memory_bytes=$(if($null-eq$usage.minimum_system_available_memory_bytes){
      $availableBytes
    }else{[math]::Min([int64]$usage.minimum_system_available_memory_bytes,$availableBytes)})
    Write-ResourceUsage -Usage $usage -Path $UsagePath
    # The scheduler chooses a wave before launch.  Once a solver process is
    # healthy, this observer records usage only: project contracts cannot turn
    # a sampled CPU/RAM/disk value into an automatic process termination.
    if($CalibrationDurationSeconds-gt 0-and$elapsed-ge$CalibrationDurationSeconds){
      & taskkill.exe /PID $process.Id /T /F|Out-Null
      $process.WaitForExit()
      $resourceCalibrationComplete=$true
      break
    }
    Start-Sleep -Milliseconds 500
    $process.Refresh()
  }
  $usage.wall_clock_seconds=[math]::Round(
    ([datetimeoffset]::UtcNow-$started).TotalSeconds,3)
  $directoryBytes=Get-RunDirectoryBytes -RunDir $RunDir
  $usage.peak_run_directory_bytes=[math]::Max(
    [int64]$usage.peak_run_directory_bytes,$directoryBytes)
  if($resourceCalibrationComplete){
    $usage.status='resource_calibration_complete'
    $usage.failure_class=$null
    $usage.resource_calibration=[ordered]@{
      scope='RESOURCE_CALIBRATION_ONLY'
      duration_seconds=$CalibrationDurationSeconds
      terminal_action='terminate_process_tree_then_replan'
      observed_peak_process_tree_working_set_bytes=[int64]$usage.peak_process_tree_working_set_bytes
    }
    Write-ResourceUsage -Usage $usage -Path $UsagePath
    return [pscustomobject]@{exit_code=0;resource_budget_exceeded=$false;limit_name=$null;
      resource_calibration_complete=$true;
      observed_peak_process_tree_working_set_bytes=[int64]$usage.peak_process_tree_working_set_bytes}
  }
  $usage.status=$(if($process.ExitCode-eq 0){'running'}else{'process_failed'})
  Write-ResourceUsage -Usage $usage -Path $UsagePath
  return [pscustomobject]@{exit_code=$process.ExitCode;resource_budget_exceeded=$false;limit_name=$null;
    resource_calibration_complete=$false}
}

function Invoke-ResourceBudgetedProcesses {
  <# Run an explicitly preflighted set of independent solver children in one wave.
     The resource limits apply to the aggregate, never per batch. #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$ResolvedBudgetPath,
    [Parameter(Mandatory)][string]$RunDir,
    [Parameter(Mandatory)][string]$UsagePath,
    [Parameter(Mandatory)][object[]]$ProcessSpecifications
  )
  if($ProcessSpecifications.Count-lt 1){throw 'A parallel process wave requires at least one specification.'}
  $budget=Get-Content -LiteralPath $ResolvedBudgetPath -Raw -Encoding UTF8|ConvertFrom-Json
  $limits=$budget.limits
  $started=[datetimeoffset]::UtcNow
  $usage=[ordered]@{
    schema_version=1;role='multipole_resource_usage';status='running'
    failure_class=$null;limit_name=$null;started_at_utc=$started.ToString('o')
    wall_clock_seconds=0.0;peak_process_tree_working_set_bytes=[int64]0
    minimum_system_available_memory_bytes=$null;warning_names=@();peak_run_directory_bytes=[int64]0
    final_retained_bytes=$null;limits=$limits
    final_retained_measurement_scope='run_directory_before_terminal_manifest'
    execution_wave=[ordered]@{dispatch='single_wave_parallel';process_count=$ProcessSpecifications.Count}
  }
  $running=@()
  foreach($specification in $ProcessSpecifications){
    foreach($required in @('name','file_path','argument_list','stdout','stderr','environment')){
      if(-not($specification.PSObject.Properties.Name-contains$required)){
        throw "Parallel process specification is missing $required."
      }
    }
    $arguments=@{FilePath=[string]$specification.file_path;ArgumentList=@($specification.argument_list);
      PassThru=$true;WindowStyle='Hidden';RedirectStandardOutput=[string]$specification.stdout;
      RedirectStandardError=[string]$specification.stderr;Environment=[hashtable]$specification.environment}
    if($specification.PSObject.Properties.Name-contains'working_directory'){
      $arguments.WorkingDirectory=[string]$specification.working_directory
    }
    $running+=[pscustomobject]@{name=[string]$specification.name;process=(Start-Process @arguments)}
  }
  while(@($running|Where-Object{-not$_.process.HasExited}).Count-gt 0){
    $now=[datetimeoffset]::UtcNow
    $elapsed=($now-$started).TotalSeconds
    $treeBytes=[int64]0
    foreach($item in $running){$treeBytes+=Get-ProcessTreeWorkingSetBytes -RootProcessId $item.process.Id}
    $availableBytes=[int64][MultipoleMemoryStatus]::AvailableBytes()
    $directoryBytes=Get-RunDirectoryBytes -RunDir $RunDir
    $usage.wall_clock_seconds=[math]::Round($elapsed,3)
    $usage.peak_process_tree_working_set_bytes=[math]::Max([int64]$usage.peak_process_tree_working_set_bytes,$treeBytes)
    $usage.peak_run_directory_bytes=[math]::Max([int64]$usage.peak_run_directory_bytes,$directoryBytes)
    $usage.minimum_system_available_memory_bytes=$(if($null-eq$usage.minimum_system_available_memory_bytes){$availableBytes}else{[math]::Min([int64]$usage.minimum_system_available_memory_bytes,$availableBytes)})
    Write-ResourceUsage -Usage $usage -Path $UsagePath
    Start-Sleep -Milliseconds 500
    foreach($item in $running){$item.process.Refresh()}
  }
  foreach($item in $running){if(-not$item.process.HasExited){$item.process.WaitForExit()}}
  $usage.status=$(if(@($running|Where-Object{$_.process.ExitCode-ne 0}).Count-eq 0){'running'}else{'process_failed'})
  Write-ResourceUsage -Usage $usage -Path $UsagePath
  return [pscustomobject]@{resource_budget_exceeded=$false;limit_name=$null;
    processes=@($running|ForEach-Object{[pscustomobject]@{name=$_.name;exit_code=$_.process.ExitCode}})
  }
}

function Complete-ResourceUsage {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$ResolvedBudgetPath,
    [Parameter(Mandatory)][string]$RunDir,
    [Parameter(Mandatory)][string]$UsagePath
  )
  $budget=Get-Content -LiteralPath $ResolvedBudgetPath -Raw -Encoding UTF8|ConvertFrom-Json
  $usage=Get-Content -LiteralPath $UsagePath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $finalBytes=Get-RunDirectoryBytes -RunDir $RunDir
  $usage.final_retained_bytes=$finalBytes
  $usage.peak_run_directory_bytes=[math]::Max([int64]$usage.peak_run_directory_bytes,$finalBytes)
  if($usage.status-eq'running'){$usage.status='completed'}
  Write-ResourceUsage -Usage $usage -Path $UsagePath
  return $true
}
