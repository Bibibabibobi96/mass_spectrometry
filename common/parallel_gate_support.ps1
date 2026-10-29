Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-GateRunSummary {
    param([Parameter(Mandatory)]$Summary)
    $temporary = $Summary.Path + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
    try {
        [IO.File]::WriteAllText($temporary,
            ($Summary.Document | ConvertTo-Json -Depth 16),
            [Text.UTF8Encoding]::new($false))
        [IO.File]::Move($temporary, $Summary.Path, $true)
    } finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary }
    }
}

function New-GateRunSummary {
    param(
        [Parameter(Mandatory)][object[]]$Items,
        [Parameter(Mandatory)][string]$GateName,
        [Parameter(Mandatory)][string]$PythonExe,
        [Parameter(Mandatory)][string]$RepoRoot,
        [string]$SummaryPath = ''
    )
    if (-not $SummaryPath) {
        $SummaryPath = Join-Path ([IO.Path]::GetTempPath()) (
            'gate_summary_' + [guid]::NewGuid().ToString('N') + '.json')
    }
    $SummaryPath = [IO.Path]::GetFullPath($SummaryPath)
    if (Test-Path -LiteralPath $SummaryPath) {
        throw "Gate summary already exists: $SummaryPath"
    }
    [IO.Directory]::CreateDirectory((Split-Path -Parent $SummaryPath)) | Out-Null
    $stages = @($Items | ForEach-Object {
        $item = $_
        $record = [ordered]@{
            name = [string]$item.Name
            selected = [bool]$item.Run
            selection_reason = [string]$item.Reason
            dependency_profile = $null
            command = $null
            requires_stages = @()
            status = $(if ($item.Run) { 'PENDING' } else { 'NOT_APPLICABLE' })
            reason_code = $(if ($item.Run) { 'NOT_STARTED' } else { 'NOT_SELECTED' })
            started_at = $null; finished_at = $null; elapsed_seconds = $null
            queue_seconds = $null; resource_wait_seconds = $null
            execution_seconds = $null; cleanup_seconds = $null
            launch_seconds = $null; process_elapsed_seconds = $null
            exit_code = $null; child_exit_code = $null; log_path = $null; log_retained = $false
            error = $null
        }
        foreach ($field in @('DependencyProfile', 'Command', 'RequiresStages')) {
            if ($null -ne $item.PSObject.Properties[$field] -or
                ($item -is [Collections.IDictionary] -and $item.Contains($field))) {
                $key = @{ DependencyProfile='dependency_profile'; Command='command'; RequiresStages='requires_stages' }[$field]
                if ($field -eq 'RequiresStages') {
                    $record[$key] = @($item.$field | Where-Object { $null -ne $_ })
                } else { $record[$key] = $item.$field }
            }
        }
        [pscustomobject]$record
    })
    $summary = [pscustomobject]@{
        Path = $SummaryPath
        Timer = [Diagnostics.Stopwatch]::StartNew()
        Document = [ordered]@{
            schema_version = 1; gate = $GateName; repository = $RepoRoot
            python_exe = $PythonExe; powershell_version = [string]$PSVersionTable.PSVersion
            started_at = [DateTime]::UtcNow.ToString('o'); finished_at = $null
            elapsed_seconds = $null; status = 'RUNNING'; error = $null
            stages = $stages
        }
    }
    Write-GateRunSummary -Summary $summary
    Write-Host "GATE_SUMMARY_PATH=$SummaryPath"
    return $summary
}

function Set-GateStageResult {
    param($Summary, [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][Collections.IDictionary]$Result)
    if ($null -eq $Summary) { return }
    $record = @($Summary.Document.stages | Where-Object { $_.name -eq $Name })
    if ($record.Count -ne 1) { throw "Unknown or duplicate summary stage: $Name" }
    foreach ($key in $Result.Keys) { $record[0].$key = $Result[$key] }
    Write-GateRunSummary -Summary $Summary
}

function Complete-GateRunSummary {
    param($Summary, $Failure)
    if ($null -eq $Summary) { return }
    $interrupted = ($null -ne $Failure -and
        $Failure.Exception -is [Management.Automation.PipelineStoppedException]) -or
        @($Summary.Document.stages | Where-Object { $_.status -eq 'INTERRUPTED' }).Count -gt 0
    foreach ($stage in $Summary.Document.stages) {
        if ($stage.status -notin @('PENDING', 'RUNNING')) { continue }
        $failedDependencies = @($Summary.Document.stages | Where-Object {
            $_.name -in @($stage.requires_stages) -and $_.status -ne 'PASS'
        })
        $stage.status = if ($interrupted) { 'INTERRUPTED' } else { 'BLOCKED' }
        $stage.reason_code = if ($interrupted) { 'GATE_INTERRUPTED' }
            elseif ($failedDependencies.Count -gt 0) { 'PREREQUISITE_NOT_PASSED' }
            else { 'GATE_ENDED_BEFORE_STAGE_COMPLETED' }
    }
    $Summary.Timer.Stop()
    $Summary.Document.finished_at = [DateTime]::UtcNow.ToString('o')
    $Summary.Document.elapsed_seconds = [Math]::Round($Summary.Timer.Elapsed.TotalSeconds, 6)
    $incomplete = @($Summary.Document.stages | Where-Object {
        $_.selected -and $_.status -ne 'PASS'
    }).Count -gt 0
    $Summary.Document.status = if ($interrupted) { 'INTERRUPTED' }
        elseif ($null -ne $Failure -or $incomplete) { 'FAIL' } else { 'PASS' }
    if ($null -ne $Failure) { $Summary.Document.error = $Failure.Exception.Message }
    try { Write-GateRunSummary -Summary $Summary } catch {
        if ($null -ne $Failure -or $interrupted -or $incomplete) {
            Write-Warning "Gate summary could not be completed; original gate failure is retained: $_"
        } else { throw }
    }
}

function Invoke-RecordedGateStage {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Reason,
        [Parameter(Mandatory)][Alias('Action')][scriptblock]$Operation,
        $Summary
    )
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $result = [ordered]@{
        status = 'RUNNING'; reason_code = 'EXECUTING'
        started_at = [DateTime]::UtcNow.ToString('o'); finished_at = $null
        elapsed_seconds = $null; exit_code = $null; error = $null
    }
    $stageFailure = $null
    $timings = @{}
    Set-GateStageResult -Summary $Summary -Name $Name -Result $result
    Write-Output "GATE_STAGE=RUN NAME=$Name REASON=$Reason"
    try {
        Invoke-ResourceBudgetedGateAction -Name $Name -Action $Operation -Timings $timings
        $result.status = 'PASS'; $result.reason_code = 'COMPLETED'; $result.exit_code = 0
    } catch {
        $stageFailure = $_
        $result.status = if ($_.Exception -is [Management.Automation.PipelineStoppedException]) {
            'INTERRUPTED'
        } else { 'FAIL' }
        $result.reason_code = 'STAGE_EXCEPTION'
        $nativeCode = Get-Variable -Name LASTEXITCODE -ValueOnly -ErrorAction SilentlyContinue
        $result.exit_code = if ($nativeCode) { $nativeCode } else { 1 }
        $result.error = $_.Exception.Message
        throw
    } finally {
        if ($result.status -eq 'RUNNING') {
            # PowerShell pipeline cancellation can bypass catch but still unwind finally.
            $result.status = 'INTERRUPTED'; $result.reason_code = 'STAGE_INTERRUPTED'
        }
        $timer.Stop()
        $result.finished_at = [DateTime]::UtcNow.ToString('o')
        $result.elapsed_seconds = [Math]::Round($timer.Elapsed.TotalSeconds, 6)
        foreach ($key in $timings.Keys) { $result[$key] = $timings[$key] }
        $recordingFailure = $null
        try { Set-GateStageResult -Summary $Summary -Name $Name -Result $result }
        catch { $recordingFailure = $_ }
        # The logged child wrapper owns this sidecar; the parent owns the run summary.
        if (Get-Variable -Name GateStageResultPath -Scope Script -ErrorAction SilentlyContinue) {
            if ($script:GateStageResultPath) {
                try {
                    Write-GateRunSummary -Summary ([pscustomobject]@{
                        Path = $script:GateStageResultPath; Document = $result
                    })
                } catch { if ($null -eq $recordingFailure) { $recordingFailure = $_ } }
            }
        }
        if ($null -ne $recordingFailure) {
            if ($null -ne $stageFailure -or $result.status -eq 'INTERRUPTED') {
                Write-Warning "Stage summary could not be written; original stage failure is retained: $recordingFailure"
            } else { throw $recordingFailure }
        }
    }
    Write-Output "GATE_STAGE=PASS NAME=$Name ELAPSED_SECONDS=$($result.elapsed_seconds)"
}

function Invoke-ResourceBudgetedGateAction {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][Alias('Action')][scriptblock]$Operation,
        [hashtable]$Timings
    )
    $budget = Get-HostResourceBudget -Stage $Name -Role GATE
    $waitTimer = [Diagnostics.Stopwatch]::StartNew()
    try { $lease = Enter-HostResourceStage -Role GATE -Stage $Name -Budget $budget }
    finally {
        if ($null -ne $Timings) { $Timings.resource_wait_seconds = $waitTimer.Elapsed.TotalSeconds }
    }
    $limitRuffThreads = $Name -in @('ruff_all', 'ruff_changed_python')
    $originalRayonThreads = [Environment]::GetEnvironmentVariable('RAYON_NUM_THREADS', 'Process')
    $originalOutputEncoding = [Console]::OutputEncoding
    $operationFailure = $null
    try {
        # Child PowerShell processes inherit this code page through Python.
        [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
        # Ruff's registered one-core budget must also bound its native workers.
        if ($limitRuffThreads) { $env:RAYON_NUM_THREADS = '1' }
        $executionTimer = [Diagnostics.Stopwatch]::StartNew()
        try { & $Operation } finally {
            if ($null -ne $Timings) { $Timings.execution_seconds = $executionTimer.Elapsed.TotalSeconds }
        }
    } catch {
        $operationFailure = $_
        throw
    } finally {
        $cleanupTimer = [Diagnostics.Stopwatch]::StartNew()
        try {
            Exit-HostResourceStage -Lease $lease
        } catch {
            if ($null -eq $operationFailure) { throw }
            $operationFailure.Exception.Data['gate_release_error'] = $_.Exception.Message
        } finally {
            [Console]::OutputEncoding = $originalOutputEncoding
            if ($limitRuffThreads) {
                [Environment]::SetEnvironmentVariable('RAYON_NUM_THREADS', $originalRayonThreads, 'Process')
            }
            if ($null -ne $Timings) { $Timings.cleanup_seconds = $cleanupTimer.Elapsed.TotalSeconds }
        }
    }
}

function Resolve-GateConcurrency {
    param([Parameter(Mandatory)][ValidateRange(0, 32)][int]$Requested)
    if ($Requested -gt 0) { return $Requested }
    return [Math]::Max(1, [Math]::Min(8, [Environment]::ProcessorCount))
}

function ConvertTo-GateProcessArgument {
    param([Parameter(Mandatory)][string]$Value)
    return '"' + $Value.Replace('"', '\"') + '"'
}

function Remove-GateTemporaryDirectory {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$ExpectedNamePrefix
    )
    $resolved = [IO.Path]::GetFullPath($Path)
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    ) + [IO.Path]::DirectorySeparatorChar
    $leaf = Split-Path -Leaf $resolved
    if (-not $resolved.StartsWith(
            $tempRoot,
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        -not $leaf.StartsWith(
            $ExpectedNamePrefix,
            [StringComparison]::Ordinal
        )) {
        throw "Refusing to remove unverified gate temporary directory: $resolved"
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force `
        -ErrorAction SilentlyContinue
}

function Invoke-LoggedGateStage {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$LogPath,
        [Parameter(Mandatory)][scriptblock]$Action
    )
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:RUFF_NO_CACHE = 'true'
    if (-not $env:MPLCONFIGDIR) {
        $env:MPLCONFIGDIR = Join-Path (Split-Path -Parent $LogPath) ("mpl_$Name")
        New-Item -ItemType Directory -Path $env:MPLCONFIGDIR -Force | Out-Null
    }
    $writer = [IO.StreamWriter]::new(
        $LogPath, $false, [Text.UTF8Encoding]::new($false)
    )
    $writer.AutoFlush = $true
    $succeeded = $true
    $previousResultPath = if (Get-Variable -Name GateStageResultPath -Scope Script -ErrorAction SilentlyContinue) {
        $script:GateStageResultPath
    } else { $null }
    $script:GateStageResultPath = $LogPath + '.result.json'
    try {
        & $Action *>&1 | ForEach-Object {
            $writer.WriteLine(($_ | Out-String -Width 4096).TrimEnd())
        }
    } catch {
        $succeeded = $false
        $writer.WriteLine(($_ | Out-String -Width 4096).TrimEnd())
    } finally {
        $writer.Dispose()
        $script:GateStageResultPath = $previousResultPath
    }
    return $succeeded
}

function Invoke-IndependentGateStageGroup {
    param(
        [Parameter(Mandatory)][object[]]$Items,
        [Parameter(Mandatory)][ValidateRange(1, 32)][int]$MaxConcurrency,
        [Parameter(Mandatory)][string]$GateScriptPath,
        [Parameter(Mandatory)][string]$PythonExe,
        [Parameter(Mandatory)][AllowEmptyCollection()][string[]]$ChildBaseArguments,
        [Parameter(Mandatory)][string]$TempNamePrefix,
        [Parameter(Mandatory)][string]$FailureMessage,
        [Parameter(Mandatory)][scriptblock]$InvokeInlineStage,
        [Parameter(Mandatory)][scriptblock]$InvokeSkipStage,
        [hashtable]$RequestPayload,
        [string]$InternalRequestParameter = '',
        [switch]$StopOnFailure,
        $Summary
    )
    # A nested gate consumes its caller's whole-stage reservation. It cannot
    # multiply that reservation by starting simultaneous inheriting children.
    if ($env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN -and $MaxConcurrency -gt 1) {
        $MaxConcurrency = 1
        Write-Output 'GATE_CONCURRENCY=1 REASON=inherited_resource_reservation'
    }
    $selected = @($Items | Where-Object { $_.Run })
    $queueTimer = [Diagnostics.Stopwatch]::StartNew()
    $states = @{}
    if ($null -ne $Summary) {
        foreach ($stage in $Summary.Document.stages) { $states[$stage.name] = $stage.status }
    }
    foreach ($item in $Items) { $states[$item.Name] = if ($item.Run) { 'PENDING' } else { 'NOT_APPLICABLE' } }
    $prerequisiteState = {
        param($item)
        $waiting = $false
        $dependencies = if ($null -ne $item.PSObject.Properties['RequiresStages'] -or
            ($item -is [Collections.IDictionary] -and $item.Contains('RequiresStages'))) { @($item.RequiresStages) } else { @() }
        foreach ($name in $dependencies) {
            if (-not $states.ContainsKey($name)) { return 'PREREQUISITE_MISSING' }
            if ($states[$name] -eq 'NOT_APPLICABLE') { return 'PREREQUISITE_NOT_SELECTED' }
            if ($states[$name] -in @('FAIL', 'INTERRUPTED', 'BLOCKED')) { return 'PREREQUISITE_NOT_PASSED' }
            if ($states[$name] -ne 'PASS') { $waiting = $true }
        }
        if ($waiting) { return 'WAIT' }
        return 'READY'
    }
    $blockStage = {
        param($item, $reason)
        $states[$item.Name] = 'BLOCKED'
        Set-GateStageResult -Summary $Summary -Name $item.Name -Result @{
            status = 'BLOCKED'; reason_code = $reason; finished_at = [DateTime]::UtcNow.ToString('o')
        }
        Write-Output "GATE_STAGE=BLOCKED NAME=$($item.Name) REASON=$reason"
    }
    if ($selected.Count -le 1) {
        foreach ($item in $Items) {
            if ($item.Run) {
                $dependency = & $prerequisiteState $item
                if ($dependency -ne 'READY') {
                    if ($dependency -eq 'WAIT') { $dependency = 'UNRESOLVED_PREREQUISITE' }
                    & $blockStage $item $dependency
                    throw "$FailureMessage`: $($item.Name)=blocked"
                }
                Set-GateStageResult -Summary $Summary -Name $item.Name -Result @{queue_seconds=$queueTimer.Elapsed.TotalSeconds}
                & $InvokeInlineStage $item
            }
            else { & $InvokeSkipStage $item }
        }
        return
    }

    $groupRoot = Join-Path ([IO.Path]::GetTempPath()) (
        $TempNamePrefix + [guid]::NewGuid().ToString('N')
    )
    New-Item -ItemType Directory -Path $groupRoot | Out-Null
    Write-Output "GATE_DIAGNOSTICS=TEMPORARY PATH=$groupRoot"
    $groupSucceeded = $false
    $groupFailure = $null
        $originalMatplotlibConfig = [Environment]::GetEnvironmentVariable(
            'MPLCONFIGDIR', 'Process'
        )
        $records = @{}
        $pending = [Collections.Generic.List[object]]::new()
        $itemsByName = @{}
        foreach ($item in $Items) {
            $itemsByName[$item.Name] = $item
            if ($item.Run) { $pending.Add($item) }
        }
        $failed = [ordered]@{}
        $stageErrors = [ordered]@{}
        $reportedCompletions = [Collections.Generic.HashSet[string]]::new(
            [StringComparer]::Ordinal
        )
        # This reporter stays on this call's stack. A dynamic-module closure
        # would hide helpers dot-sourced in the calling gate's script scope.
        $reportCompletions = {
            foreach ($recordName in @($records.Keys)) {
                $record = $records[$recordName]
                if ($record.Process.HasExited -and
                    $reportedCompletions.Add([string]$recordName)) {
                    $record.Process.WaitForExit()
                    $record.Timer.Stop()
                    $elapsed = $record.Timer.Elapsed
                    $result = @{
                        status = $(if ($record.Process.ExitCode -eq 0) { 'PASS' } else { 'FAIL' })
                        reason_code = $(if ($record.Process.ExitCode -eq 0) { 'COMPLETED' } else { 'CHILD_EXIT_NONZERO' })
                        finished_at = [DateTime]::UtcNow.ToString('o')
                        elapsed_seconds = [Math]::Round($elapsed.TotalSeconds, 6)
                        process_elapsed_seconds = [Math]::Round($elapsed.TotalSeconds, 6)
                        exit_code = $record.Process.ExitCode
                        child_exit_code = $record.Process.ExitCode
                        log_path = $record.LogPath
                        log_retained = (Test-Path -LiteralPath $record.LogPath)
                    }
                    $resultPath = $record.LogPath + '.result.json'
                    if (Test-Path -LiteralPath $resultPath -PathType Leaf) {
                        $record.HasResultReceipt = $true
                        $childResult = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json -AsHashtable
                        foreach ($key in $childResult.Keys) {
                            if ($key -notin @('process_elapsed_seconds', 'launch_seconds', 'child_exit_code')) {
                                $result[$key] = $childResult[$key]
                            }
                        }
                        if ($record.Process.ExitCode -ne 0 -and $result.status -eq 'PASS') {
                            $result.status = 'FAIL'; $result.reason_code = 'CHILD_EXIT_NONZERO'
                            $result.exit_code = $record.Process.ExitCode
                        }
                    }
                    if (-not (Test-Path -LiteralPath $record.LogPath -PathType Leaf) -and
                        -not $record.HasResultReceipt) {
                        # Resolve the existing fallback before any dependent becomes ready.
                        Write-Output "GATE_STAGE=FALLBACK NAME=$recordName REASON=missing_stage_log_serial_fallback"
                        $fallbackItem = $itemsByName[$recordName]
                        $inlineSucceeded = Invoke-LoggedGateStage -Name $recordName -LogPath $record.LogPath -Action {
                            & $InvokeInlineStage $fallbackItem
                        }
                        $result.elapsed_seconds = $null
                        if (Test-Path -LiteralPath $resultPath -PathType Leaf) {
                            $fallbackResult = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json -AsHashtable
                            foreach ($key in $fallbackResult.Keys) {
                                if ($key -notin @('process_elapsed_seconds', 'launch_seconds', 'child_exit_code')) {
                                    $result[$key] = $fallbackResult[$key]
                                }
                            }
                        }
                        $result.status = if ($inlineSucceeded) { 'PASS' } else { 'FAIL' }
                        $result.reason_code = if ($inlineSucceeded) { 'SERIAL_FALLBACK_COMPLETED' } else { 'SERIAL_FALLBACK_FAILED' }
                        $result.exit_code = if ($inlineSucceeded) { 0 } else { 1 }
                        $result.log_retained = Test-Path -LiteralPath $record.LogPath
                    }
                    $record.Result = $result
                    $states[$recordName] = $result.status
                    if ($result.status -ne 'PASS') {
                        $failed[$recordName] = if ($result.reason_code -eq 'SERIAL_FALLBACK_FAILED') {
                            "$recordName=serial_fallback_failed_after_$($record.Process.ExitCode)"
                        } else { "$recordName=$($result.exit_code)" }
                    }
                    Set-GateStageResult -Summary $Summary -Name $recordName -Result $result
                    Write-Output (
                        "GATE_PROCESS=COMPLETE NAME=$recordName " +
                        "EXIT_CODE=$($record.Process.ExitCode) " +
                        "ELAPSED_SECONDS=$([Math]::Round($elapsed.TotalSeconds, 3)) " +
                        'LOG_REPLAY=PENDING'
                    )
                }
            }
        }
        try {
        $env:MPLCONFIGDIR = Join-Path $groupRoot 'matplotlib'
        New-Item -ItemType Directory -Path $env:MPLCONFIGDIR | Out-Null
        Invoke-ResourceBudgetedGateAction -Name 'gate_matplotlib_cache' -Action {
            & $PythonExe -c (
                "import importlib.util; spec=importlib.util.find_spec('matplotlib'); " +
                "spec and __import__('matplotlib.font_manager')"
            )
            if ($LASTEXITCODE -ne 0) {
                throw 'Gate Matplotlib cache initialization failed.'
            }
        }
        Write-Output "GATE_MATPLOTLIB_CACHE=READY PATH=$env:MPLCONFIGDIR"
        $childArguments = [Collections.Generic.List[string]]::new()
        foreach ($argument in $ChildBaseArguments) {
            $childArguments.Add([string]$argument)
        }
        if ($null -ne $RequestPayload) {
            if (-not $InternalRequestParameter) {
                throw 'InternalRequestParameter is required with RequestPayload.'
            }
            $requestPath = Join-Path $groupRoot 'request.json'
            $RequestPayload | ConvertTo-Json -Depth 8 |
                Set-Content -LiteralPath $requestPath -Encoding UTF8
            $childArguments.Add($InternalRequestParameter)
            $childArguments.Add($requestPath)
        }

        while ($pending.Count -gt 0 -or @($records.Values | Where-Object { -not $_.Process.HasExited }).Count -gt 0) {
            & $reportCompletions
            foreach ($candidate in @($pending)) {
                $dependency = & $prerequisiteState $candidate
                if ($dependency -notin @('READY', 'WAIT')) {
                    & $blockStage $candidate $dependency
                    $failed[$candidate.Name] = "$($candidate.Name)=blocked"
                    $null = $pending.Remove($candidate)
                }
            }
            if ($StopOnFailure -and $failed.Count -gt 0) {
                foreach ($candidate in @($pending)) {
                    $dependency = & $prerequisiteState $candidate
                    $reason = if ($dependency -in @('READY', 'WAIT')) { 'FAIL_FAST' } else { $dependency }
                    & $blockStage $candidate $reason
                    $null = $pending.Remove($candidate)
                }
            }
            $running = @($records.Values | Where-Object { $null -eq $_.Result }).Count
            $ready = @($pending | Where-Object { (& $prerequisiteState $_) -eq 'READY' })
            if ($running -ge $MaxConcurrency -or ($ready.Count -eq 0 -and $running -gt 0)) {
                Start-Sleep -Milliseconds 50
                continue
            }
            if ($ready.Count -eq 0) {
                foreach ($candidate in @($pending)) {
                    & $blockStage $candidate 'UNRESOLVED_PREREQUISITE'
                    $failed[$candidate.Name] = "$($candidate.Name)=blocked"
                }
                $pending.Clear()
                break
            }
            $item = $ready[0]
            $null = $pending.Remove($item)
            $index = [array]::IndexOf($Items, $item)
            $logPath = Join-Path $groupRoot (
                '{0:D2}_{1}.log' -f $index, $item.Name
            )
            $arguments = [Collections.Generic.List[string]]::new()
            $arguments.Add('-NoProfile')
            $arguments.Add('-File')
            $arguments.Add($GateScriptPath)
            foreach ($argument in $childArguments) {
                $arguments.Add($argument)
            }
            $arguments.Add('-InternalStage')
            $arguments.Add([string]$item.Name)
            $arguments.Add('-InternalLogPath')
            $arguments.Add($logPath)
            $argumentText = @(
                $arguments | ForEach-Object {
                    ConvertTo-GateProcessArgument ([string]$_)
                }
            ) -join ' '
            Set-GateStageResult -Summary $Summary -Name $item.Name -Result @{
                status = 'RUNNING'; reason_code = 'CHILD_STARTING'
                started_at = [DateTime]::UtcNow.ToString('o'); log_path = $logPath
                queue_seconds = $queueTimer.Elapsed.TotalSeconds
            }
            $states[$item.Name] = 'RUNNING'
            $launchTimer = [Diagnostics.Stopwatch]::StartNew()
            try {
                $process = Start-Process -FilePath (Get-Command pwsh).Source `
                    -ArgumentList $argumentText -WindowStyle Hidden -PassThru
            } catch {
                $launchFailure = $_
                $launchTimer.Stop()
                $states[$item.Name] = 'FAIL'
                $failed[$item.Name] = "$($item.Name)=start_failed"
                $stageErrors[$item.Name] = $launchFailure
                try {
                    Set-GateStageResult -Summary $Summary -Name $item.Name -Result @{
                        status = 'FAIL'; reason_code = 'CHILD_START_FAILED'; error = $launchFailure.Exception.Message
                        finished_at = [DateTime]::UtcNow.ToString('o')
                        elapsed_seconds = $launchTimer.Elapsed.TotalSeconds
                        launch_seconds = $launchTimer.Elapsed.TotalSeconds
                    }
                } catch {
                    Write-Warning "Gate launch failure could not be recorded; original launch failure is retained: $_"
                }
                continue
            }
            $launchSeconds = $launchTimer.Elapsed.TotalSeconds
            $records[$item.Name] = [pscustomobject]@{
                LogPath = $logPath
                Process = $process
                Timer = $launchTimer
                Result = $null
                HasResultReceipt = $false
            }
            Set-GateStageResult -Summary $Summary -Name $item.Name -Result @{launch_seconds=$launchSeconds}
            Write-Output "GATE_PROCESS=START NAME=$($item.Name) PID=$($process.Id) LOG_PATH=$logPath"
        }
        while (@($records.Values | Where-Object {
            -not $_.Process.HasExited
        }).Count -gt 0) {
            & $reportCompletions
            Start-Sleep -Milliseconds 50
        }
        & $reportCompletions

        $failedRecords = [Collections.Generic.List[object]]::new()
        foreach ($item in $Items) {
            if (-not $item.Run) {
                & $InvokeSkipStage $item
                continue
            }
            if (-not $records.ContainsKey($item.Name)) { continue }
            $record = $records[$item.Name]
            $hasLog = Test-Path -LiteralPath $record.LogPath -PathType Leaf
            if ($hasLog -or $record.HasResultReceipt) {
                if ($hasLog) { Get-Content -LiteralPath $record.LogPath -Encoding UTF8 }
                if ($record.Result.status -ne 'PASS') {
                    if ($hasLog) {
                        $failedRecords.Add([pscustomobject]@{
                            Name = [string]$item.Name
                            ExitCode = $record.Result.exit_code
                            LogPath = $record.LogPath
                        })
                    }
                }
            }
        }
        if ($failed.Count -gt 0) {
            foreach ($failedRecord in $failedRecords) {
                Write-Output (
                    "GATE_STAGE=FAIL NAME=$($failedRecord.Name) " +
                    "EXIT_CODE=$($failedRecord.ExitCode) DIAGNOSTIC_TAIL_BEGIN"
                )
                Get-Content -LiteralPath $failedRecord.LogPath -Encoding UTF8 -Tail 80
                Write-Output (
                    "GATE_STAGE=FAIL NAME=$($failedRecord.Name) " +
                    'DIAGNOSTIC_TAIL_END'
                )
            }
            if ($stageErrors.Count -gt 0) { throw @($stageErrors.Values)[0] }
            throw "$FailureMessage`: $($failed.Values -join ', ')"
        }
        $groupSucceeded = $true
    } catch {
        # Keep the original stage paths valid, including startup/fallback errors
        # that have no child log of their own.
        $groupFailure = if ($stageErrors.Count -gt 0 -and
            $_.Exception -isnot [Management.Automation.PipelineStoppedException]) { @($stageErrors.Values)[0] } else { $_ }
        try {
            [IO.File]::WriteAllText(
                (Join-Path $groupRoot 'group_failure.log'),
                ($groupFailure | Out-String -Width 4096),
                [Text.UTF8Encoding]::new($false)
            )
        } catch {
            Write-Warning "Could not record gate group failure: $_"
        }
        throw $groupFailure
    } finally {
        # Do not release the work/log directory while a child is alive. An
        # unwind stops future launches but preserves an already-running stage's
        # natural terminal evidence.
        foreach ($record in @($records.Values)) {
            if (-not $record.Process.HasExited) {
                Write-Output "GATE_PROCESS=WAIT PID=$($record.Process.Id) REASON=group_unwinding"
                $record.Process.WaitForExit()
                if (Test-Path -LiteralPath $record.LogPath -PathType Leaf) {
                    Get-Content -LiteralPath $record.LogPath -Encoding UTF8
                }
            }
        }
        $finalizationFailure = $null
        try { & $reportCompletions } catch {
            if ($null -ne $groupFailure) {
                Write-Warning "Gate completion could not be recorded; original group failure is retained: $_"
            } else {
                $finalizationFailure = $_
                $groupSucceeded = $false
            }
        } finally {
            foreach ($record in @($records.Values)) { $record.Process.Dispose() }
            if ($null -eq $originalMatplotlibConfig) {
                Remove-Item Env:MPLCONFIGDIR -ErrorAction SilentlyContinue
            } else {
                $env:MPLCONFIGDIR = $originalMatplotlibConfig
            }
        }
        if ($groupSucceeded) {
            Remove-GateTemporaryDirectory -Path $groupRoot `
                -ExpectedNamePrefix $TempNamePrefix
        }
        if (-not (Test-Path -LiteralPath $groupRoot)) {
            Write-Output "GATE_DIAGNOSTICS=CLEANED PATH=$groupRoot"
        } else {
            # Retain only this group's diagnostic files, not its generated cache.
            Remove-GateTemporaryDirectory -Path (Join-Path $groupRoot 'matplotlib') `
                -ExpectedNamePrefix 'matplotlib'
            Write-Output "GATE_DIAGNOSTICS=RETAINED PATH=$groupRoot"
            Write-Output (
                'GATE_DIAGNOSTICS_CLEANUP=AFTER_REVIEW ' +
                "COMMAND=Remove-GateTemporaryDirectory -Path '$($groupRoot.Replace("'", "''"))' " +
                "-ExpectedNamePrefix '$($TempNamePrefix.Replace("'", "''"))'"
            )
        }
        foreach ($recordName in @($records.Keys)) {
            try {
                Set-GateStageResult -Summary $Summary -Name $recordName -Result @{
                    log_retained = (Test-Path -LiteralPath $records[$recordName].LogPath)
                }
            } catch {
                if (-not $groupSucceeded) {
                    Write-Warning "Gate log retention could not be recorded; original group failure is retained: $_"
                } else { throw }
            }
        }
        if ($null -ne $finalizationFailure) { throw $finalizationFailure }
    }
}
