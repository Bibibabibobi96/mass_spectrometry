% Export solver-comparable oa-TOF axis-field samples from the formal MPH.

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
outputCsv = getenv('OATOF_COMSOL_FIELD_CSV');
assert(~isempty(outputCsv), 'OATOF_COMSOL_FIELD_CSV is not set.');
testDir = fileparts(mfilename('fullpath'));
projectDir = fileparts(fileparts(testDir));
addpath(projectDir);
paths = oatof_paths();
modelPath = fullfile(paths.comsolFormalDir, ...
    'oa_tof__model.mph');

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, 'MODEL=%s\n', modelPath);
fprintf(fid, 'OUTPUT_CSV=%s\n', outputCsv);

try
    model = mphopen(modelPath);
    zSource = 0.2:0.01:2.8;
    zAccelerator = 3.2:0.05:19.6;
    zReflectron = 620.08:0.25:826.58;
    [sourceV, sourceEz] = sample_profile(model, -48.8, zSource);
    [acceleratorV, acceleratorEz] = sample_profile(model, -48.8, zAccelerator);
    [reflectronV, reflectronEz] = sample_profile(model, 0, zReflectron);

    result = [profile_table('accelerator_source', zSource, -48.8, sourceV, sourceEz); ...
        profile_table('accelerator_full', zAccelerator, -48.8, acceleratorV, acceleratorEz); ...
        profile_table('reflectron', zReflectron, 0, reflectronV, reflectronEz)];
    outputDir = fileparts(outputCsv);
    if ~isfolder(outputDir), mkdir(outputDir); end
    writetable(result, outputCsv);
    fprintf(fid, 'SOURCE_POINTS=%d\n', numel(zSource));
    fprintf(fid, 'ACCELERATOR_POINTS=%d\n', numel(zAccelerator));
    fprintf(fid, 'REFLECTRON_POINTS=%d\n', numel(zReflectron));
    fprintf(fid, 'SOURCE_EZ_MIN_MAX_V_PER_M=%.15g,%.15g\n', min(sourceEz), max(sourceEz));
    fprintf(fid, 'STATUS=PASS\n');
catch exception
    fprintf(fid, 'STATUS=FAIL\nERROR=%s\n', ...
        getReport(exception, 'extended', 'hyperlinks', 'off'));
    rethrow(exception)
end
clear cleanup

function [potentialV, ezVpm] = sample_profile(model, xMm, zMm)
coords = [repmat(xMm, 1, numel(zMm)); zeros(1, numel(zMm)); zMm];
[potentialV, ezVpm] = mphinterp(model, {'V', 'es.Ez'}, ...
    'coord', coords, 'dataset', 'dset1');
potentialV = potentialV(:);
ezVpm = ezVpm(:);
end

function result = profile_table(regionName, zMm, xMm, potentialV, ezVpm)
count = numel(zMm);
result = table(repmat(string(regionName), count, 1), (1:count).', ...
    repmat(xMm, count, 1), zeros(count, 1), zMm(:), potentialV, ezVpm, ...
    'VariableNames', {'region','sample_index','x_mm','y_mm','z_mm','potential_V','Ez_V_per_m'});
end
