reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
assert(~isempty(reportPath), 'COMSOL_BOOTSTRAP_REPORT is required.');

projectRoot = fileparts(fileparts(fileparts(mfilename('fullpath'))));
addpath(projectRoot);
phase1_geometry_coil_transverse();
electrostatic = phase2_electrostatics_coil_transverse('build_only');
thermal = phase4_thermal_emission_coil_transverse('build_only');
assert(strcmp(electrostatic.status, 'PASS'), 'Wehnelt electrostatic build-only result did not pass.');
assert(strcmp(thermal.status, 'PASS'), 'Wehnelt CPT build-only result did not pass.');
assert(isfile(electrostatic.model_path), 'Wehnelt electrostatic build-only model was not saved.');
assert(isfile(thermal.model_path), 'Wehnelt CPT build-only model was not saved.');

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
fprintf(fid, 'STATUS=PASS\n');
