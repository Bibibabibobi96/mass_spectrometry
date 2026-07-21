[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$ControlRunId,
  [Parameter(Mandatory=$true)][string]$CandidateRunId,
  [Parameter(Mandatory=$true)][string]$RunId
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot=(Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$artifactRoot=Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$control=Join-Path $artifactRoot "runs\$ControlRunId";$candidate=Join-Path $artifactRoot "runs\$CandidateRunId"
$controlManifestPath=Join-Path $control 'run_manifest.json';$candidateManifestPath=Join-Path $candidate 'run_manifest.json'
$controlManifest=Get-Content $controlManifestPath -Raw -Encoding UTF8|ConvertFrom-Json;$candidateManifest=Get-Content $candidateManifestPath -Raw -Encoding UTF8|ConvertFrom-Json
if($controlManifest.status-ne'success'-or$candidateManifest.status-ne'success'-or$candidateManifest.mode-ne'rf_to_oatof_energy_match_n100'){throw 'RF input-energy comparison source manifests are invalid.'}
$runDir=Join-Path $artifactRoot "runs\$RunId";if(Test-Path $runDir){throw "Run already exists: $runDir"}
$inputDir=Join-Path $runDir 'inputs';$resultDir=Join-Path $runDir 'results';New-Item -ItemType Directory -Force -Path $inputDir,$resultDir|Out-Null
$controlEvents=Join-Path $inputDir 'control_2eV_events.csv';$candidateEvents=Join-Path $inputDir 'candidate_5eV_events.csv';$controlIon=Join-Path $inputDir 'control_2eV_particles.ion';$candidateIon=Join-Path $inputDir 'candidate_5eV_particles.ion';$contract=Join-Path $inputDir 'rf_to_oatof_energy_match_candidate.json';$analysis=Join-Path $inputDir 'compare_rf_input_energy.py'
Copy-Item (Join-Path $control 'results\rf_hybrid_mesh_n100_events.csv') $controlEvents;Copy-Item (Join-Path $candidate 'results\rf_hybrid_mesh_n100_events.csv') $candidateEvents;Copy-Item (Join-Path $control 'inputs\particles.ion') $controlIon;Copy-Item (Join-Path $candidate 'inputs\particles.ion') $candidateIon;Copy-Item (Join-Path $projectRoot 'config\rf_to_oatof_energy_match_candidate.json') $contract;Copy-Item (Join-Path $projectRoot 'analysis\compare_rf_input_energy.py') $analysis
$figure=Join-Path $resultDir 'rf_input_energy_2eV_vs_5eV.png';$comparison=Join-Path $resultDir 'rf_input_energy_2eV_vs_5eV.json';$python=Join-Path $repoRoot '.venv\Scripts\python.exe'
& $python $analysis --control-events $controlEvents --candidate-events $candidateEvents --control-ion $controlIon --candidate-ion $candidateIon --contract $contract --figure $figure --summary $comparison
if($LASTEXITCODE-ne 0){throw 'RF input-energy comparison failed.'}
$runConfig=Join-Path $runDir 'run_config.json';[ordered]@{schema_version=1;run_id=$RunId;project='rf_quadrupole_collision_cooling';mode='rf_to_oatof_input_energy_comparison';project_root=$repoRoot;inputs=[ordered]@{control_manifest=$controlManifestPath;candidate_manifest=$candidateManifestPath;control_events=$controlEvents;candidate_events=$candidateEvents;control_ion=$controlIon;candidate_ion=$candidateIon;contract=$contract;analysis=$analysis};parameters=[ordered]@{control_run_id=$ControlRunId;candidate_run_id=$CandidateRunId;particles=100;only_source_variable='kinetic_energy_eV';solver_rerun=$false};formal_gate_passed=$false}|ConvertTo-Json -Depth 6|Set-Content $runConfig -Encoding UTF8
$summary=Join-Path $runDir 'summary.json';[ordered]@{schema_version=1;role='rf_to_oatof_input_energy_comparison_run_summary';status='success';comparison='results/rf_input_energy_2eV_vs_5eV.json';figure='results/rf_input_energy_2eV_vs_5eV.png';downstream_oatof_performance_claim_allowed=$false}|ConvertTo-Json|Set-Content $summary -Encoding UTF8
$writer=Join-Path $repoRoot 'common\contracts\write_run_manifest.py';& $python $writer --run-config $runConfig --status success --software 'Python 3.11' --output $figure --output $comparison --output $summary
if($LASTEXITCODE-ne 0){throw 'RF input-energy comparison manifest failed.'};Write-Output "RF_INPUT_ENERGY_COMPARISON_RUN=PASS RUN_ID=$RunId"
