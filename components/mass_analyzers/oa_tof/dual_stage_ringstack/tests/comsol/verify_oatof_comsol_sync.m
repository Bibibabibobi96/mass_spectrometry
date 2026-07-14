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
model = mphload(modelPath, 'OaTofSyncVerify');
fprintf(fid, 'LOAD_SECONDS=%.6f\n', toc(tLoad));

expected = {
    'x_accel_center',        -48.80e-3;
    'L_accel',                19.83e-3;
    'accel_shield_half',      35e-3;
    'accel_shield_wall',       4e-3;
    'accel_ring_gap',          2e-3;
    'accel_ring_bore_half',   15e-3;
    'accel_shield_back_extra',10e-3;
    'bore_r',                250e-3;
    'ring_outer_r',          300e-3;
    'flight_tube_r',         350e-3;
    'L_flight',              619.83e-3;
    'L_refl',                206.833e-3;
    'V_repeller',           2240;
    'V_grid1',              1760;
    'V_mid',                1600;
    'V_mirror',             2400};
for k = 1:size(expected, 1)
    name = expected{k, 1};
    value = model.param.evaluate(name);
    target = expected{k, 2};
    tolerance = max(1e-10, abs(target) * 1e-8);
    assert(abs(value - target) <= tolerance, ...
        '%s mismatch: actual %.15g, expected %.15g', name, value, target);
    fprintf(fid, 'PARAM_%s_EXPR=%s\n', name, char(model.param.get(name)));
    fprintf(fid, 'PARAM_%s_SI=%.15g\n', name, value);
end

fprintf(fid, 'COMPONENT_TAGS=%s\n', joinJavaStrings(model.component.tags));
fprintf(fid, 'STUDY_TAGS=%s\n', joinJavaStrings(model.study.tags));
fprintf(fid, 'SOLUTION_TAGS=%s\n', joinJavaStrings(model.sol.tags));
fprintf(fid, 'DATASET_TAGS=%s\n', joinJavaStrings(model.result.dataset.tags));
fprintf(fid, 'PLOTGROUP_TAGS=%s\n', joinJavaStrings(model.result.tags));

tSolve = tic;
model.study('std1').run;
fprintf(fid, 'STD1_RUN_SECONDS=%.6f\n', toc(tSolve));

coords = [
    -48.8, -48.8, -48.8, 0, 0, 0, 0;
     0,     0,     0,    0, 0, 0, 0;
     1.5,  10.0,  19.0, 300, 500, 650, 760];
labels = {'src_1p5', 'src_10', 'src_19', 'drift_300', ...
    'drift_500', 'refl_650', 'refl_760'};
[V, Ex, Ey, Ez] = mphinterp(model, {'V','es.Ex','es.Ey','es.Ez'}, ...
    'coord', coords, 'dataset', 'dset1');
for k = 1:numel(labels)
    fprintf(fid, 'FIELD_%s_XYZ_MM=%.9g,%.9g,%.9g\n', labels{k}, coords(:,k));
    fprintf(fid, 'FIELD_%s_V=%.15g\n', labels{k}, V(k));
    fprintf(fid, 'FIELD_%s_E_V_PER_M=%.15g,%.15g,%.15g\n', ...
        labels{k}, Ex(k), Ey(k), Ez(k));
end

fprintf(fid, 'STATUS=PASS\n');
clear cleanup
ModelUtil.remove('OaTofSyncVerify');

function text = joinJavaStrings(values)
items = cell(1, length(values));
for idx = 1:length(values)
    items{idx} = char(values(idx));
end
text = strjoin(items, ',');
end
