reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
testDir = fileparts(mfilename('fullpath'));
projectDir = fileparts(fileparts(testDir));
addpath(projectDir);
paths = oatof_paths();

modelPath = fullfile(paths.comsolCandidateDir, ...
    'MS_oaTOF_TwoStageRingStackReflectron_Candidate_524amu_FixedN100_real_dt0.2ns.mph');
ionTable = fullfile(paths.simionFormalDir, 'oatof_comsol_524amu_gaussian_N100.ion');
simionCsv = fullfile(paths.artifactRoot, 'runs', ...
    'simion_comsol_fixed_particle_closure', '2026-07-15', ...
    'simion_real_fixedN100_particles.csv');
outputCsv = fullfile(paths.artifactRoot, 'runs', ...
    'comsol_fixed_particle_closure', '2026-07-15', ...
    'candidate_524amu_fixedN100_real_dt0p2ns_particles.csv');
assert(isfile(modelPath), 'Candidate MPH not found: %s', modelPath);
assert(isfile(ionTable), 'Fixed ION table not found: %s', ionTable);
assert(isfile(simionCsv), 'SIMION particle CSV not found: %s', simionCsv);

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
    pd = mphparticle(model, 'dataset', 'pdset1', 'expr', {'qz'}, ...
        't', evalTimes, 'dataonly', 'on');
    z = squeeze(pd.d1);
    t = pd.t(:);
    detectorZ = mphevaluate(model, 'detector_z', 'mm');
    detectorThreshold = detectorZ + 0.5;
    nP = size(z, 2);
    detTimes = nan(nP, 1);
    for ion = 1:nP
        k = find(z(:,ion) < detectorThreshold, 1, 'first');
        if ~isempty(k)
            detTimes(ion) = interpolate_crossing(t, z(:,ion), k, detectorZ);
        end
    end
    assert(all(isfinite(detTimes)), 'Expected all fixed particles to hit the detector.');
    writetable(table((1:nP).', detTimes*1e6, ...
        'VariableNames', {'Ion','TofUs'}), outputCsv);

    [comsolFwhm, comsolR] = direct_mass_fwhm(detTimes, 524);
    simion = readtable(simionCsv, 'VariableNamingRule', 'preserve');
    simionTimes = double(simion.TofUs(:))*1e-6;
    assert(numel(simionTimes) == nP, 'SIMION and COMSOL particle counts differ.');
    [simionFwhm, simionR] = direct_mass_fwhm(simionTimes, 524);

    rng(20260715, 'twister');
    nBoot = 5000;
    relativeDifference = nan(nBoot, 1);
    for b = 1:nBoot
        idx = randi(nP, nP, 1);
        [~, rc] = direct_mass_fwhm(detTimes(idx), 524);
        [~, rs] = direct_mass_fwhm(simionTimes(idx), 524);
        relativeDifference(b) = abs(rc-rs)/rs*100;
    end
    relativeDifference = relativeDifference(isfinite(relativeDifference));
    ci = prctile(relativeDifference, [2.5 50 97.5]);

    fprintf(fid, 'OUTPUT_CSV=%s\n', outputCsv);
    fprintf(fid, 'MAX_T0_RELEASE_POSITION_ERROR_MM=%.12g\n', positionErrorMm);
    fprintf(fid, 'MAX_T0_RELEASE_SPEED_ERROR_M_PER_S=%.12g\n', speedErrorMS);
    fprintf(fid, 'DETECTED=%d/%d\n', sum(isfinite(detTimes)), nP);
    fprintf(fid, 'COMSOL_MEAN_TOF_US=%.12g\n', mean(detTimes)*1e6);
    fprintf(fid, 'COMSOL_MASS_FWHM_DA=%.12g\n', comsolFwhm);
    fprintf(fid, 'COMSOL_R_DIRECT=%.12g\n', comsolR);
    fprintf(fid, 'SIMION_MASS_FWHM_DA=%.12g\n', simionFwhm);
    fprintf(fid, 'SIMION_R_DIRECT=%.12g\n', simionR);
    fprintf(fid, 'OBSERVED_R_DIFFERENCE_PERCENT=%.12g\n', abs(comsolR-simionR)/simionR*100);
    fprintf(fid, 'PAIRED_BOOTSTRAP_R_DIFFERENCE_PERCENT_P2P5=%.12g\n', ci(1));
    fprintf(fid, 'PAIRED_BOOTSTRAP_R_DIFFERENCE_PERCENT_MEDIAN=%.12g\n', ci(2));
    fprintf(fid, 'PAIRED_BOOTSTRAP_R_DIFFERENCE_PERCENT_P97P5=%.12g\n', ci(3));
    fprintf(fid, 'STATUS=PASS\n');
catch exception
    fprintf(fid, 'STATUS=FAIL\nERROR=%s\n', ...
        getReport(exception, 'extended', 'hyperlinks', 'off'));
    rethrow(exception)
end
clear cleanup

function tc = interpolate_crossing(t, z, k, target)
if k > 1 && isfinite(z(k-1)) && isfinite(z(k)) && z(k) ~= z(k-1)
    fraction = (target-z(k-1))/(z(k)-z(k-1));
    tc = t(k-1) + fraction*(t(k)-t(k-1));
else
    tc = t(k);
end
end

function [massFwhm, resolution] = direct_mass_fwhm(tof, mass)
tof = double(tof(:));
apparentMass = mass*(tof./mean(tof)).^2;
sigma = std(apparentMass);
span = max(apparentMass)-min(apparentMass);
padding = max([0.20*span; 4*sigma; 1e-6]);
grid = linspace(min(apparentMass)-padding, max(apparentMass)+padding, 1001);
bandwidth = max(1.06*sigma*numel(apparentMass)^(-1/5), 1e-6);
density = mean(exp(-0.5*((grid(:)-apparentMass(:).')/bandwidth).^2), 2) ...
    ./ (sqrt(2*pi)*bandwidth);
[peak, peakIndex] = max(density);
halfMaximum = peak/2;
leftIndex = find(density(1:peakIndex) < halfMaximum, 1, 'last');
rightOffset = find(density(peakIndex:end) < halfMaximum, 1, 'first');
if isempty(leftIndex) || isempty(rightOffset)
    massFwhm = NaN;
    resolution = NaN;
    return
end
rightIndex = peakIndex + rightOffset - 1;
leftMass = interp1(density(leftIndex:leftIndex+1), ...
    grid(leftIndex:leftIndex+1), halfMaximum, 'linear');
rightMass = interp1(density(rightIndex-1:rightIndex), ...
    grid(rightIndex-1:rightIndex), halfMaximum, 'linear');
massFwhm = rightMass-leftMass;
resolution = mass/massFwhm;
end
