param(
    [int]$RfStepsPerPeriod = 40,
    [int]$TrajectoryQuality = 10,
    [string]$RunLabel = 'baseline',
    [double]$SourceAxialOffsetMm = 0.0,
    [string]$CandidateSubdir = 'quad_transport'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$repoRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$candidateDir = Join-Path $artifactRoot "models\simion\candidates\$CandidateSubdir"
$resultDir = Join-Path $artifactRoot 'results\simion'
$runDir = Join-Path $artifactRoot "runs\transport_no_collision\simion_$RunLabel"
$simion = 'C:\Program Files\SIMION-2020\simion.exe'
$officialIob = 'C:\Program Files\SIMION-2020\examples\quad\quad_monolithic.iob'

New-Item -ItemType Directory -Path $candidateDir,$resultDir,$runDir -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot 'simion\geometry\quad_include.gem') -Destination $candidateDir -Force
Copy-Item -LiteralPath (Join-Path $projectRoot 'simion\geometry\quad_monolithic.gem') -Destination $candidateDir -Force
Copy-Item -LiteralPath (Join-Path $projectRoot 'simion\programs\quad_transport.lua') -Destination (Join-Path $candidateDir 'quad_monolithic.lua') -Force
Copy-Item -LiteralPath $officialIob -Destination (Join-Path $candidateDir 'quad_monolithic.iob') -Force

$ionPath = Join-Path $projectRoot 'config\particles\official_fixed_25.ion'
$flyPath = Join-Path $candidateDir 'quad_monolithic.fly2'
& (Join-Path $repoRoot '.venv\Scripts\python.exe') `
    (Join-Path $projectRoot 'analysis\generate_fixed_fly2.py') $ionPath $flyPath `
    --axial-offset-mm $SourceAxialOffsetMm
if ($LASTEXITCODE -ne 0) { throw 'Fixed FLY2 generation failed.' }

Push-Location $candidateDir
try {
    & $simion --nogui gem2pa quad_monolithic.gem quad_monolithic.pa#
    if ($LASTEXITCODE -ne 0) { throw 'SIMION gem2pa failed.' }
    & $simion --nogui refine quad_monolithic.pa#
    if ($LASTEXITCODE -ne 0) { throw 'SIMION refine failed.' }

    $env:RFQUAD_SIMION_PARTICLE_CSV = Join-Path $resultDir "transport_no_collision_particles_$RunLabel.csv"
    $env:RFQUAD_SIMION_TRAJECTORY_CSV = Join-Path $resultDir "transport_no_collision_trajectory_samples_$RunLabel.csv"
    $env:RFQUAD_SIMION_SUMMARY_JSON = Join-Path $resultDir "transport_no_collision_summary_$RunLabel.json"
    $env:RFQUAD_SIMION_IOB = Join-Path $candidateDir 'quad_monolithic.iob'
    $env:RFQUAD_SIMION_FLY2 = $flyPath
    $env:RFQUAD_SIMION_QUALITY = [string]$TrajectoryQuality
    $env:RFQUAD_SIMION_STEPS = [string]$RfStepsPerPeriod
    & $simion --nogui lua (Join-Path $PSScriptRoot 'run_fly.lua') 2>&1 |
        Tee-Object -FilePath (Join-Path $runDir 'simion_stdout.txt')
    if ($LASTEXITCODE -ne 0) { throw 'SIMION fly failed.' }
}
finally {
    Remove-Item Env:RFQUAD_SIMION_PARTICLE_CSV -ErrorAction SilentlyContinue
    Remove-Item Env:RFQUAD_SIMION_TRAJECTORY_CSV -ErrorAction SilentlyContinue
    Remove-Item Env:RFQUAD_SIMION_SUMMARY_JSON -ErrorAction SilentlyContinue
    Remove-Item Env:RFQUAD_SIMION_IOB -ErrorAction SilentlyContinue
    Remove-Item Env:RFQUAD_SIMION_FLY2 -ErrorAction SilentlyContinue
    Remove-Item Env:RFQUAD_SIMION_QUALITY -ErrorAction SilentlyContinue
    Remove-Item Env:RFQUAD_SIMION_STEPS -ErrorAction SilentlyContinue
    Pop-Location
}

$summary = Get-Content -LiteralPath (Join-Path $resultDir "transport_no_collision_summary_$RunLabel.json") -Raw | ConvertFrom-Json
if ($summary.particles -ne 25 -or $summary.collision_model -ne 'none' -or $summary.transmission -lt 0.8) {
    throw "SIMION transport gate failed: $($summary | ConvertTo-Json -Compress)"
}
"STATUS=PASS LABEL=$RunLabel HITS=$($summary.hits) TRANSMISSION=$($summary.transmission)"
