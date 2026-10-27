Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-ResourceBudgetedGateAction {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][Alias('Action')][scriptblock]$Operation
    )
    $budget = Get-HostResourceBudget -Stage $Name -Role GATE
    $lease = Enter-HostResourceStage -Role GATE -Stage $Name -Budget $budget
    $limitRuffThreads = $Name -in @('ruff_all', 'ruff_changed_python')
    $originalRayonThreads = [Environment]::GetEnvironmentVariable('RAYON_NUM_THREADS', 'Process')
    $originalOutputEncoding = [Console]::OutputEncoding
    try {
        # Child PowerShell processes inherit this code page through Python.
        [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
        # Ruff's registered one-core budget must also bound its native workers.
        if ($limitRuffThreads) { $env:RAYON_NUM_THREADS = '1' }
        & $Operation
    } finally {
        try {
            Exit-HostResourceStage -Lease $lease
        } finally {
            [Console]::OutputEncoding = $originalOutputEncoding
            if ($limitRuffThreads) {
                [Environment]::SetEnvironmentVariable('RAYON_NUM_THREADS', $originalRayonThreads, 'Process')
            }
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
    try {
        & $Action *>&1 | ForEach-Object {
            $writer.WriteLine(($_ | Out-String -Width 4096).TrimEnd())
        }
    } catch {
        $succeeded = $false
        $writer.WriteLine(($_ | Out-String -Width 4096).TrimEnd())
    } finally {
        $writer.Dispose()
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
        [string]$InternalRequestParameter = ''
    )
    # A nested gate consumes its caller's whole-stage reservation. It cannot
    # multiply that reservation by starting simultaneous inheriting children.
    if ($env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN -and $MaxConcurrency -gt 1) {
        $MaxConcurrency = 1
        Write-Output 'GATE_CONCURRENCY=1 REASON=inherited_resource_reservation'
    }
    $selected = @($Items | Where-Object { $_.Run })
    if ($selected.Count -le 1) {
        foreach ($item in $Items) {
            if ($item.Run) { & $InvokeInlineStage $item }
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
        $originalMatplotlibConfig = [Environment]::GetEnvironmentVariable(
            'MPLCONFIGDIR', 'Process'
        )
        $records = @{}
        $reportedCompletions = [Collections.Generic.HashSet[string]]::new(
            [StringComparer]::Ordinal
        )
        $reportCompletions = {
            foreach ($recordName in @($records.Keys)) {
                $record = $records[$recordName]
                if ($record.Process.HasExited -and
                    $reportedCompletions.Add([string]$recordName)) {
                    $record.Process.WaitForExit()
                    $elapsed = [DateTime]::UtcNow - $record.StartedAt
                    Write-Output (
                        "GATE_PROCESS=COMPLETE NAME=$recordName " +
                        "EXIT_CODE=$($record.Process.ExitCode) " +
                        "ELAPSED_SECONDS=$([Math]::Round($elapsed.TotalSeconds, 3)) " +
                        'LOG_REPLAY=PENDING'
                    )
                }
            }
        }.GetNewClosure()
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

        for ($index = 0; $index -lt $Items.Count; $index++) {
            $item = $Items[$index]
            if (-not $item.Run) { continue }
            while (@($records.Values | Where-Object {
                -not $_.Process.HasExited
            }).Count -ge $MaxConcurrency) {
                & $reportCompletions
                Start-Sleep -Milliseconds 50
            }
            & $reportCompletions
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
            $process = Start-Process -FilePath (Get-Command pwsh).Source `
                -ArgumentList $argumentText -WindowStyle Hidden -PassThru
            $records[$item.Name] = [pscustomobject]@{
                LogPath = $logPath
                Process = $process
                StartedAt = [DateTime]::UtcNow
            }
            Write-Output "GATE_PROCESS=START NAME=$($item.Name) PID=$($process.Id) LOG_PATH=$logPath"
        }
        while (@($records.Values | Where-Object {
            -not $_.Process.HasExited
        }).Count -gt 0) {
            & $reportCompletions
            Start-Sleep -Milliseconds 50
        }
        & $reportCompletions

        $failed = [Collections.Generic.List[string]]::new()
        $failedRecords = [Collections.Generic.List[object]]::new()
        foreach ($item in $Items) {
            if (-not $item.Run) {
                & $InvokeSkipStage $item
                continue
            }
            $record = $records[$item.Name]
            if (Test-Path -LiteralPath $record.LogPath -PathType Leaf) {
                Get-Content -LiteralPath $record.LogPath -Encoding UTF8
                if ($record.Process.ExitCode -ne 0) {
                    $failed.Add("$($item.Name)=$($record.Process.ExitCode)")
                    $failedRecords.Add([pscustomobject]@{
                        Name = [string]$item.Name
                        ExitCode = $record.Process.ExitCode
                        LogPath = $record.LogPath
                    })
                }
            } else {
                Write-Output (
                    "GATE_STAGE=FALLBACK NAME=$($item.Name) " +
                    'REASON=missing_stage_log_serial_fallback'
                )
                $inlineSucceeded = Invoke-LoggedGateStage -Name $item.Name `
                    -LogPath $record.LogPath -Action {
                    & $InvokeInlineStage $item
                }
                Get-Content -LiteralPath $record.LogPath -Encoding UTF8
                if (-not $inlineSucceeded) {
                    $failed.Add(
                        "$($item.Name)=serial_fallback_failed_after_" +
                        $record.Process.ExitCode
                    )
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
            throw "$FailureMessage`: $($failed -join ', ')"
        }
        $groupSucceeded = $true
    } catch {
        # Keep the original stage paths valid, including startup/fallback errors
        # that have no child log of their own.
        $groupFailure = $_
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
            $record.Process.Dispose()
        }
        if ($null -eq $originalMatplotlibConfig) {
            Remove-Item Env:MPLCONFIGDIR -ErrorAction SilentlyContinue
        } else {
            $env:MPLCONFIGDIR = $originalMatplotlibConfig
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
    }
}
