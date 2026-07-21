[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$SourceRunId,
  [Parameter(Mandatory = $true)][string]$RunId
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$source = Join-Path $artifactRoot "runs\$SourceRunId"
$sourceManifestPath = Join-Path $source 'run_manifest.json'
$sourceManifest = Get-Content -LiteralPath $sourceManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($sourceManifest.status -ne 'success' -or $sourceManifest.mode -ne 'rf_to_oatof_s1_local_joint_field') {
  throw 'Capture comparison requires a successful S1 local joint-field particle run.'
}
$runDir = Join-Path $artifactRoot "runs\$RunId"
if (Test-Path -LiteralPath $runDir) { throw "Run already exists: $runDir" }
$inputDir = Join-Path $runDir 'inputs'; $resultDir = Join-Path $runDir 'results'
New-Item -ItemType Directory -Force -Path $inputDir,$resultDir | Out-Null
$entry = Join-Path $inputDir 'canonical_rf_exit_at_oatof_entry.csv'
$local = Join-Path $inputDir 's1_physical_port_particles.csv'
$capture = Join-Path $inputDir 's1_pulse_capture_particles.csv'
$baseline = Join-Path $inputDir 'oatof_baseline.json'
$formalValidation = Join-Path $inputDir 'oatof_formal_validation.json'
$analysis = Join-Path $inputDir 'compare_s1_capture_to_oatof_ideal_source.py'
$generator = Join-Path $inputDir 'generate_comsol_consistent_ions.ps1.txt'
Copy-Item -LiteralPath (Join-Path $source 'inputs\canonical_rf_exit_at_oatof_entry.csv') -Destination $entry
Copy-Item -LiteralPath (Join-Path $source 'results\s1_physical_port_particles.csv') -Destination $local
Copy-Item -LiteralPath (Join-Path $source 'results\s1_pulse_capture_particles.csv') -Destination $capture
Copy-Item -LiteralPath (Join-Path $repoRoot 'projects\oa_tof\config\baseline.json') -Destination $baseline
Copy-Item -LiteralPath (Join-Path $repoRoot 'projects\oa_tof\config\formal_validation.json') -Destination $formalValidation
Copy-Item -LiteralPath (Join-Path $projectRoot 'analysis\compare_s1_capture_to_oatof_ideal_source.py') -Destination $analysis
$generatorSource = Join-Path $repoRoot 'projects\oa_tof\simion\workbench\generate_comsol_consistent_ions.ps1'
Copy-Item -LiteralPath $generatorSource -Destination $generator
$baselineDocument = Get-Content -LiteralPath $baseline -Raw -Encoding UTF8 | ConvertFrom-Json
$validationDocument = Get-Content -LiteralPath $formalValidation -Raw -Encoding UTF8 | ConvertFrom-Json
$entryFirst = Import-Csv -LiteralPath $entry | Select-Object -First 1
$sourceDesign = $baselineDocument.particle_source
$energyMean = [double]$validationDocument.shared_particles.initial_energy_mean_eV
$energySigma = [double]$validationDocument.shared_particles.initial_energy_sigma_eV
$massAmu = [double]$entryFirst.mass_amu; $chargeState = [int]$entryFirst.charge_state
$ideal = Join-Path $inputDir 'oatof_ideal_mass_matched_100amu_n100.ion'
& $generatorSource -N 100 -MassAmu $massAmu -Charge $chargeState `
  -EnergyMeanEv $energyMean -EnergyStdEv $energySigma `
  -HalfWidthXmm ([double]$sourceDesign.size_x_mm/2) `
  -HalfWidthYmm ([double]$sourceDesign.size_y_mm/2) `
  -HalfWidthZmm ([double]$sourceDesign.size_z_mm/2) `
  -CenterXmm ([double]$sourceDesign.center_x_mm) -CenterYmm ([double]$sourceDesign.center_y_mm) `
  -CenterZmm ([double]$sourceDesign.center_z_mm) -Seed ([int]$sourceDesign.seed) -Output $ideal | Out-Null
if (-not $?) { throw 'Mass-matched oaTOF ideal source generation failed.' }
$figure = Join-Path $resultDir 's1_capture_vs_oatof_ideal_source.png'
$comparison = Join-Path $resultDir 's1_capture_vs_oatof_ideal_source.json'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
& $python $analysis --capture $capture --entry $entry --local $local --ideal-ion $ideal `
  --oatof-baseline $baseline --figure $figure --summary $comparison
if ($LASTEXITCODE -ne 0) { throw 'S1 pulse-capture versus ideal-source analysis failed.' }
$comparisonDocument = Get-Content -LiteralPath $comparison -Raw -Encoding UTF8 | ConvertFrom-Json
$runConfig = Join-Path $runDir 'run_config.json'
[ordered]@{schema_version=1;run_id=$RunId;project='rf_quadrupole_collision_cooling';mode='rf_oatof_s1_capture_vs_ideal_source';project_root=$repoRoot;inputs=[ordered]@{source_run_manifest=$sourceManifestPath;entry=$entry;local=$local;capture=$capture;oatof_baseline=$baseline;oatof_formal_validation=$formalValidation;ideal_ion=$ideal;analysis=$analysis;ideal_generator=$generator};parameters=[ordered]@{source_run_id=$SourceRunId;particles=100;mass_amu=$massAmu;charge_state=$chargeState;pulse_time_us=[double]$comparisonDocument.pulse_instrument_time_us;solver_rerun=$false;equivalent_capture_time_state_available=$true};formal_gate_passed=$false} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $runConfig -Encoding UTF8
$summary = Join-Path $runDir 'summary.json'
[ordered]@{schema_version=1;role='rf_oatof_s1_capture_vs_ideal_source_run_summary';status='success';comparison='results/s1_capture_vs_oatof_ideal_source.json';figure='results/s1_capture_vs_oatof_ideal_source.png';formal_source_equivalence_claim_allowed=$false} | ConvertTo-Json | Set-Content -LiteralPath $summary -Encoding UTF8
$writer = Join-Path $repoRoot 'common\contracts\write_run_manifest.py'
& $python $writer --run-config $runConfig --status success --software 'Python 3.11' --output $figure --output $comparison --output $summary
if ($LASTEXITCODE -ne 0) { throw 'S1 capture comparison manifest failed.' }
Write-Output "S1_CAPTURE_IDEAL_COMPARISON_RUN=PASS RUN_ID=$RunId"
