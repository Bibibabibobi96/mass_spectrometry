reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
assert(~isempty(reportPath), 'COMSOL_BOOTSTRAP_REPORT is required.');

projectRoot = fileparts(fileparts(fileparts(mfilename('fullpath'))));
addpath(projectRoot);
addpath(fullfile(projectRoot, 'comsol'));
result = ms_stage1_ei_source(1e19, 'build_smoke', 'build_only');
assert(strcmp(result.status, 'PASS'), 'EI source build-only result did not pass.');
assert(isfile(result.model_path), 'EI source build-only model was not saved.');

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Cannot create EI source build-only report.');
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, 'TASK=EI_SOURCE_BUILD_ONLY\n');
fprintf(fid, 'MODEL_PATH=%s\n', result.model_path);
fprintf(fid, 'GEOMETRY_BUILT=%s\n', string(result.geometry_built));
fprintf(fid, 'MESH_BUILT=%s\n', string(result.mesh_built));
fprintf(fid, 'ELECTROSTATICS_SOLVED=%s\n', string(result.electrostatics_solved));
fprintf(fid, 'PARTICLE_TRACING_SOLVED=%s\n', string(result.particle_tracing_solved));
fprintf(fid, 'STATUS=PASS\n');
