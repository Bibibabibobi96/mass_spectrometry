% Export COMSOL E-vector values at solver-neutral accelerator sample points.

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
inputCsv = getenv('OATOF_ACCELERATOR_SAMPLE_CSV');
outputCsv = getenv('OATOF_COMSOL_VECTOR_FIELD_CSV');
assert(~isempty(inputCsv) && isfile(inputCsv), ...
    'OATOF_ACCELERATOR_SAMPLE_CSV is missing.');
assert(~isempty(outputCsv), 'OATOF_COMSOL_VECTOR_FIELD_CSV is not set.');

projectDir = getenv('OATOF_PROJECT_ROOT');
assert(~isempty(projectDir) && isfolder(projectDir), ...
    'OATOF_PROJECT_ROOT is missing.');
addpath(projectDir);
modelPath = getenv('OATOF_COMSOL_MODEL_PATH');
assert(isfile(modelPath), 'COMSOL model is absent: %s', modelPath);

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));
try
    samples = readtable(inputCsv);
    required = {'particle_id','time_us','x_mm','y_mm','z_mm'};
    assert(all(ismember(required, samples.Properties.VariableNames)), ...
        'Sample CSV does not follow the trajectory-coordinate contract.');
    % The upstream SIMION adapter has already restricted these coordinates
    % to the accelerator PA interpolation domain.  COMSOL must evaluate the
    % exact same rows without applying a second geometric filter.
    model = mphopen(modelPath);
    coords = [samples.x_mm.'; samples.y_mm.'; samples.z_mm.'];
    [ex, ey, ez] = mphinterp(model, {'es.Ex','es.Ey','es.Ez'}, ...
        'coord', coords, 'dataset', 'dset1');
    samples.Ex_V_per_m = ex(:);
    samples.Ey_V_per_m = ey(:);
    samples.Ez_V_per_m = ez(:);
    outputDir = fileparts(outputCsv);
    if ~isfolder(outputDir), mkdir(outputDir); end
    writetable(samples, outputCsv);
    fprintf(fid, 'MODEL=%s\nINPUT_CSV=%s\nOUTPUT_CSV=%s\n', ...
        modelPath, inputCsv, outputCsv);
    fprintf(fid, 'EXPORTED_ROWS=%d\nSTATUS=PASS\n', height(samples));
catch exception
    fprintf(fid, 'STATUS=FAIL\nERROR=%s\n', ...
        getReport(exception, 'extended', 'hyperlinks', 'off'));
    rethrow(exception)
end
clear cleanup
