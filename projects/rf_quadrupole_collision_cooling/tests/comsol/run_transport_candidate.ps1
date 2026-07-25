param(
    [string]$RunId = '',
    [int]$RfStepsPerPeriod = 80,
    [int]$MeshAutoLevel = 1,
    [double]$MeshHmaxMm = [double]::NaN,
    [double]$SourceAxialOffsetMm = 0.0,
    [string]$ParticleTablePath = '',
    [string]$ParticleBundleMetadataPath = '',
    [string]$SourceFamilyPath = '',
    [string]$ParticleDistributionPath = '',
    [ValidateSet('transport_interface_readiness')][string]$Mode = 'transport_interface_readiness',
    [string]$OperatingPoint = 'official_100amu_2eV'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$repoRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if ([string]::IsNullOrWhiteSpace($RunId)) {
    $detail = $Mode.Replace('_','-')
    $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + "__sim__comsol__rf-transport__$detail"
}
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $RunId" }
$runDir = Join-Path $artifactRoot "runs\$RunId"
$resultDir = Join-Path $runDir 'results'
$inputDir = Join-Path $runDir 'inputs'
$candidateDir = Join-Path $runDir 'comsol'
$logDir = Join-Path $runDir 'logs'
$runtimeDir = Join-Path $runDir 'runtime'
if (Test-Path -LiteralPath $runDir) { throw "Run directory already exists: $RunId" }

$particleTable = if ([string]::IsNullOrWhiteSpace($ParticleTablePath)) {
    Join-Path $projectRoot 'config\particles\official_fixed_100.ion'
} else { [IO.Path]::GetFullPath($ParticleTablePath) }
if (-not (Test-Path -LiteralPath $particleTable -PathType Leaf)) { throw "Particle table is missing: $particleTable" }
$expectedParticles = @(Get-Content -LiteralPath $particleTable -Encoding UTF8 | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count
& $python -m common.contracts.particle_count_policy --count $expectedParticles
if ($LASTEXITCODE -ne 0) { throw 'Particle table violates the repository N=100/N=1000 policy.' }
$resolvedContractInput = 'config/resolved_design_official.json'
$resolved = Get-Content -LiteralPath (Join-Path $projectRoot $resolvedContractInput) -Raw -Encoding UTF8 | ConvertFrom-Json
$minimumParticles = (Get-Content -LiteralPath (Join-Path $projectRoot 'config\modes\transport_interface_readiness.json') -Raw -Encoding UTF8 | ConvertFrom-Json).numerics.minimum_diagnostic_particles
if ([string]::IsNullOrWhiteSpace($ParticleTablePath) -or $expectedParticles -lt $minimumParticles) {
    throw "Interface-readiness mode requires an explicit particle table with at least $minimumParticles particles."
}
if ([string]::IsNullOrWhiteSpace($ParticleBundleMetadataPath)) {
    throw 'Interface-readiness mode requires ParticleBundleMetadataPath.'
}
$bundleMetadataInput = [IO.Path]::GetFullPath($ParticleBundleMetadataPath)
$sourceFamilyInput = if ($SourceFamilyPath) {
    [IO.Path]::GetFullPath($SourceFamilyPath)
} else {
    Join-Path $projectRoot 'config\interface_readiness_particle_source.json'
}
$distributionInput = if ($ParticleDistributionPath) {
    [IO.Path]::GetFullPath($ParticleDistributionPath)
} else {
    Join-Path $projectRoot 'config\official_particle_source.json'
}
foreach ($sourceContract in @($bundleMetadataInput,$sourceFamilyInput,$distributionInput)) {
    if (-not (Test-Path -LiteralPath $sourceContract -PathType Leaf)) {
        throw "Paired particle source contract is missing: $sourceContract"
    }
}
$RfPeakV = [double]$resolved.drive.rf_amplitude_V_zero_to_peak_per_group
$FrequencyHz = [double]$resolved.drive.frequency_Hz
$PhaseRad = [double]$resolved.drive.phase_rad
$modeInput = 'config/modes/transport_interface_readiness.json'

New-Item -ItemType Directory -Path $runDir,$inputDir,$resultDir,$candidateDir,$logDir,$runtimeDir -Force | Out-Null

$frozenSourceFamily = Join-Path $inputDir 'particle_source_family.json'
$frozenDistribution = Join-Path $inputDir 'particle_source_distribution.json'
$sourceBinding = Join-Path $inputDir 'particle_source_binding.json'
Copy-Item -LiteralPath $sourceFamilyInput -Destination $frozenSourceFamily
Copy-Item -LiteralPath $distributionInput -Destination $frozenDistribution
$bindingArguments = @(
    '-m','projects.rf_quadrupole_collision_cooling.analysis.validate_paired_particle_source_binding',
    '--bundle-metadata',$bundleMetadataInput,
    '--source-family',$frozenSourceFamily,
    '--distribution',$frozenDistribution,
    '--resolved-design',(Join-Path $projectRoot $resolvedContractInput),
    '--operating-point',$OperatingPoint,
    '--particle-count',$expectedParticles,
    '--consumed-representation','ion11',
    '--expected-consumed',$particleTable,
    '--output',$sourceBinding
)
Push-Location $repoRoot
try {
    & $python @bindingArguments
    if ($LASTEXITCODE -ne 0) { throw 'Paired particle source bundle binding failed.' }
}
finally { Pop-Location }
$bundleDocument = Get-Content -LiteralPath $bundleMetadataInput -Raw -Encoding UTF8 | ConvertFrom-Json
$frozenBundleRoot = Join-Path $inputDir 'paired_bundle'
New-Item -ItemType Directory -Path $frozenBundleRoot -Force | Out-Null
foreach ($entry in $bundleDocument.artifacts) {
    $sourceArtifact = Join-Path (Split-Path -Parent $bundleMetadataInput) ([string]$entry.relative_path)
    $frozenArtifact = Join-Path $frozenBundleRoot ([string]$entry.relative_path)
    New-Item -ItemType Directory -Path (Split-Path -Parent $frozenArtifact) -Force | Out-Null
    Copy-Item -LiteralPath $sourceArtifact -Destination $frozenArtifact
}
$frozenBundleMetadata = Join-Path $frozenBundleRoot 'paired_particle_bundle.json'
Copy-Item -LiteralPath $bundleMetadataInput -Destination $frozenBundleMetadata
$ionEntry = @($bundleDocument.artifacts | Where-Object {
    $_.operating_point_id -eq $OperatingPoint -and
    [int]$_.particle_count -eq $expectedParticles -and
    $_.representation -eq 'ion11'
})
$canonicalEntry = @($bundleDocument.artifacts | Where-Object {
    $_.operating_point_id -eq $OperatingPoint -and
    [int]$_.particle_count -eq $expectedParticles -and
    $_.representation -eq 'canonical10'
})
if ($ionEntry.Count -ne 1 -or $canonicalEntry.Count -ne 1) {
    throw 'Frozen paired bundle selection is not unique.'
}
$particleTable = Join-Path $frozenBundleRoot ([string]$ionEntry[0].relative_path)
$frozenCanonicalPath = Join-Path $frozenBundleRoot ([string]$canonicalEntry[0].relative_path)
$frozenBindingArguments = @(
    '-m','projects.rf_quadrupole_collision_cooling.analysis.validate_paired_particle_source_binding',
    '--bundle-metadata',$frozenBundleMetadata,
    '--source-family',$frozenSourceFamily,
    '--distribution',$frozenDistribution,
    '--resolved-design',(Join-Path $projectRoot $resolvedContractInput),
    '--operating-point',$OperatingPoint,
    '--particle-count',$expectedParticles,
    '--consumed-representation','ion11',
    '--expected-consumed',$particleTable,
    '--output',$sourceBinding
)
Push-Location $repoRoot
try {
    & $python @frozenBindingArguments
    if ($LASTEXITCODE -ne 0) { throw 'Frozen paired particle source bundle binding failed.' }
}
finally { Pop-Location }
$bindingDocument = Get-Content -LiteralPath $sourceBinding -Raw -Encoding UTF8 | ConvertFrom-Json

$runConfigPath = Join-Path $runDir 'run_config.json'
$bootstrapReport = Join-Path $logDir 'comsol_bootstrap_report.txt'
$guiVerifyReport = Join-Path $logDir 'comsol_gui_compute_report.txt'
$stateContractReport = Join-Path $resultDir 'particle_state_contract.json'
$runConfig = [ordered]@{
    schema_version=1; role='rf_quadrupole_comsol_run_config'; run_id=$RunId
    project='rf_quadrupole_collision_cooling'; mode=$Mode; project_root=$projectRoot
    inputs=[ordered]@{
        resolved_design=$resolvedContractInput
        mode=$modeInput; particle_table=$particleTable
        interface_contract='config/interface_contract.json'
        consumed_particle_table=$particleTable
        source_ion11=$particleTable
        source_canonical10=$frozenCanonicalPath
        particle_bundle_metadata=$frozenBundleMetadata
        particle_source_binding=$sourceBinding
        particle_source_family=$frozenSourceFamily
        particle_source_distribution=$frozenDistribution
    }
    results_dir=$resultDir; comsol_dir=$candidateDir; logs_dir=$logDir; runtime_dir=$runtimeDir; run_dir=$runDir
    comsol_rf_steps_per_period=$RfStepsPerPeriod; comsol_mesh_auto_level=$MeshAutoLevel
    comsol_hmax_mm=$MeshHmaxMm; source_axial_offset_mm=$SourceAxialOffsetMm
    particle_table_path=$particleTable; operating_point=$OperatingPoint
    rf_peak_v=$RfPeakV; frequency_hz=$FrequencyHz; particles=$expectedParticles
    formal_gate_passed=$false
    provenance=[ordered]@{
        source_sample_family_sha256=[string]$bindingDocument.source_sample_family_sha256
        source_family_sha256=[string]$bindingDocument.source_family_sha256
        distribution_sha256=[string]$bindingDocument.distribution_sha256
        latent_sha256=[string]$bindingDocument.latent_sha256
        coordinate_mapping_version=[string]$bindingDocument.coordinate_mapping_version
        representation_equivalence=[string]$bindingDocument.representation_equivalence
        operating_point_id=$OperatingPoint
        particle_count=$expectedParticles
        representation='ion11'
        consumed_sha256=[string]$bindingDocument.consumed_sha256
        particle_source_sha256=[string]$bindingDocument.consumed_sha256
        ion11_sha256=[string]$bindingDocument.ion11_sha256
        canonical10_sha256=[string]$bindingDocument.canonical10_sha256
        n1000_parent=$bindingDocument.n1000_parent
        ion11_n1000_parent=$bindingDocument.ion11_n1000_parent
        canonical10_n1000_parent=$bindingDocument.canonical10_n1000_parent
    }
}
$bundleArtifactIndex = 0
foreach ($entry in $bundleDocument.artifacts) {
    $bundleArtifactIndex += 1
    $runConfig.inputs[("bundle_artifact_{0:D3}" -f $bundleArtifactIndex)] = Join-Path `
        $frozenBundleRoot ([string]$entry.relative_path)
}
# The run config is ASCII-only.  Avoid the Windows PowerShell 5.1 UTF-8 BOM,
# which MATLAB jsondecode treats as an invalid first JSON character.
$runConfig | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runConfigPath -Encoding ASCII

$env:RFQUAD_RUN_CONFIG = $runConfigPath
try {
    & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') `
        -TaskScript (Join-Path $PSScriptRoot 'run_nocollision_candidate.m') `
        -ReportPath $bootstrapReport -StartupReportTimeoutSeconds 120
    if ($LASTEXITCODE -ne 0) { throw 'COMSOL candidate launcher failed.' }
}
finally {
    Remove-Item Env:RFQUAD_RUN_CONFIG -ErrorAction SilentlyContinue
}

$modelPath = Join-Path $candidateDir 'rf_quadrupole_collision_cooling__model.mph'
$summaryPath = Join-Path $resultDir 'solver_summary.json'
$trajectoryPath = Join-Path $resultDir 'trajectory_samples.csv'
$particleStatePath = Join-Path $resultDir 'particle_state.csv'
$rawPhaseSpacePath = Join-Path $resultDir 'particle_raw.csv'
$summary = Get-Content -LiteralPath $summaryPath -Raw -Encoding UTF8 | ConvertFrom-Json
$env:RFQUAD_COMSOL_MODEL_PATH = $modelPath
$env:RFQUAD_EXPECTED_PARTICLES = [string]$expectedParticles
$env:RFQUAD_EXPECTED_HITS = [string]$summary.hits
$env:RFQUAD_EXPECTED_RF_PEAK_V = [string]$RfPeakV
$env:RFQUAD_EXPECTED_FREQUENCY_HZ = [string]$FrequencyHz
try {
    & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') `
        -TaskScript (Join-Path $PSScriptRoot 'verify_nocollision_comsol.m') `
        -ReportPath $guiVerifyReport
    if ($LASTEXITCODE -ne 0) { throw 'COMSOL GUI Compute verification failed.' }
}
finally {
    Remove-Item Env:RFQUAD_COMSOL_MODEL_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:RFQUAD_EXPECTED_PARTICLES -ErrorAction SilentlyContinue
    Remove-Item Env:RFQUAD_EXPECTED_HITS -ErrorAction SilentlyContinue
    Remove-Item Env:RFQUAD_EXPECTED_RF_PEAK_V -ErrorAction SilentlyContinue
    Remove-Item Env:RFQUAD_EXPECTED_FREQUENCY_HZ -ErrorAction SilentlyContinue
}

$expected = @($modelPath,$summaryPath,$trajectoryPath,$particleStatePath,$rawPhaseSpacePath,$bootstrapReport,$guiVerifyReport)
$missing = @($expected | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) })
if ($missing.Count -gt 0) { throw "COMSOL candidate outputs are missing: $($missing -join ', ')" }

Push-Location $repoRoot
try {
& $python -m common.contracts.particle_state `
    --state $particleStatePath --particles $particleTable --source-format ion11 `
    --contract (Join-Path $projectRoot 'config\interface_contract.json') --axial-offset-mm $SourceAxialOffsetMm `
    --frequency-hz $FrequencyHz --phase-rad $PhaseRad `
    --solver COMSOL --output $stateContractReport
    if ($LASTEXITCODE -ne 0) { throw 'Particle-state contract gate failed.' }
}
finally { Pop-Location }

$runSummary = Join-Path $runDir 'summary.json'
[ordered]@{
    schema_version=1; role='rf_quadrupole_transport_summary'; status='success'; mode=$Mode
    particles=$expectedParticles; hits=$summary.hits; transmission=$summary.transmission
    mean_output_energy_eV=$summary.mean_output_energy_eV
    solver_summary='results/solver_summary.json'
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $runSummary -Encoding UTF8

& $python (Join-Path $repoRoot 'common\contracts\write_run_manifest.py') --run-config $runConfigPath `
    --status success --software 'COMSOL 6.4' --software 'MATLAB R2025b' `
    --output $modelPath --output $summaryPath --output $trajectoryPath `
    --output $particleStatePath --output $rawPhaseSpacePath --output $bootstrapReport --output $guiVerifyReport --output $stateContractReport --output $runSummary
if ($LASTEXITCODE -ne 0) { throw 'Run-manifest generation failed.' }
"STATUS=PASS RUN_ID=$RunId HITS=$($summary.hits) TRANSMISSION=$($summary.transmission)"
