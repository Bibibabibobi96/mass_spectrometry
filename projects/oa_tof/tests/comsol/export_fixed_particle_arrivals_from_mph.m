% Export COMSOL fixed-particle detector arrivals without doing peak analysis.
% Solver-independent FWHM, R, peak-shape and bootstrap calculations belong to
% analysis/reference_analysis.py and config/analysis_contract.json.

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
testDir = fileparts(mfilename('fullpath'));
projectDir = fileparts(fileparts(testDir));
addpath(projectDir);
paths = oatof_paths();
import com.comsol.model.util.*

modelPath = getenv('OATOF_COMSOL_MODEL_PATH');
if isempty(modelPath)
    error('OATOF_COMSOL_MODEL_PATH is required; select a source runs/<run_id>/comsol model.');
end
ionTable = getenv('OATOF_ION_TABLE');
if isempty(ionTable)
    ionTable = fullfile(paths.simionFormalDir, ...
        'oatof_comsol_524amu_gaussian_N100.ion');
end
outputCsv = getenv('OATOF_COMSOL_OUTPUT_CSV');
if isempty(outputCsv)
    error('OATOF_COMSOL_OUTPUT_CSV is required; write inside the current run results directory.');
end
assert(isfile(modelPath), 'COMSOL MPH not found: %s', modelPath);
assert(isfile(ionTable), 'Fixed ION table not found: %s', ionTable);
outputDir = fileparts(outputCsv);
if ~isfolder(outputDir), mkdir(outputDir); end

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, 'MODEL=%s\n', modelPath);

try
    model = mphopen(modelPath);
    ion = readmatrix(ionTable, 'FileType', 'text', 'Delimiter', ',');
    p0 = mphparticle(model, 'dataset', 'pdset1', 't', 0);
    releasedPositionMm = squeeze(p0.p);
    releasedVelocityMS = squeeze(p0.v);
    expectedPositionMm = ion(:,4:6);
    expectedSpeedMS = sqrt(2*ion(:,9)*1.602176e-19/(524*1.66053906660e-27));
    positionErrorMm = max(abs(releasedPositionMm(:)-expectedPositionMm(:)));
    speedErrorMS = max(abs(sqrt(sum(releasedVelocityMS.^2,2))-expectedSpeedMS));

    expectedTof = 31.4478763926e-6*sqrt(524/100);
    fineStep = 0.2e-9;
    evalTimes = expectedTof + (-200e-9:fineStep:200e-9);
    pd = mphparticle(model, 'dataset', 'pdset1', 'expr', {'qx','qy','qz'}, ...
        't', evalTimes, 'dataonly', 'on');
    t = pd.t(:);
    x = orient_time_by_particle(squeeze(pd.d1), numel(t));
    y = orient_time_by_particle(squeeze(pd.d2), numel(t));
    z = orient_time_by_particle(squeeze(pd.d3), numel(t));
    detectorZ = mphevaluate(model, 'detector_z', 'mm');
    detectorThreshold = detectorZ + 0.5;
    particleCount = size(z, 2);
    detectorTimes = nan(particleCount, 1);
    detectorX = nan(particleCount, 1);
    detectorY = nan(particleCount, 1);
    for particle = 1:particleCount
        crossingIndex = find(z(:,particle) < detectorThreshold, 1, 'first');
        if ~isempty(crossingIndex)
            [detectorTimes(particle), detectorX(particle), detectorY(particle)] = ...
                interpolate_crossing(t, x(:,particle), y(:,particle), ...
                z(:,particle), crossingIndex, detectorZ);
        end
    end
    assert(all(isfinite(detectorTimes)), ...
        'Expected all fixed particles to hit the detector.');
    writetable(table((1:particleCount).', detectorTimes*1e6, detectorX, detectorY, ...
        'VariableNames', {'Ion','TofUs','XMm','YMm'}), outputCsv);

    fprintf(fid, 'OUTPUT_CSV=%s\n', outputCsv);
    fprintf(fid, 'MAX_T0_RELEASE_POSITION_ERROR_MM=%.12g\n', positionErrorMm);
    fprintf(fid, 'MAX_T0_RELEASE_SPEED_ERROR_M_PER_S=%.12g\n', speedErrorMS);
    fprintf(fid, 'DETECTED=%d/%d\n', sum(isfinite(detectorTimes)), particleCount);
    fprintf(fid, 'MEAN_TOF_US=%.12g\n', mean(detectorTimes)*1e6);
    fprintf(fid, 'ANALYSIS_OWNER=Python_3.11_reference_analysis.py\n');
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
