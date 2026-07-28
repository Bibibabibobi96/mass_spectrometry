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
    detectorXCenter = mphevaluate(model, 'detector_x', 'mm');
    detectorRadius = mphevaluate(model, 'detector_radius', 'mm');
    arrivals = oatof_extract_detector_arrivals( ...
        t,x,y,z,detectorZ,1e-3,0.5,detectorXCenter,0,detectorRadius);
    detectorTimes = arrivals.time_s;
    particleCount = numel(detectorTimes);
    assert(all(arrivals.hit), ...
        'Expected all fixed particles to hit the detector.');
    writetable(table((1:particleCount).', detectorTimes*1e6, ...
        arrivals.x_mm, arrivals.y_mm, arrivals.hit, arrivals.status, ...
        arrivals.radius_mm, 'VariableNames', ...
        {'Ion','TofUs','XMm','YMm','Hit','Status','DetectorRadiusMm'}), outputCsv);

    fprintf(fid, 'OUTPUT_CSV=%s\n', outputCsv);
    fprintf(fid, 'MAX_T0_RELEASE_POSITION_ERROR_MM=%.12g\n', positionErrorMm);
    fprintf(fid, 'MAX_T0_RELEASE_SPEED_ERROR_M_PER_S=%.12g\n', speedErrorMS);
    fprintf(fid, 'DETECTED=%d/%d\n', sum(arrivals.hit), particleCount);
    fprintf(fid, 'MEAN_TOF_US=%.12g\n', mean(detectorTimes(arrivals.hit))*1e6);
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
