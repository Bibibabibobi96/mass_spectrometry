% Export COMSOL E-vector values at solver-neutral accelerator sample points.

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
inputCsv = getenv('OATOF_ACCELERATOR_SAMPLE_CSV');
outputCsv = getenv('OATOF_COMSOL_VECTOR_FIELD_CSV');
assert(~isempty(inputCsv) && isfile(inputCsv), ...
    'OATOF_ACCELERATOR_SAMPLE_CSV is missing.');
assert(~isempty(outputCsv), 'OATOF_COMSOL_VECTOR_FIELD_CSV is not set.');

testDir = fileparts(mfilename('fullpath'));
projectDir = fileparts(fileparts(testDir));
addpath(projectDir);
paths = oatof_paths();
modelPath = fullfile(paths.comsolFormalDir, ...
    'MS_oaTOF_TwoStageRingStackReflectron_Final.mph');

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));
try
    samples = readtable(inputCsv);
    required = {'particle_id','time_us','x_mm','y_mm','z_mm'};
    assert(all(ismember(required, samples.Properties.VariableNames)), ...
        'Sample CSV does not follow the trajectory-coordinate contract.');
    % The accelerator PA instance ends at z=20.0 mm.  Stay 0.4 mm inside
    % both solvers' shared interpolation volume; the exit grid is at 19.83 mm.
    samples = samples(samples.time_us <= 2 & samples.z_mm <= 19.6, :);
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
