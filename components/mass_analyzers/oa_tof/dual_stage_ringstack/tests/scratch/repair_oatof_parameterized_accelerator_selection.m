% One-time retained repair/provenance script for the 2026-07-14 formal MPH.
% It modifies and overwrites the formal model only after mesh, field,
% N=1000, solver-attachment, and persisted-state checks all pass.
reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
assert(strcmp(getenv('OATOF_ALLOW_FORMAL_REPAIR'), '1'), ...
    ['This retained repair script overwrites the formal MPH only after all ' ...
     'checks pass. Set OATOF_ALLOW_FORMAL_REPAIR=1 explicitly to rerun it.']);
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

model = mphload(modelPath, 'OaTofSelectionRepair');
initialSolutions = joinJavaStrings(model.sol.tags);
assert(strcmp(initialSolutions, 'sol1,sol2'), ...
    'Unexpected initial solver tags: %s', initialSolutions);

selection = model.component('comp1').selection('selbracket');
selection.set('xmin', 'x_accel_center-accel_shield_half');
selection.set('xmax', 'x_accel_center+accel_shield_half');
selection.set('ymin', '-accel_shield_half');
selection.set('ymax', 'accel_shield_half');
selection.set('zmin', '0');
selection.set('zmax', 'L_accel');
selection.set('condition', 'inside');
domainIds = selection.entities(3);
assert(numel(domainIds) >= 6, ...
    'Parameterized selection resolved to only %d domains.', numel(domainIds));
fprintf(fid, 'PARAMETERIZED_DOMAIN_IDS=%s\n', joinNumbers(domainIds));

mesh = model.component('comp1').mesh('mesh1');
meshTags = mesh.feature.tags;
if hasJavaTag(meshTags, 'szbracket')
    mesh.feature.remove('szbracket');
end
assert(~hasJavaTag(mesh.feature.tags, 'szbracket'), ...
    'Obsolete szbracket mesh feature was not removed.');

tMesh = tic;
mesh.run;
fprintf(fid, 'MESH_RUN_SECONDS=%.6f\n', toc(tMesh));
tStatic = tic;
model.study('std1').run;
fprintf(fid, 'STD1_RUN_SECONDS=%.6f\n', toc(tStatic));
assert(strcmp(joinJavaStrings(model.sol.tags), initialSolutions), ...
    'std1 generated an unexpected solver sequence.');

xCenterMm = model.param.evaluate('x_accel_center') * 1e3;
targetEz = (model.param.evaluate('V_repeller') - ...
    model.param.evaluate('V_grid1')) / 3e-3;
zMm = linspace(0.2, 2.8, 261);
coords = [repmat(xCenterMm, 1, numel(zMm)); zeros(1, numel(zMm)); zMm];
ezRaw = mphinterp(model, 'es.Ez', 'coord', coords, 'dataset', 'dset1');
axisRelativePct = 100 * (ezRaw-targetEz) / targetEz;

offsetMm = [-0.5, 0, 0.5];
[dx, dy, dz] = ndgrid(offsetMm, offsetMm, [1, 1.5, 2]);
releaseCoords = [xCenterMm+dx(:)'; dy(:)'; dz(:)'];
releaseEz = mphinterp(model, 'es.Ez', 'coord', releaseCoords, ...
    'dataset', 'dset1');
releaseRelativePct = 100 * (releaseEz-targetEz) / targetEz;
fprintf(fid, 'AXIS_RELATIVE_MIN_MAX_PCT=%.15g,%.15g\n', ...
    min(axisRelativePct), max(axisRelativePct));
fprintf(fid, 'RELEASE_RELATIVE_MIN_MAX_PCT=%.15g,%.15g\n', ...
    min(releaseRelativePct), max(releaseRelativePct));
assert(max(abs(axisRelativePct)) < 0.05, ...
    'Axis bracket-field deviation exceeds 0.05%%.');
assert(max(abs(releaseRelativePct)) < 0.03, ...
    'Release bracket-field deviation exceeds 0.03%%.');

tParticle = tic;
model.study('std2').run;
fprintf(fid, 'STD2_RUN_SECONDS=%.6f\n', toc(tParticle));
assert(strcmp(joinJavaStrings(model.sol.tags), initialSolutions), ...
    'std2 generated an unexpected solver sequence.');

pd = mphparticle(model, 'dataset', 'pdset1');
t = pd.t;
z = squeeze(pd.p(:,:,3));
nParticles = size(z, 2);
detectorZ = model.param.evaluate('detector_z') * 1e3;
detThreshold = detectorZ + 0.5;
wasUpThreshold = detectorZ * 2;
freezeTolerance = 2;
detTimes = nan(1, nParticles);
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
            detTimes(particle) = interpCrossingTime(t, zi, sample, detectorZ);
            detected = true;
            break
        end
    end
    if ~detected && wasUp
        nearDetector = find(abs(zi(wasUpIndex:end)-detectorZ) < ...
            freezeTolerance, 1, 'first');
        if ~isempty(nearDetector)
            sample = wasUpIndex + nearDetector - 1;
            detTimes(particle) = interpCrossingTime(t, zi, sample, detectorZ);
        end
    end
end

nDetected = sum(~isnan(detTimes));
meanTime = mean(detTimes, 'omitnan');
stdTime = std(detTimes, 'omitnan');
resolution = meanTime / (2*stdTime);
fprintf(fid, 'PARTICLES=%d\n', nParticles);
fprintf(fid, 'DETECTED=%d\n', nDetected);
fprintf(fid, 'MEAN_TOF_US=%.12g\n', meanTime*1e6);
fprintf(fid, 'STD_TOF_NS=%.12g\n', stdTime*1e9);
fprintf(fid, 'RESOLUTION_R=%.12g\n', resolution);
assert(nParticles == 1000 && nDetected == 1000, ...
    'Formal baseline detected only %d/%d particles.', nDetected, nParticles);
assert(resolution > 15000, ...
    'Formal baseline resolution %.6g is below 15000.', resolution);

model.save(modelPath);
fprintf(fid, 'MODEL_SAVED=1\n');
ModelUtil.remove('OaTofSelectionRepair');

persisted = mphload(modelPath, 'OaTofSelectionPersisted');
persistedSelection = persisted.component('comp1').selection('selbracket');
assert(strcmp(char(persistedSelection.getString('xmin')), ...
    'x_accel_center-accel_shield_half'), ...
    'Persisted xmin is not parameter-linked.');
assert(strcmp(char(persistedSelection.getString('xmax')), ...
    'x_accel_center+accel_shield_half'), ...
    'Persisted xmax is not parameter-linked.');
assert(numel(persistedSelection.entities(3)) >= 6, ...
    'Persisted accelerator selection is incomplete.');
assert(~hasJavaTag(persisted.component('comp1').mesh('mesh1').feature.tags, ...
    'szbracket'), 'Persisted model still contains szbracket.');
assert(persisted.sol('sol1').isAttached() && persisted.sol('sol2').isAttached(), ...
    'Persisted solver attachment is incomplete.');
fprintf(fid, 'PERSISTED_STATUS=PASS\n');
fprintf(fid, 'STATUS=PASS\n');
ModelUtil.remove('OaTofSelectionPersisted');
clear cleanup

function crossingTime = interpCrossingTime(t, z, index, target)
if index > 1 && z(index-1) ~= z(index)
    fraction = (target-z(index-1)) / (z(index)-z(index-1));
    crossingTime = t(index-1) + fraction*(t(index)-t(index-1));
else
    crossingTime = t(index);
end
end

function tf = hasJavaTag(values, target)
tf = false;
for index = 1:length(values)
    if strcmp(char(values(index)), target)
        tf = true;
        return
    end
end
end

function text = joinNumbers(values)
text = strjoin(string(values), ',');
end

function text = joinJavaStrings(values)
items = cell(1, length(values));
for index = 1:length(values)
    items{index} = char(values(index));
end
text = strjoin(items, ',');
end
