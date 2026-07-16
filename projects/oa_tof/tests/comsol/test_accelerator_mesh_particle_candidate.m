% Test an in-memory N=100 particle candidate with a locally refined accelerator.

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
outputCsv = getenv('OATOF_COMSOL_OUTPUT_CSV');
hmaxText = getenv('OATOF_ACCELERATOR_HMAX_MM');
assert(~isempty(outputCsv), 'OATOF_COMSOL_OUTPUT_CSV is not set.');
if isempty(hmaxText), hmaxText = '0.5'; end
hmaxMm = str2double(hmaxText);
assert(isfinite(hmaxMm) && hmaxMm > 0, 'Invalid accelerator hmax.');

testDir = fileparts(mfilename('fullpath'));
projectDir = fileparts(fileparts(testDir));
addpath(projectDir);
paths = oatof_paths();
modelPath = fullfile(paths.comsolFormalDir, ...
    'MS_oaTOF_TwoStageRingStackReflectron_Final.mph');
ionTable = fullfile(paths.simionFormalDir, ...
    'oatof_comsol_524amu_gaussian_N100.ion');

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, 'MODEL=%s\nION_TABLE=%s\nOUTPUT_CSV=%s\n', ...
    modelPath, ionTable, outputCsv);
fprintf(fid, 'ACCELERATOR_HMAX_MM=%.12g\n', hmaxMm);

try
    model = mphopen(modelPath);
    mesh = model.component('comp1').mesh('mesh1');
    tag = 'szaccelconv';
    sizeFeature = mesh.feature().create(tag, 'Size');
    sizeFeature.label('DIAGNOSTIC accelerator-domain particle candidate');
    sizeFeature.selection().geom('geom1', 3);
    sizeFeature.selection().named('selbracket');
    sizeFeature.set('custom', 'on');
    sizeFeature.set('hmaxactive', true);
    sizeFeature.set('hmax', sprintf('%.12g[mm]', hmaxMm));
    tagsBefore = string(cell(mesh.feature.tags()));
    ftetIndex = find(tagsBefore == "ftet1", 1);
    assert(~isempty(ftetIndex), 'Formal mesh does not contain ftet1.');
    mesh.feature.move(tag, ftetIndex-1);
    tagsAfter = string(cell(mesh.feature.tags()));
    assert(find(tagsAfter == tag, 1) < find(tagsAfter == "ftet1", 1), ...
        'Diagnostic Size is not before ftet1.');
    fprintf(fid, 'MESH_FEATURES=%s\n', join(tagsAfter, ','));

    meshStart = tic;
    mesh.run;
    meshSeconds = toc(meshStart);
    meshInfo = mphmeshstats(model, 'mesh1');
    esStart = tic;
    model.study('std1').run;
    esSeconds = toc(esStart);
    particleStart = tic;
    model.study('std2').run;
    particleSeconds = toc(particleStart);

    ion = readmatrix(ionTable, 'FileType', 'text', 'Delimiter', ',');
    p0 = mphparticle(model, 'dataset', 'pdset1', 't', 0);
    releasedPositionMm = squeeze(p0.p);
    releasedVelocityMS = squeeze(p0.v);
    expectedPositionMm = ion(:,4:6);
    expectedSpeedMS = sqrt(2*ion(:,9)*1.602176e-19/(524*1.66053906660e-27));
    positionErrorMm = max(abs(releasedPositionMm(:)-expectedPositionMm(:)));
    speedErrorMS = max(abs(sqrt(sum(releasedVelocityMS.^2,2))-expectedSpeedMS));

    expectedTof = 31.4478763926e-6*sqrt(524/100);
    evalTimes = expectedTof + (-200e-9:0.2e-9:200e-9);
    pd = mphparticle(model, 'dataset', 'pdset1', ...
        'expr', {'qx','qy','qz'}, 't', evalTimes, 'dataonly', 'on');
    t = pd.t(:);
    x = orient_time_by_particle(squeeze(pd.d1), numel(t));
    y = orient_time_by_particle(squeeze(pd.d2), numel(t));
    z = orient_time_by_particle(squeeze(pd.d3), numel(t));
    detectorZ = mphevaluate(model, 'detector_z', 'mm');
    detectorTimes = nan(size(z,2), 1);
    detectorX = nan(size(z,2), 1);
    detectorY = nan(size(z,2), 1);
    for particle = 1:size(z,2)
        crossingIndex = find(z(:,particle) < detectorZ+0.5, 1, 'first');
        if isempty(crossingIndex), continue; end
        [detectorTimes(particle), detectorX(particle), detectorY(particle)] = ...
            interpolate_crossing(t, x(:,particle), y(:,particle), ...
            z(:,particle), crossingIndex, detectorZ);
    end
    assert(all(isfinite(detectorTimes)), 'Expected all fixed particles to hit.');
    result = table((1:size(z,2)).', detectorTimes*1e6, detectorX, detectorY, ...
        true(size(z,2),1), ion(:,4), ion(:,5), ion(:,6), ion(:,9), ...
        'VariableNames', {'Ion','TofUs','XMm','YMm','Hit', ...
        'X0Mm','Y0Mm','Z0Mm','EnergyEv'});
    outputDir = fileparts(outputCsv);
    if ~isfolder(outputDir), mkdir(outputDir); end
    writetable(result, outputCsv);

    fprintf(fid, 'MESH_ELEMENTS=%d\nMESH_SECONDS=%.6f\n', ...
        meshInfo.numelem(2), meshSeconds);
    fprintf(fid, 'ELECTROSTATICS_SECONDS=%.6f\nPARTICLE_SECONDS=%.6f\n', ...
        esSeconds, particleSeconds);
    fprintf(fid, 'MAX_T0_RELEASE_POSITION_ERROR_MM=%.12g\n', positionErrorMm);
    fprintf(fid, 'MAX_T0_RELEASE_SPEED_ERROR_M_PER_S=%.12g\n', speedErrorMS);
    fprintf(fid, 'DETECTED=%d/%d\nMEAN_TOF_US=%.12g\n', ...
        sum(isfinite(detectorTimes)), numel(detectorTimes), mean(detectorTimes)*1e6);
    fprintf(fid, 'STATUS=PASS\n');
catch exception
    fprintf(fid, 'STATUS=FAIL\nERROR=%s\n', ...
        getReport(exception, 'extended', 'hyperlinks', 'off'));
    rethrow(exception)
end
clear cleanup

function values = orient_time_by_particle(values, timeCount)
if size(values, 1) == timeCount, return; end
if size(values, 2) == timeCount, values = values.'; return; end
error('Unexpected particle array shape %dx%d for %d times.', ...
    size(values,1), size(values,2), timeCount);
end

function [crossingTime, crossingX, crossingY] = ...
    interpolate_crossing(t, x, y, z, index, target)
if index > 1 && all(isfinite([x(index-1:index); y(index-1:index); ...
        z(index-1:index)]), 'all') && z(index) ~= z(index-1)
    fraction = (target-z(index-1))/(z(index)-z(index-1));
    crossingTime = t(index-1) + fraction*(t(index)-t(index-1));
    crossingX = x(index-1) + fraction*(x(index)-x(index-1));
    crossingY = y(index-1) + fraction*(y(index)-y(index-1));
else
    crossingTime = t(index);
    crossingX = x(index);
    crossingY = y(index);
end
end
