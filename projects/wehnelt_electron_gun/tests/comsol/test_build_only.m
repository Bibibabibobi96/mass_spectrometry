reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
assert(~isempty(reportPath), 'COMSOL_BOOTSTRAP_REPORT is required.');

projectRoot = fileparts(fileparts(fileparts(mfilename('fullpath'))));
addpath(projectRoot);
resolvedContractPath = fullfile(projectRoot, 'config', 'resolved_model.json');
geometry = phase1_geometry_coil_transverse(resolvedContractPath);
electrostatic = phase2_electrostatics_coil_transverse(resolvedContractPath);
thermal = phase4_thermal_emission_coil_transverse(resolvedContractPath);
assert(strcmp(geometry.status, 'PASS'), ...
    'Wehnelt geometry build-only result did not pass.');
assert(strcmp(electrostatic.status, 'PASS'), 'Wehnelt electrostatic build-only result did not pass.');
assert(strcmp(thermal.status, 'PASS'), 'Wehnelt CPT build-only result did not pass.');
assert(isfile(electrostatic.model_path), 'Wehnelt electrostatic build-only model was not saved.');
assert(isfile(thermal.model_path), 'Wehnelt CPT build-only model was not saved.');
assert(geometry.contract_loaded && electrostatic.contract_loaded && ...
    thermal.contract_loaded, 'Resolved Wehnelt contract was not loaded.');
assert(strcmp(thermal.contract_project_id, 'wehnelt_electron_gun'), ...
    'Resolved Wehnelt project identity was not preserved.');
assert(strcmp(thermal.selected_mode_id, 'build_only_smoke'), ...
    'Build-only test consumed the wrong numerical mode.');
assert(geometry.parameter_bindings_verified && ...
    electrostatic.parameter_bindings_verified && ...
    thermal.parameter_bindings_verified, ...
    'GUI-visible COMSOL parameters were not bound to the resolved contract.');
assert(~thermal.candidate_evidence_allowed, ...
    'A build-only smoke run must never be Candidate evidence.');

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Cannot create Wehnelt build-only report.');
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, 'TASK=WEHNELT_THREE_STAGE_BUILD_ONLY\n');
fprintf(fid, 'ELECTROSTATIC_MODEL_PATH=%s\n', electrostatic.model_path);
fprintf(fid, 'CPT_MODEL_PATH=%s\n', thermal.model_path);
fprintf(fid, 'GEOMETRY_BUILT=%s\n', string(electrostatic.geometry_built));
fprintf(fid, 'MESH_BUILT=%s\n', string(electrostatic.mesh_built));
fprintf(fid, 'ELECTROSTATICS_SOLVED=%s\n', string(thermal.electrostatics_solved));
fprintf(fid, 'CPT_TREE_BUILT=%s\n', string(thermal.cpt_tree_built));
fprintf(fid, 'PARTICLE_TRACING_SOLVED=%s\n', string(thermal.particle_tracing_solved));
fprintf(fid, 'CONTRACT_LOADED=%s\n', string(thermal.contract_loaded));
fprintf(fid, 'CONTRACT_PROJECT_ID=%s\n', thermal.contract_project_id);
fprintf(fid, 'SELECTED_MODE_ID=%s\n', thermal.selected_mode_id);
fprintf(fid, 'PARAMETER_BINDINGS_VERIFIED=%s\n', ...
    string(thermal.parameter_bindings_verified));
fprintf(fid, 'CANDIDATE_EVIDENCE_ALLOWED=%s\n', ...
    string(thermal.candidate_evidence_allowed));
fprintf(fid, 'STATUS=PASS\n');
