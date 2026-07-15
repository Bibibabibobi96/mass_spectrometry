reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
testDir = fileparts(mfilename('fullpath'));
componentDir = fileparts(fileparts(testDir));
addpath(componentDir);
paths = oatof_paths();
modelPath = fullfile(paths.comsolFormalDir, ...
    'MS_oaTOF_TwoStageRingStackReflectron_Final.mph');

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
z = squeeze(pd.p(:,:,3));
nParticles = size(z, 2);
expectedParticles = str2double(model.component('comp1').physics('cpt') ...
    .feature('rel1').getString('N'));
assert(nParticles == expectedParticles, ...
    'Particle count mismatch: extracted %d, expected %d.', ...
    nParticles, expectedParticles);

detectorZ = model.param.evaluate('detector_z') * 1e3;
detThreshold = detectorZ + 0.5;
wasUpThreshold = detectorZ * 2;
freezeTolerance = 2;
detTimes = nan(1, nParticles);
zMax = max(z, [], 1);
for particle = 1:nParticles
    zi = z(:, particle);
    wasUp = false;
    wasUpIndex = NaN;
    detected = false;
    for sample = 1:numel(zi)
        if isnan(zi(sample))
            break
        end
        if zi(sample) > wasUpThreshold && ~wasUp
            wasUp = true;
            wasUpIndex = sample;
        end
        if wasUp && zi(sample) < detThreshold
            detTimes(particle) = interpCrossingTime( ...
                t, zi, sample, detectorZ);
            detected = true;
            break
        end
    end
    if ~detected && wasUp
        nearDetector = find(abs(zi(wasUpIndex:end) - detectorZ) < ...
            freezeTolerance, 1, 'first');
        if ~isempty(nearDetector)
            sample = wasUpIndex + nearDetector - 1;
            detTimes(particle) = interpCrossingTime( ...
                t, zi, sample, detectorZ);
        end
    end
end

nDetected = sum(~isnan(detTimes));
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

function crossingTime = interpCrossingTime(t, z, index, target)
if index > 1 && z(index-1) ~= z(index)
    fraction = (target - z(index-1)) / (z(index) - z(index-1));
    crossingTime = t(index-1) + fraction * (t(index) - t(index-1));
else
    crossingTime = t(index);
end
end

function text = joinJavaStrings(values)
items = cell(1, length(values));
for idx = 1:length(values)
    items{idx} = char(values(idx));
end
text = strjoin(items, ',');
end
