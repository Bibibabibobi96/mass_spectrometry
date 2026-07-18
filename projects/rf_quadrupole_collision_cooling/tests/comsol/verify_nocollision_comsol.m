reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
testDir = fileparts(mfilename('fullpath'));
projectRoot = fileparts(fileparts(testDir));
addpath(projectRoot);
paths = rf_quadrupole_paths();
contract = load_rf_quadrupole_contract();
interface = jsondecode(fileread(fullfile(projectRoot,'config','interface_contract.json')));
g = contract.geometry_mm;
modelPath = getenv('RFQUAD_COMSOL_MODEL_PATH');
assert(~isempty(modelPath) && isfile(modelPath), ...
    'RFQUAD_COMSOL_MODEL_PATH must name an existing candidate MPH.');
expectedParticles = str2double(getenv('RFQUAD_EXPECTED_PARTICLES'));
expectedHits = str2double(getenv('RFQUAD_EXPECTED_HITS'));
expectedRfPeakV = str2double(getenv('RFQUAD_EXPECTED_RF_PEAK_V'));
expectedFrequencyHz = str2double(getenv('RFQUAD_EXPECTED_FREQUENCY_HZ'));
assert(all(isfinite([expectedParticles,expectedHits,expectedRfPeakV,expectedFrequencyHz])), ...
    'Expected GUI verification values are missing.');

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));

import com.comsol.model.util.*
fprintf(fid, 'MATLAB_VERSION=%s\n', version);
fprintf(fid, 'COMSOL_VERSION=%s\n', char(ModelUtil.getComsolVersion));
fprintf(fid, 'MODEL=%s\n', modelPath);
model = mphload(modelPath, 'RFQuadTransportGuiVerify');

assert(abs(model.param.evaluate('r0')*1e3 - g.field_radius_r0) < 1e-9, ...
    'Persisted r0 is not the SIMION reference value.');
assert(abs(model.param.evaluate('r_rod')*1e3 - g.rod_radius) < 1e-9, ...
    'Persisted rod radius is not the SIMION reference value.');
assert(abs(model.param.evaluate('L_rod')*1e3 - g.rod_length) < 1e-9, ...
    'Persisted rod length is not the SIMION reference value.');
assert(abs(model.param.evaluate('V_rf') - expectedRfPeakV) < 1e-8, ...
    'Persisted RF amplitude moved from the transport contract.');
assert(abs(model.param.evaluate('f_rf') - expectedFrequencyHz) < 1e-6, ...
    'Persisted RF frequency moved from the transport contract.');
assert(abs(model.param.evaluate('z_rod_exit')*1e3 - interface.planes.rod_exit.z_mm) < 1e-9, ...
    'Persisted rod-exit plane moved from the interface contract.');
assert(abs(model.param.evaluate('z_handoff')*1e3 - interface.planes.handoff.z_mm) < 1e-9, ...
    'Persisted handoff plane moved from the interface contract.');
assert(abs(model.param.evaluate('z_acceptance')*1e3 - interface.planes.acceptance_detector.z_mm) < 1e-9, ...
    'Persisted acceptance plane moved from the interface contract.');

cpt = model.component('comp1').physics('cpt');
featureTags = cell(cpt.feature.tags());
releaseTags = featureTags(startsWith(featureTags, 'rel'));
assert(numel(releaseTags) == expectedParticles, 'GUI-visible release-node count differs from the run config.');
assert(~any(contains(lower(string(featureTags)), 'coll')), ...
    'A collision feature is present in the no-collision candidate.');
assert(any(strcmp(featureTags, 'ef1')), 'GUI-visible RF Electric Force is absent.');
assert(numel(model.component('comp1').selection('sel_vac').entities()) > 0, ...
    'Persisted vacuum selection is empty.');
exportTags = cell(model.result.export.tags());
assert(any(strcmp(exportTags, 'exp_phase_raw')), ...
    'GUI-visible raw particle phase-space export is absent.');

initialSolutions = joinJavaStrings(model.sol.tags);
assert(model.sol('sol1').isAttached(), 'sol1 is not attached to std1.');
assert(model.sol('sol2').isAttached(), 'sol2 is not attached to std2.');
fprintf(fid, 'SOLUTION_TAGS_INITIAL=%s\n', initialSolutions);

tStatic = tic;
model.study('std1').run;
fprintf(fid, 'STD1_GUI_COMPUTE_SECONDS=%.6f\n', toc(tStatic));
afterStatic = joinJavaStrings(model.sol.tags);
assert(strcmp(afterStatic, initialSolutions), ...
    'std1 GUI Compute generated an unexpected solver sequence.');

tParticle = tic;
model.study('std2').run;
fprintf(fid, 'STD2_GUI_COMPUTE_SECONDS=%.6f\n', toc(tParticle));
afterParticle = joinJavaStrings(model.sol.tags);
assert(strcmp(afterParticle, initialSolutions), ...
    'std2 GUI Compute generated an unexpected solver sequence.');

pd = mphparticle(model, 'dataset', 'pdset1');
x = squeeze(pd.p(:,:,1));
y = squeeze(pd.p(:,:,2));
z = squeeze(pd.p(:,:,3));
radial = sqrt(x.^2 + y.^2);
assert(size(z,2) == expectedParticles, 'GUI Compute did not preserve the configured particle source.');
detectorZ = interface.planes.acceptance_detector.z_mm;
detectorRadius = g.detector_radius;
hits = false(1, size(z,2));
arrival = nan(1, size(z,2));
for particle = 1:size(z,2)
    sample = find(z(:,particle) >= detectorZ-1e-6, 1, 'first');
    if ~isempty(sample) && radial(sample,particle) <= detectorRadius
        hits(particle) = true;
        arrival(particle) = pd.t(sample)*1e6;
    end
end
fprintf(fid, 'PARTICLES=%d\n', size(z,2));
fprintf(fid, 'HITS=%d\n', sum(hits));
fprintf(fid, 'TRANSMISSION=%.12g\n', mean(hits));
fprintf(fid, 'MEAN_DETECTOR_TIME_US=%.12g\n', mean(arrival,'omitnan'));
fprintf(fid, 'Q_MATHIEU=%.12g\n', mphglobal(model,'q_mathieu','dataset','dset1'));
assert(sum(hits) == expectedHits, 'GUI Compute hit count moved from the saved candidate result.');

fprintf(fid, 'STATUS=PASS\n');
clear cleanup
ModelUtil.remove('RFQuadTransportGuiVerify');

function text = joinJavaStrings(values)
items = cell(1, length(values));
for idx = 1:length(values)
    items{idx} = char(values(idx));
end
text = strjoin(items, ',');
end
