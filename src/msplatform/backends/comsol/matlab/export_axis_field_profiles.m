% Export solver-comparable oa-TOF axis-field samples from the formal MPH.

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
outputCsv = getenv('OATOF_COMSOL_FIELD_CSV');
assert(~isempty(outputCsv), 'OATOF_COMSOL_FIELD_CSV is not set.');
projectDir = getenv('OATOF_PROJECT_ROOT');
contractPath = getenv('OATOF_RESOLVED_GEOMETRY_JSON');
assert(~isempty(projectDir) && isfolder(projectDir), ...
    'OATOF_PROJECT_ROOT is missing.');
assert(~isempty(contractPath) && isfile(contractPath), ...
    'OATOF_RESOLVED_GEOMETRY_JSON is missing.');
addpath(projectDir);
modelPath = getenv('OATOF_COMSOL_MODEL_PATH');
assert(~isempty(modelPath) && isfile(modelPath), ...
    'OATOF_COMSOL_MODEL_PATH is missing.');
contract = jsondecode(fileread(contractPath));
geometry = contract.geometry_mm;
source = contract.particle_source;

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, 'MODEL=%s\n', modelPath);
fprintf(fid, 'OUTPUT_CSV=%s\n', outputCsv);

try
    model = mphopen(modelPath);
    zSource = (source.center_z_mm-source.size_z_mm/2):0.01: ...
        (source.center_z_mm+source.size_z_mm/2);
    zAccelerator = (geometry.accelerator_repeller_z+0.2):0.05: ...
        (geometry.accelerator_grid2_z-0.2);
    zReflectron = (geometry.L_flight+0.25):0.25: ...
        (geometry.L_flight+geometry.L_reflectron-0.25);
    acceleratorX = contract.coordinate_convention.accelerator_axis_x;
    reflectronX = contract.coordinate_convention.reflectron_axis(1);
    [sourceV, sourceEz] = sample_profile(model, acceleratorX, zSource);
    [acceleratorV, acceleratorEz] = sample_profile(model, acceleratorX, zAccelerator);
    [reflectronV, reflectronEz] = sample_profile(model, reflectronX, zReflectron);

    result = [profile_table('accelerator_source', zSource, acceleratorX, sourceV, sourceEz); ...
        profile_table('accelerator_full', zAccelerator, acceleratorX, acceleratorV, acceleratorEz); ...
        profile_table('reflectron', zReflectron, reflectronX, reflectronV, reflectronEz)];
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
