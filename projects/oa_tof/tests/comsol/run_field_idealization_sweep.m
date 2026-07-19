% Run a controlled field-idealization sweep from one saved N=100 model.
% The saved MPH already contains GUI-visible ideal_<region>_<component>
% parameters and ef1 expressions. This task changes only those parameters,
% reruns std2/sol2, and exports canonical particle tables for Python analysis.

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
modelPath = getenv('OATOF_FIELD_SWEEP_MODEL');
selectorsPath = getenv('OATOF_FIELD_SWEEP_SELECTORS');
outputDir = getenv('OATOF_FIELD_SWEEP_OUTPUT');
assert(isfile(modelPath), 'Sweep model is missing: %s', modelPath);
assert(isfile(selectorsPath), 'Selector configuration is missing: %s', selectorsPath);
if ~isfolder(outputDir), mkdir(outputDir); end

testDir = fileparts(mfilename('fullpath'));
projectRoot = fileparts(fileparts(testDir));
addpath(projectRoot);
addpath(fullfile(projectRoot, 'comsol'));

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));

configuration = jsondecode(fileread(selectorsPath));
assert(isfield(configuration, 'cases') && ~isempty(configuration.cases), ...
    'Selector configuration must contain nonempty cases.');
model = mphopen(modelPath);
massAmu = 524;
particleCount = 100;
regions = {'accel','drift','stage1','stage2'};
components = {'ex','ey','ez'};

p0 = mphparticle(model, 'dataset', 'pdset1', 't', 0);
initialPosition = squeeze(p0.p);
initialVelocity = squeeze(p0.v);
assert(size(initialPosition,1) == particleCount, ...
    'Expected %d saved particles, found %d.', particleCount, size(initialPosition,1));
initialEnergyEv = 0.5*(massAmu*1.66053906660e-27) * ...
    sum(initialVelocity.^2,2) / 1.602176634e-19;

expectedTof = model.param.evaluate('t_detector_ref');
fineStep = model.param.evaluate('cpt_dt_fine');
simulationEnd = model.param.evaluate('cpt_t_end');
arrivalTimes = expectedTof + (-300e-9:fineStep:300e-9);
extractTimes = unique([linspace(0, simulationEnd, 2001), arrivalTimes, simulationEnd]);
detectorZ = model.param.evaluate('detector_z')*1e3;
detectorXCenter = model.param.evaluate('detector_x')*1e3;

summaryRows = cell(numel(configuration.cases), 8);
for caseIndex = 1:numel(configuration.cases)
    caseConfig = configuration.cases(caseIndex);
    caseId = string(caseConfig.id);
    selector = string(caseConfig.selector);
    selection = oatof_parse_field_idealization(selector);
    for regionIndex = 1:numel(regions)
        for componentIndex = 1:numel(components)
            flag = sprintf('ideal_%s_%s', regions{regionIndex}, components{componentIndex});
            model.param.set(flag, sprintf('%d', selection.mask(regionIndex, componentIndex)));
        end
    end
    fprintf('[FIELD_SWEEP] case=%s selector=%s\n', caseId, selection.canonical);
    model.sol('sol2').clearSolutionData();
    caseTimer = tic;
    model.sol('sol2').runAll();
    solveSeconds = toc(caseTimer);

    pd = mphparticle(model, 'dataset', 'pdset1', 'expr', {'qx','qy','qz'}, ...
        't', extractTimes, 'dataonly', 'on');
    t = pd.t(:);
    x = orient_time_by_particle(squeeze(pd.d1), numel(t));
    y = orient_time_by_particle(squeeze(pd.d2), numel(t));
    z = orient_time_by_particle(squeeze(pd.d3), numel(t));
    detectorTimes = nan(particleCount,1);
    detectorX = nan(particleCount,1);
    detectorY = nan(particleCount,1);
    for particle = 1:particleCount
        lastValid = find(isfinite(z(:,particle)), 1, 'last');
        if isempty(lastValid), continue; end
        [~, turnIndex] = max(z(1:lastValid,particle));
        crossingIndex = find(z(turnIndex+1:lastValid,particle) < detectorZ+0.5, 1, 'first');
        if ~isempty(crossingIndex)
            crossingIndex = turnIndex + crossingIndex;
        else
            nearIndex = find(abs(z(turnIndex:lastValid,particle)-detectorZ) < 2, 1, 'first');
            if isempty(nearIndex), continue; end
            crossingIndex = turnIndex + nearIndex - 1;
        end
        [detectorTimes(particle),detectorX(particle),detectorY(particle)] = ...
            interpolate_crossing(t,x(:,particle),y(:,particle),z(:,particle),crossingIndex,detectorZ);
    end
    hit = isfinite(detectorTimes);
    particleTable = table((1:particleCount).', detectorTimes*1e6, hit, ...
        detectorX, detectorY, initialPosition(:,1), initialPosition(:,2), ...
        initialPosition(:,3), initialEnergyEv, ...
        'VariableNames', {'particle_id','tof_us','hit','detector_x_mm', ...
        'detector_y_mm','initial_x_mm','initial_y_mm','initial_z_mm','initial_energy_eV'});
    csvPath = fullfile(outputDir, char(caseId + "_particles.csv"));
    writetable(particleTable, csvPath);
    landingRadius = hypot(detectorX(hit)-detectorXCenter, detectorY(hit));
    summaryRows(caseIndex,:) = {char(caseId),char(selection.canonical),solveSeconds, ...
        sum(hit),mean(detectorTimes(hit))*1e6,std(detectorTimes(hit))*1e9, ...
        sqrt(mean(landingRadius.^2)),csvPath};
    fprintf(fid, 'CASE=%s SELECTOR=%s SOLVE_SECONDS=%.6f HIT=%d/%d MEAN_TOF_US=%.12g TOF_STD_NS=%.12g LANDING_RMS_MM=%.12g CSV=%s\n', ...
        caseId,selection.canonical,solveSeconds,sum(hit),particleCount, ...
        mean(detectorTimes(hit))*1e6,std(detectorTimes(hit))*1e9, ...
        sqrt(mean(landingRadius.^2)),csvPath);
end

summary = cell2table(summaryRows, 'VariableNames', ...
    {'case_id','selector','solve_seconds','detected','mean_tof_us','tof_std_ns','landing_rms_mm','particle_csv'});
writetable(summary, fullfile(outputDir, 'sweep_summary.csv'));
fprintf(fid, 'STATUS=PASS\n');
clear cleanup

function values = orient_time_by_particle(values, timeCount)
if size(values,1) == timeCount, return; end
if size(values,2) == timeCount, values = values.'; return; end
error('Unexpected particle array shape %dx%d for %d times.', size(values,1),size(values,2),timeCount);
end

function [crossingTime,crossingX,crossingY] = interpolate_crossing(t,x,y,z,index,target)
if index > 1 && all(isfinite([x(index-1:index);y(index-1:index);z(index-1:index)]),'all') ...
        && z(index) ~= z(index-1)
    fraction = (target-z(index-1))/(z(index)-z(index-1));
    crossingTime = t(index-1)+fraction*(t(index)-t(index-1));
    crossingX = x(index-1)+fraction*(x(index)-x(index-1));
    crossingY = y(index-1)+fraction*(y(index)-y(index-1));
else
    crossingTime = t(index); crossingX = x(index); crossingY = y(index);
end
end
