param(
    [Parameter(Mandatory = $true)]
    [string]$ReferenceCsv,

    [Parameter(Mandatory = $true)]
    [string]$CandidateCsv,

    [Parameter(Mandatory = $true)]
    [string]$ReportPath,

    [double]$MaxTofDifferenceUs = 0.001,
    [double]$MaxLandingDifferenceMm = 0.05
)

$ErrorActionPreference = 'Stop'
$reference = Import-Csv -LiteralPath $ReferenceCsv
$candidate = Import-Csv -LiteralPath $CandidateCsv
if ($reference.Count -ne $candidate.Count) {
    throw "Particle count mismatch: $($reference.Count) versus $($candidate.Count)."
}

$tofDifferences = [System.Collections.Generic.List[double]]::new()
$landingDifferences = [System.Collections.Generic.List[double]]::new()
for ($index = 0; $index -lt $reference.Count; $index++) {
    if ($reference[$index].Ion -ne $candidate[$index].Ion) {
        throw "Ion order mismatch at row $($index + 1)."
    }
    $tofDifferences.Add(
        [double]$candidate[$index].TofUs - [double]$reference[$index].TofUs)
    $dx = [double]$candidate[$index].XMm - [double]$reference[$index].XMm
    $dy = [double]$candidate[$index].YMm - [double]$reference[$index].YMm
    $landingDifferences.Add([Math]::Sqrt($dx * $dx + $dy * $dy))
}

$meanTof = ($tofDifferences | Measure-Object -Average).Average
$rmsTof = [Math]::Sqrt((($tofDifferences | ForEach-Object { $_ * $_ }) |
            Measure-Object -Average).Average)
$maxTof = (($tofDifferences | ForEach-Object { [Math]::Abs($_) }) |
        Measure-Object -Maximum).Maximum
$rmsLanding = [Math]::Sqrt((($landingDifferences | ForEach-Object { $_ * $_ }) |
            Measure-Object -Average).Average)
$maxLanding = ($landingDifferences | Measure-Object -Maximum).Maximum

$status = if ($maxTof -le $MaxTofDifferenceUs -and
    $maxLanding -le $MaxLandingDifferenceMm) { 'PASS' } else { 'FAIL' }
$report = @(
    "REFERENCE_CSV=$([IO.Path]::GetFullPath($ReferenceCsv))"
    "CANDIDATE_CSV=$([IO.Path]::GetFullPath($CandidateCsv))"
    "PARTICLES=$($reference.Count)"
    "MEAN_DELTA_TOF_US=$($meanTof.ToString('G17'))"
    "RMS_DELTA_TOF_US=$($rmsTof.ToString('G17'))"
    "MAX_ABS_DELTA_TOF_US=$($maxTof.ToString('G17'))"
    "RMS_LANDING_DELTA_MM=$($rmsLanding.ToString('G17'))"
    "MAX_LANDING_DELTA_MM=$($maxLanding.ToString('G17'))"
    "MAX_ALLOWED_TOF_DIFFERENCE_US=$($MaxTofDifferenceUs.ToString('G17'))"
    "MAX_ALLOWED_LANDING_DIFFERENCE_MM=$($MaxLandingDifferenceMm.ToString('G17'))"
    "STATUS=$status"
)
$reportDirectory = Split-Path -Parent ([IO.Path]::GetFullPath($ReportPath))
if (-not (Test-Path -LiteralPath $reportDirectory)) {
    New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
}
Set-Content -LiteralPath $ReportPath -Value $report -Encoding UTF8
$report
if ($status -ne 'PASS') {
    throw 'Candidate particle result differs from the formal reference.'
}
