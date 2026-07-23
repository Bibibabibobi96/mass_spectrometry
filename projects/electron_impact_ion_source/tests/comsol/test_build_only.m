reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
assert(~isempty(reportPath), 'COMSOL_BOOTSTRAP_REPORT is required.');

projectRoot = fileparts(fileparts(fileparts(mfilename('fullpath'))));
addpath(projectRoot);
addpath(fullfile(projectRoot, 'comsol'));
contractPath = fullfile(projectRoot, 'config', 'resolved_model.json');
assert(isfile(contractPath), 'Resolved EI-source build contract is missing.');
result = ms_stage1_ei_source(contractPath, 'build_smoke');
assert(strcmp(result.status, 'PASS'), 'EI source build-only result did not pass.');
assert(isfile(result.model_path), 'EI source build-only model was not saved.');
assert(result.contract_loaded, 'Resolved EI-source contract was not loaded.');
assert(strcmp(result.contract_project_id, 'electron_impact_ion_source'), ...
    'Resolved EI-source project identity was not preserved.');
assert(strcmp(result.selected_mode_id, 'build_only_smoke'), ...
    'Build-only test consumed the wrong numerical mode.');
assert(result.parameter_bindings_verified, ...
    'GUI-visible COMSOL parameters were not bound to the resolved contract.');
assert(~result.candidate_evidence_allowed, ...
    'A build-only smoke run must never be candidate evidence.');

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Cannot create EI source build-only report.');
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, 'TASK=EI_SOURCE_BUILD_ONLY\n');
fprintf(fid, 'MODEL_PATH=%s\n', result.model_path);
fprintf(fid, 'GEOMETRY_BUILT=%s\n', string(result.geometry_built));
fprintf(fid, 'MESH_BUILT=%s\n', string(result.mesh_built));
fprintf(fid, 'ELECTROSTATICS_SOLVED=%s\n', string(result.electrostatics_solved));
fprintf(fid, 'PARTICLE_TRACING_SOLVED=%s\n', string(result.particle_tracing_solved));
fprintf(fid, 'CONTRACT_LOADED=%s\n', string(result.contract_loaded));
fprintf(fid, 'CONTRACT_PROJECT_ID=%s\n', result.contract_project_id);
fprintf(fid, 'SELECTED_MODE_ID=%s\n', result.selected_mode_id);
fprintf(fid, 'PARAMETER_BINDINGS_VERIFIED=%s\n', ...
    string(result.parameter_bindings_verified));
fprintf(fid, 'CANDIDATE_EVIDENCE_ALLOWED=%s\n', ...
    string(result.candidate_evidence_allowed));
fprintf(fid, 'STATUS=PASS\n');
