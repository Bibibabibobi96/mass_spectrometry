% Test local COMSOL accelerator mesh sizes without modifying the formal MPH.

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
inputCsv = getenv('OATOF_ACCELERATOR_SAMPLE_CSV');
outputCsv = getenv('OATOF_COMSOL_MESH_SCAN_CSV');
hmaxText = getenv('OATOF_ACCELERATOR_HMAX_MM');
assert(~isempty(inputCsv) && isfile(inputCsv), ...
    'OATOF_ACCELERATOR_SAMPLE_CSV is missing.');
assert(~isempty(outputCsv), 'OATOF_COMSOL_MESH_SCAN_CSV is not set.');
if isempty(hmaxText), hmaxText = '2,1'; end
hmaxValues = str2double(split(string(hmaxText), ','));
assert(all(isfinite(hmaxValues) & hmaxValues > 0), ...
    'OATOF_ACCELERATOR_HMAX_MM must be a positive comma-separated list.');

testDir = fileparts(mfilename('fullpath'));
projectDir = fileparts(fileparts(testDir));
addpath(projectDir);
paths = oatof_paths();
modelPath = fullfile(paths.comsolFormalDir, ...
        'oa_tof__model.mph');

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, 'MODEL=%s\nINPUT_CSV=%s\nOUTPUT_CSV=%s\n', ...
    modelPath, inputCsv, outputCsv);
fprintf(fid, 'HMAX_MM=%s\n', join(string(hmaxValues), ','));

try
    samples = readtable(inputCsv);
    required = {'particle_id','time_us','x_mm','y_mm','z_mm'};
    assert(all(ismember(required, samples.Properties.VariableNames)), ...
        'Sample CSV does not follow the trajectory-coordinate contract.');
    samples = samples(samples.time_us <= 2 & samples.z_mm <= 19.6, :);
    coords = [samples.x_mm.'; samples.y_mm.'; samples.z_mm.'];
    model = mphopen(modelPath);
    mesh = model.component('comp1').mesh('mesh1');
    tag = 'szaccelconv';
    sizeFeature = mesh.feature().create(tag, 'Size');
    sizeFeature.label('DIAGNOSTIC accelerator-domain convergence mesh');
    sizeFeature.selection().geom('geom1', 3);
    sizeFeature.selection().named('selbracket');
    sizeFeature.set('custom', 'on');
    sizeFeature.set('hmaxactive', true);
    % Mesh features execute in sequence. A Size appended after FreeTet is
    % GUI-visible but does not control that tetrahedralization. Move this
    % diagnostic Size immediately before ftet1 and record the order so a
    % silent no-op cannot be mistaken for convergence.
    tagsBefore = string(cell(mesh.feature.tags()));
    ftetIndex = find(tagsBefore == "ftet1", 1);
    assert(~isempty(ftetIndex), 'Formal mesh does not contain ftet1.');
    mesh.feature.move(tag, ftetIndex-1);
    tagsAfter = string(cell(mesh.feature.tags()));
    diagnosticIndex = find(tagsAfter == tag, 1);
    ftetIndexAfter = find(tagsAfter == "ftet1", 1);
    assert(diagnosticIndex < ftetIndexAfter, ...
        'Diagnostic Size is not before ftet1: %s', join(tagsAfter, ','));
    fprintf(fid, 'MESH_FEATURES_BEFORE=%s\n', join(tagsBefore, ','));
    fprintf(fid, 'MESH_FEATURES_AFTER=%s\n', join(tagsAfter, ','));

    combined = table();
    for hmaxMm = reshape(hmaxValues, 1, [])
        sizeFeature.set('hmax', sprintf('%.12g[mm]', hmaxMm));
        meshStart = tic;
        mesh.run;
        meshSeconds = toc(meshStart);
        meshInfo = mphmeshstats(model, 'mesh1');
        solveStart = tic;
        model.study('std1').run;
        solveSeconds = toc(solveStart);
        [ex, ey, ez] = mphinterp(model, {'es.Ex','es.Ey','es.Ez'}, ...
            'coord', coords, 'dataset', 'dset1');
        variant = repmat("accelerator_hmax_" + replace(string(hmaxMm), '.', 'p') + "mm", ...
            height(samples), 1);
        meshElements = repmat(meshInfo.numelem(2), height(samples), 1);
        hmaxColumn = repmat(hmaxMm, height(samples), 1);
        rows = [table(variant, hmaxColumn, meshElements), samples, ...
            table(ex(:), ey(:), ez(:), 'VariableNames', ...
            {'Ex_V_per_m','Ey_V_per_m','Ez_V_per_m'})];
        combined = [combined; rows]; %#ok<AGROW>
        fprintf(fid, 'VARIANT=%.12g mm MESH_ELEMENTS=%d MESH_SECONDS=%.6f SOLVE_SECONDS=%.6f\n', ...
            hmaxMm, meshInfo.numelem(2), meshSeconds, solveSeconds);
    end
    outputDir = fileparts(outputCsv);
    if ~isfolder(outputDir), mkdir(outputDir); end
    writetable(combined, outputCsv);
    fprintf(fid, 'EXPORTED_ROWS=%d\nSTATUS=PASS\n', height(combined));
catch exception
    fprintf(fid, 'STATUS=FAIL\nERROR=%s\n', ...
        getReport(exception, 'extended', 'hyperlinks', 'off'));
    rethrow(exception)
end
clear cleanup
