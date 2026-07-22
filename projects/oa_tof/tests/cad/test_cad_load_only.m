reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
modelPath = getenv('OATOF_CAD_SMOKE_MODEL_PATH');
outputDir = getenv('OATOF_CAD_SMOKE_OUTPUT_DIR');
assert(~isempty(reportPath), 'COMSOL_BOOTSTRAP_REPORT is required.');
assert(~isempty(modelPath), 'OATOF_CAD_SMOKE_MODEL_PATH is required.');
assert(~isempty(outputDir), 'OATOF_CAD_SMOKE_OUTPUT_DIR is required.');
assert(~isfolder(outputDir), 'The load-only output sentinel must not already exist.');

projectRoot = fileparts(fileparts(fileparts(mfilename('fullpath'))));
addpath(projectRoot);
addpath(fullfile(projectRoot, 'cad'));
result = export_oatof_cad_step(modelPath, outputDir, 'load_only');

assert(result.modelLoaded, 'The oaTOF MPH was not loaded.');
assert(result.geometryResolved, 'The oaTOF geometry was not resolved.');
assert(result.exportableObjectCount > 0, 'No exportable oaTOF objects were discovered.');
assert(~result.stepExported, 'The load-only smoke unexpectedly exported STEP.');
assert(~result.formalAssetModified, 'The load-only smoke reported a Formal modification.');
assert(~isfolder(outputDir), 'The load-only smoke created its output sentinel directory.');

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Cannot create oaTOF CAD load-only report.');
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, 'TASK=OATOF_CAD_LOAD_ONLY\n');
fprintf(fid, 'MODEL_PATH=%s\n', result.modelPath);
fprintf(fid, 'MODEL_LOADED=%s\n', string(result.modelLoaded));
fprintf(fid, 'GEOMETRY_RESOLVED=%s\n', string(result.geometryResolved));
fprintf(fid, 'BODY_FEATURE_COUNT=%d\n', result.bodyFeatureCount);
fprintf(fid, 'EXPORTABLE_OBJECT_COUNT=%d\n', result.exportableObjectCount);
fprintf(fid, 'STEP_EXPORTED=%s\n', string(result.stepExported));
fprintf(fid, 'FORMAL_ASSET_MODIFIED=%s\n', string(result.formalAssetModified));
fprintf(fid, 'SOLVER_RUN=false\n');
fprintf(fid, 'STATUS=PASS\n');
