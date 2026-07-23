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
regions = {'accel','drift','stage1','stage2'};
components = {'ex','ey','ez'};

p0 = mphparticle(model, 'dataset', 'pdset1', 't', 0);
initialPosition = squeeze(p0.p);
initialVelocity = squeeze(p0.v);
particleCount = size(initialPosition,1);
massAmu = model.param.evaluate('ion_mass_amu');
if isfield(configuration,'particle_count')
    assert(particleCount==configuration.particle_count, ...
        'Configured particle count %d does not match saved solution %d.', ...
        configuration.particle_count,particleCount);
end
if isfield(configuration,'mass_amu')
    assert(abs(massAmu-configuration.mass_amu)<1e-9, ...
        'Configured mass %.12g does not match saved model %.12g.', ...
        configuration.mass_amu,massAmu);
end
initialEnergyEv = 0.5*(massAmu*1.66053906660e-27) * ...
    sum(initialVelocity.^2,2) / 1.602176634e-19;

expectedTof = model.param.evaluate('t_detector_ref');
fineStep = model.param.evaluate('cpt_dt_fine');
simulationEnd = model.param.evaluate('cpt_t_end');
arrivalTimes = expectedTof + (-300e-9:fineStep:300e-9);
extractTimes = unique([linspace(0, simulationEnd, 2001), arrivalTimes, simulationEnd]);
detectorZ = model.param.evaluate('detector_z')*1e3;
detectorXCenter = model.param.evaluate('detector_x')*1e3;
detectorRadius = model.param.evaluate('detector_radius')*1e3;

summaryRows = cell(numel(configuration.cases), 11);
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
    arrivals = oatof_extract_detector_arrivals( ...
        t,x,y,z,detectorZ,1e-3,0.5,detectorXCenter,0,detectorRadius);
    detectorTimes = arrivals.time_s;
    detectorX = arrivals.x_mm;
    detectorY = arrivals.y_mm;
    hit = arrivals.hit;
    particleTable = table((1:particleCount).', detectorTimes*1e6, hit, ...
        arrivals.status, detectorX, detectorY, arrivals.radius_mm, ...
        initialPosition(:,1), initialPosition(:,2), ...
        initialPosition(:,3), initialEnergyEv, ...
        'VariableNames', {'particle_id','tof_us','hit','status','detector_x_mm', ...
        'detector_y_mm','detector_radius_mm','initial_x_mm','initial_y_mm', ...
        'initial_z_mm','initial_energy_eV'});
    csvPath = fullfile(outputDir, char(caseId + "_particles.csv"));
    writetable(particleTable, csvPath);
    landingRadius = hypot(detectorX(hit)-detectorXCenter, detectorY(hit));
    eventCounts = groupsummary(table(arrivals.event),'Var1');
    eventSummary = strjoin(eventCounts.Var1+"="+string(eventCounts.GroupCount),';');
    summaryRows(caseIndex,:) = {char(caseId),char(selection.canonical),solveSeconds, ...
        sum(hit),mean(detectorTimes(hit))*1e6,std(detectorTimes(hit))*1e9, ...
        sqrt(mean(landingRadius.^2)),csvPath,particleCount,massAmu,char(eventSummary)};
    fprintf(fid, 'CASE=%s SELECTOR=%s SOLVE_SECONDS=%.6f HIT=%d/%d MEAN_TOF_US=%.12g TOF_STD_NS=%.12g LANDING_RMS_MM=%.12g EVENTS=%s CSV=%s\n', ...
        caseId,selection.canonical,solveSeconds,sum(hit),particleCount, ...
        mean(detectorTimes(hit))*1e6,std(detectorTimes(hit))*1e9, ...
        sqrt(mean(landingRadius.^2)),eventSummary,csvPath);
end

summary = cell2table(summaryRows, 'VariableNames', ...
    {'case_id','selector','solve_seconds','detected','mean_tof_us','tof_std_ns', ...
     'landing_rms_mm','particle_csv','particle_count','mass_amu','event_summary'});
writetable(summary, fullfile(outputDir, 'sweep_summary.csv'));
fprintf(fid, 'STATUS=PASS\n');
clear cleanup

function values = orient_time_by_particle(values, timeCount)
if size(values,1) == timeCount, return; end
if size(values,2) == timeCount, values = values.'; return; end
error('Unexpected particle array shape %dx%d for %d times.', size(values,1),size(values,2),timeCount);
end
