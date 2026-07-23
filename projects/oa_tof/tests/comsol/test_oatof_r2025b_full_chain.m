reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
testDir = fileparts(mfilename('fullpath'));
componentDir = fileparts(fileparts(testDir));
addpath(componentDir);
addpath(fullfile(componentDir, 'comsol'));
paths = oatof_paths();
modelPath = fullfile(paths.comsolFormalDir, ...
    'oa_tof__model.mph');

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));

fprintf(fid, 'MATLAB_VERSION=%s\n', version);
fprintf(fid, 'JVM=%d\n', usejava('jvm'));
import com.comsol.model.util.*
fprintf(fid, 'COMSOL_VERSION=%s\n', char(ModelUtil.getComsolVersion));
fprintf(fid, 'MODEL=%s\n', modelPath);

tLoad = tic;
model = mphload(modelPath, 'OaTofFullChainVerify');
fprintf(fid, 'LOAD_SECONDS=%.6f\n', toc(tLoad));
initialSolutions = joinJavaStrings(model.sol.tags);
fprintf(fid, 'SOLUTION_TAGS_INITIAL=%s\n', initialSolutions);
assert(model.sol('sol1').isAttached(), 'sol1 is not attached to std1.');
assert(model.sol('sol2').isAttached(), 'sol2 is not attached to std2.');

tStatic = tic;
model.study('std1').run;
fprintf(fid, 'STD1_RUN_SECONDS=%.6f\n', toc(tStatic));
solutionsAfterStatic = joinJavaStrings(model.sol.tags);
fprintf(fid, 'SOLUTION_TAGS_AFTER_STD1=%s\n', solutionsAfterStatic);
assert(strcmp(solutionsAfterStatic, initialSolutions), ...
    'std1.run generated an unexpected solver sequence.');

tParticle = tic;
model.study('std2').run;
fprintf(fid, 'STD2_RUN_SECONDS=%.6f\n', toc(tParticle));
solutionsAfterParticle = joinJavaStrings(model.sol.tags);
fprintf(fid, 'SOLUTION_TAGS_AFTER_STD2=%s\n', solutionsAfterParticle);
assert(strcmp(solutionsAfterParticle, initialSolutions), ...
    'std2.run generated an unexpected solver sequence.');

pd = mphparticle(model, 'dataset', 'pdset1');
t = pd.t;
x = squeeze(pd.p(:,:,1));
y = squeeze(pd.p(:,:,2));
z = squeeze(pd.p(:,:,3));
nParticles = size(z, 2);
expectedParticles = str2double(model.component('comp1').physics('cpt') ...
    .feature('rel1').getString('N'));
assert(nParticles == expectedParticles, ...
    'Particle count mismatch: extracted %d, expected %d.', ...
    nParticles, expectedParticles);

detectorZ = model.param.evaluate('detector_z') * 1e3;
detectorX = model.param.evaluate('detector_x') * 1e3;
detectorRadius = model.param.evaluate('detector_radius') * 1e3;
arrivals = oatof_extract_detector_arrivals( ...
    t(:),x,y,z,detectorZ,1e-3,0.5,detectorX,0,detectorRadius);
detTimes = arrivals.time_s;
detTimes(~arrivals.hit) = NaN;
zMax = max(z, [], 1);

nDetected = sum(arrivals.hit);
meanTime = mean(detTimes, 'omitnan');
stdTime = std(detTimes, 'omitnan');
fwhmFactor = 2*sqrt(2*log(2));
fwhmTime = fwhmFactor*stdTime;
resolution = meanTime / (2*fwhmTime);
stage2Penetration = max(zMax) - ...
    model.param.evaluate('L_flight') * 1e3 - 120;

fprintf(fid, 'PARTICLES=%d\n', nParticles);
fprintf(fid, 'DETECTED=%d\n', nDetected);
fprintf(fid, 'MEAN_TOF_US=%.12g\n', meanTime * 1e6);
fprintf(fid, 'STD_TOF_NS=%.12g\n', stdTime * 1e9);
fprintf(fid, 'FWHM_TOF_NS=%.12g\n', fwhmTime * 1e9);
fprintf(fid, 'RESOLUTION_R_FWHM=%.12g\n', resolution);
fprintf(fid, 'MAX_STAGE2_PENETRATION_MM=%.12g\n', stage2Penetration);
for status = unique(arrivals.status).'
    fprintf(fid, 'DETECTOR_STATUS_%s=%d\n', ...
        upper(status),sum(arrivals.status==status));
end

assert(nDetected == expectedParticles, ...
    'Only %d/%d particles reached the detector.', ...
    nDetected, expectedParticles);
assert(abs(meanTime * 1e6 - 31.44793) < 0.05, ...
    'Mean TOF moved outside the formal baseline tolerance.');
assert(resolution > 15000/fwhmFactor, ...
    'Resolution %.6g is below the accepted formal-baseline floor.', resolution);

fprintf(fid, 'STATUS=PASS\n');
clear cleanup
ModelUtil.remove('OaTofFullChainVerify');

function text = joinJavaStrings(values)
items = cell(1, length(values));
for idx = 1:length(values)
    items{idx} = char(values(idx));
end
text = strjoin(items, ',');
end
