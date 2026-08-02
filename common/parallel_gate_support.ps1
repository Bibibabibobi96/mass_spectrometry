Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

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
    $env:MPLCONFIGDIR = Join-Path (Split-Path -Parent $LogPath) ("mpl_$Name")
    New-Item -ItemType Directory -Path $env:MPLCONFIGDIR -Force | Out-Null
    $lines = [Collections.Generic.List[string]]::new()
    $succeeded = $true
    try {
        & $Action *>&1 | ForEach-Object {
            $lines.Add(($_ | Out-String -Width 4096).TrimEnd())
        }
    } catch {
        $succeeded = $false
        $lines.Add(($_ | Out-String -Width 4096).TrimEnd())
    }
    [IO.File]::WriteAllLines(
        $LogPath, $lines, [Text.UTF8Encoding]::new($false)
    )
    return $succeeded
}

function Invoke-IndependentGateStageGroup {
    param(
        [Parameter(Mandatory)][object[]]$Items,
        [Parameter(Mandatory)][ValidateRange(1, 32)][int]$MaxConcurrency,
        [Parameter(Mandatory)][string]$GateScriptPath,
        [Parameter(Mandatory)][AllowEmptyCollection()][string[]]$ChildBaseArguments,
        [Parameter(Mandatory)][string]$TempNamePrefix,
        [Parameter(Mandatory)][string]$FailureMessage,
        [Parameter(Mandatory)][scriptblock]$InvokeInlineStage,
        [Parameter(Mandatory)][scriptblock]$InvokeSkipStage,
        [hashtable]$RequestPayload,
        [string]$InternalRequestParameter = ''
    )
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
            Write-Output "GATE_PROCESS=START NAME=$($item.Name) PID=$($process.Id)"
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
                try {
                    & $InvokeInlineStage $item
                } catch {
                    Write-Output ($_ | Out-String -Width 4096).TrimEnd()
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
    } finally {
        Remove-GateTemporaryDirectory -Path $groupRoot `
            -ExpectedNamePrefix $TempNamePrefix
    }
}
