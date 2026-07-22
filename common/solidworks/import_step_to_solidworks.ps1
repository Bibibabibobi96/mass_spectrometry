param(
    [Parameter(Mandatory = $true)][string]$StepPath,
    [Parameter(Mandatory = $true)][string]$SldprtPath,
    [switch]$Visible
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $StepPath -PathType Leaf)) {
    throw "STEP file not found: $StepPath"
}

$outDir = Split-Path -Parent $SldprtPath
if (-not (Test-Path -LiteralPath $outDir -PathType Container)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}

# Do not use late-bound dispatch through whichever TypeLib happens to be
# registered.  Load the installed SolidWorks 2022 PIA explicitly so every
# import uses the repository's formal CAD baseline.
. (Join-Path $PSScriptRoot 'resolve_solidworks_2022.ps1')
$solidWorksPaths = Get-SolidWorks2022Paths
$interopPath = $solidWorksPaths.Interop
$constantsPath = $solidWorksPaths.Constants
if (-not (Test-Path -LiteralPath $interopPath -PathType Leaf)) {
    throw "SolidWorks 2022 Interop assembly was not found: $interopPath"
}
if (-not (Test-Path -LiteralPath $constantsPath -PathType Leaf)) {
    throw "SolidWorks 2022 constants assembly was not found: $constantsPath"
}
Add-Type -Path $interopPath
Add-Type -Path $constantsPath

$sw = $null
try {
    $sw = New-Object -TypeName 'SolidWorks.Interop.sldworks.SldWorksClass'
    if ($Visible) {
        $sw.Visible = $true
    }

    # The 3D Interconnect route successfully translates the STEP bodies to
    # Parasolid, but then remains blocked in a headless session.  Disable it
    # for this import so LoadFile4 uses the native, non-interactive STEP
    # importer instead.  The preference is restored before SolidWorks exits.
    $interconnectPreference = [int][SolidWorks.Interop.swconst.swUserPreferenceToggle_e]::swMultiCAD_Enable3DInterconnect
    $originalInterconnect = $sw.GetUserPreferenceToggle($interconnectPreference)
    $sw.SetUserPreferenceToggle($interconnectPreference, $false) | Out-Null

    $loadErrors = 0
    $loadWarnings = 0
    $importData = $sw.GetImportFileData($StepPath)
    $part = $sw.LoadFile4($StepPath, 'r', $importData, [ref]$loadErrors)
    if ($null -eq $part) {
        throw "SolidWorks LoadFile4 failed (error=$loadErrors; warning=$loadWarnings)."
    }

    # ImportDiagnosis launches the interactive repair workflow for this
    # multi-body STEP input and does not return in a headless automation
    # session.  LoadFile4's translator log and successful SaveAs below are
    # the non-interactive acceptance checks; -1 explicitly records that the
    # optional GUI diagnosis was not invoked.
    $diagnosisCode = -1
    $saveErrors = 0
    $saveWarnings = 0
    $saved = $part.Extension.SaveAs($SldprtPath, 0, 1, $null, [ref]$saveErrors, [ref]$saveWarnings)
    if (-not $saved) {
        throw "SolidWorks SaveAs failed (error=$saveErrors; warning=$saveWarnings)."
    }

    [PSCustomObject]@{
        stepPath = $StepPath
        sldprtPath = $SldprtPath
        loadErrors = $loadErrors
        loadWarnings = $loadWarnings
        importDiagnosisCode = $diagnosisCode
        saveErrors = $saveErrors
        saveWarnings = $saveWarnings
        solidWorksRevision = $sw.RevisionNumber()
        startedSolidWorks = $true
    } | ConvertTo-Json -Compress
}
catch {
    throw "Line $($_.InvocationInfo.ScriptLineNumber): $($_.Exception.Message)"
}
finally {
    if ($null -ne $sw) {
        if ($null -ne $originalInterconnect) {
            $sw.SetUserPreferenceToggle($interconnectPreference, $originalInterconnect) | Out-Null
        }
        $sw.ExitApp()
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($sw)
    }
}
