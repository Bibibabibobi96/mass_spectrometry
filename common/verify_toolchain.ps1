param(
    [switch]$SkipMatlabProbe,
    [switch]$SkipSolidWorksProbe
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$matlabExe = 'C:\Program Files\MATLAB\R2025b\MatlabR2025b\bin\matlab.exe'
$solidWorksExe = 'D:\SW2022\SOLIDWORKS Corp2022\SOLIDWORKS\SLDWORKS.exe'
$swInterop = 'D:\SW2022\SOLIDWORKS Corp2022\SOLIDWORKS\SolidWorks.Interop.sldworks.dll'
$swConstants = 'D:\SW2022\SOLIDWORKS Corp2022\SOLIDWORKS\SolidWorks.Interop.swconst.dll'

if (-not (Test-Path -LiteralPath $matlabExe -PathType Leaf)) {
    throw "MATLAB R2025b executable not found: $matlabExe"
}
if (-not $SkipMatlabProbe) {
    $matlabOutput = & $matlabExe -batch "fprintf('MATLAB_RELEASE=%s\n', version('-release'))"
    if ($LASTEXITCODE -ne 0 -or ($matlabOutput -join "`n") -notmatch 'MATLAB_RELEASE=2025b') {
        throw "MATLAB R2025b probe failed: $($matlabOutput -join ' ')"
    }
}

if (-not (Test-Path -LiteralPath $solidWorksExe -PathType Leaf) -or
    -not (Test-Path -LiteralPath $swInterop -PathType Leaf) -or
    -not (Test-Path -LiteralPath $swConstants -PathType Leaf)) {
    throw 'SolidWorks 2022 PIA assemblies are unavailable.'
}
$revision = 'UNPROBED'
$solidWorksProbeMode = 'SKIPPED'
if (-not $SkipSolidWorksProbe) {
    Add-Type -Path $swInterop
    Add-Type -Path $swConstants
    $sw = $null
    $existingSolidWorksIds = @(Get-Process -Name SLDWORKS -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
    try {
        $sw = New-Object -TypeName 'SolidWorks.Interop.sldworks.SldWorksClass'
        $revisionError = $null
        foreach ($attempt in 1..10) {
            try {
                $revision = [string]$sw.RevisionNumber()
                $revisionError = $null
                break
            }
            catch {
                $revisionError = $_
                Start-Sleep -Milliseconds 500
            }
        }
        if ($null -ne $revisionError) {
            $revision = [string](Get-Item -LiteralPath $solidWorksExe).VersionInfo.ProductVersion
            $solidWorksProbeMode = 'FILE_VERSION_FALLBACK'
            Write-Warning ("SolidWorks live COM revision probe failed; verified the installed " +
                "executable/PIA baseline instead. Actual CAD changes still require the project " +
                "SolidWorks export gate. COM error: $($revisionError.Exception.Message)")
        }
        else {
            $solidWorksProbeMode = 'LIVE_COM'
        }
        if ($revision -notmatch '^30\.') {
            throw "Expected SolidWorks 2022 revision 30.x, got $revision"
        }
    }
    finally {
        if ($null -ne $sw) {
            try {
                $sw.ExitApp()
            }
            catch {
                Write-Warning "SolidWorks probe instance was already unavailable during ExitApp: $($_.Exception.Message)"
            }
            try {
                [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($sw)
            }
            catch {
                Write-Warning "SolidWorks probe COM release was already complete: $($_.Exception.Message)"
            }
            $newSolidWorks = @(Get-Process -Name SLDWORKS -ErrorAction SilentlyContinue | Where-Object {
                $_.Id -notin $existingSolidWorksIds
            })
            foreach ($process in $newSolidWorks) {
                if (-not $process.HasExited) {
                    Write-Warning "Stopping orphan SolidWorks probe process $($process.Id)."
                    Stop-Process -Id $process.Id -Force
                }
            }
        }
    }
}

$readmes = Get-ChildItem -LiteralPath (Join-Path $repoRoot 'projects') -Directory | ForEach-Object {
    Join-Path $_.FullName 'README.md'
}
foreach ($readme in $readmes) {
    $text = Get-Content -LiteralPath $readme -Raw -Encoding UTF8
    if ($text -notmatch 'MATLAB \*\*R2025b\*\*' -or $text -notmatch 'SolidWorks 2022') {
        throw "Project README lacks the formal R2025b/SolidWorks 2022 baseline: $readme"
    }
}

[PSCustomObject]@{
    MATLAB = 'R2025b'
    MATLABProbe = -not $SkipMatlabProbe
    SolidWorks = $revision
    SolidWorksProbe = -not $SkipSolidWorksProbe
    SolidWorksProbeMode = $solidWorksProbeMode
    ProjectReadmes = $readmes.Count
    STATUS = 'PASS'
} | Format-List
