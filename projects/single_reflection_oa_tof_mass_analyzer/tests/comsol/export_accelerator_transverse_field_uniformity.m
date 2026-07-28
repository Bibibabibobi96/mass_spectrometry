% Export systematic transverse accelerator-field profiles from a saved solution.

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
outputCsv = getenv('OATOF_TRANSVERSE_FIELD_CSV');
projectRoot = getenv('OATOF_PROJECT_ROOT');
modelPath = getenv('OATOF_COMSOL_MODEL_PATH');
assert(~isempty(outputCsv), 'OATOF_TRANSVERSE_FIELD_CSV is required.');
assert(~isempty(projectRoot) && isfolder(projectRoot), 'OATOF_PROJECT_ROOT is invalid.');
assert(~isempty(modelPath) && isfile(modelPath), 'OATOF_COMSOL_MODEL_PATH is invalid.');

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));
try
    baseline = jsondecode(fileread(fullfile(projectRoot, 'config', 'baseline.json')));
    model = mphopen(modelPath);
    axisX = baseline.coordinate_convention.accelerator_axis_x;
    g = baseline.geometry_mm;
    positiveY = unique([0:0.25:3.5, 3.6]); %#ok<NBRAK2>
    yOffsets = [-fliplr(positiveY(2:end)), positiveY];
    zStage1 = linspace(g.accelerator_repeller_z + 0.1, g.accelerator_grid1_z - 0.1, 29);
    zStage2 = linspace(g.accelerator_grid1_z + 0.1, g.accelerator_grid2_z - 0.1, 69);
    zSamples = [zStage1, zStage2];
    region = [repmat("stage1", 1, numel(zStage1)), repmat("stage2", 1, numel(zStage2))];

    nY = numel(yOffsets);
    nZ = numel(zSamples);
    x = repmat(axisX, nY*nZ, 1);
    y = repelem(yOffsets(:), nZ);
    z = repmat(zSamples(:), nY, 1);
    sampleRegion = repmat(region(:), nY, 1);
    coords = [x.'; y.'; z.'];
    [ex, ey, ez, potential] = mphinterp(model, {'es.Ex','es.Ey','es.Ez','V'}, ...
        'coord', coords, 'dataset', 'dset1', 'matherr', 'on');
    samples = table(x, y, z, sampleRegion, ex(:), ey(:), ez(:), potential(:), ...
        'VariableNames', {'x_mm','y_mm','z_mm','region','Ex_V_per_m','Ey_V_per_m','Ez_V_per_m','potential_V'});
    outputDir = fileparts(outputCsv);
    if ~isfolder(outputDir), mkdir(outputDir); end
    writetable(samples, outputCsv);
    fprintf(fid, 'MODEL=%s\nOUTPUT=%s\nY_COUNT=%d\nZ_COUNT=%d\nROWS=%d\nSTATUS=PASS\n', ...
        modelPath, outputCsv, nY, nZ, height(samples));
catch exception
    fprintf(fid, 'STATUS=FAIL\nERROR=%s\n', ...
        getReport(exception, 'extended', 'hyperlinks', 'off'));
    rethrow(exception)
end
clear cleanup
