reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
testDir = fileparts(mfilename('fullpath'));
componentDir = fileparts(fileparts(testDir));
addpath(componentDir);
paths = oatof_paths();
contract = jsondecode(fileread(fullfile(componentDir, 'config', 'baseline.json')));
g = contract.geometry_mm;
modelPath = getenv('OATOF_COMSOL_MODEL_PATH');
if isempty(modelPath)
    modelPath = fullfile(paths.comsolFormalDir, ...
        'MS_oaTOF_TwoStageRingStackReflectron_Final.mph');
end
assert(isfile(modelPath), 'COMSOL model to verify is missing: %s', modelPath);

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
    'x_accel_center',        contract.coordinate_convention.accelerator_axis_x*1e-3;
    'L_accel',               g.L_accel*1e-3;
    'accel_shield_half',     g.accelerator_exit_grid_half_width*1e-3;
    'accel_shield_wall',     g.accelerator_shield_wall*1e-3;
    'accel_ring_gap',        g.accelerator_insulation_gap*1e-3;
    'accel_ring_bore_half',  g.accelerator_bore_half*1e-3;
    'accel_shield_back_extra',g.accelerator_rear_clearance*1e-3;
    'endcap_gap',            g.shield_near_endcap_gap*1e-3;
    'bore_r',                g.bore_r*1e-3;
    'ring_outer_r',          g.ring_outer_r*1e-3;
    'flight_tube_r',         g.flight_tube_r*1e-3;
    'flight_tube_wall',      g.flight_tube_wall*1e-3;
    'shield_axial_gap',      g.shield_axial_gap*1e-3;
    'ring_thickness',        g.ring_thickness*1e-3;
    'L_flight',              g.L_flight*1e-3;
    'L_refl',                g.L_reflectron*1e-3;
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

geom1 = model.component('comp1').geom('geom1');
shieldOuter = geom1.feature('flighttubewallO');
shieldBore = geom1.feature('flighttubewallH');
shield = geom1.feature('flighttubewall');
assert(strcmp(char(shieldOuter.getString('r')), ...
    'flight_tube_r+flight_tube_wall'), ...
    'Shield outer radius is not linked to the 10 mm wall.');
assert(strcmp(char(shieldOuter.getString('h')), ...
    'L_flight+L_refl+ring_thickness+shield_axial_gap-(-1[mm]-accel_shield_back_extra-accel_shield_wall-endcap_gap)+2*flight_tube_wall'), ...
    'Shield outer axial span no longer includes both end caps.');
assert(strcmp(char(shieldBore.getString('r')), 'flight_tube_r'), ...
    'Shield bore radius no longer matches the flight-tube vacuum.');
assert(contains(char(shield.label), 'one-piece shell with both ends closed'), ...
    'Shield feature is not the authoritative one-piece closed shell.');
fprintf(fid, 'SHIELD_OUTER_R_EXPR=%s\n', char(shieldOuter.getString('r')));
fprintf(fid, 'SHIELD_OUTER_H_EXPR=%s\n', char(shieldOuter.getString('h')));
fprintf(fid, 'SHIELD_BORE_R_EXPR=%s\n', char(shieldBore.getString('r')));
fprintf(fid, 'SHIELD_LABEL=%s\n', char(shield.label));

grid2Rectangle = geom1.feature('wp_grid2').geom.feature('r1');
grid2Size = grid2Rectangle.getStringArray('size');
assert(strcmp(char(grid2Size(1)), '2*accel_shield_half') && ...
    strcmp(char(grid2Size(2)), '2*accel_shield_half'), ...
    'Accelerator exit grid is not the linked 30 x 30 mm square.');
fprintf(fid, 'GRID2_SIZE_EXPR=%s,%s\n', ...
    char(grid2Size(1)), char(grid2Size(2)));

fprintf(fid, 'COMPONENT_TAGS=%s\n', joinJavaStrings(model.component.tags));
fprintf(fid, 'STUDY_TAGS=%s\n', joinJavaStrings(model.study.tags));
fprintf(fid, 'SOLUTION_TAGS=%s\n', joinJavaStrings(model.sol.tags));
fprintf(fid, 'DATASET_TAGS=%s\n', joinJavaStrings(model.result.dataset.tags));
fprintf(fid, 'PLOTGROUP_TAGS=%s\n', joinJavaStrings(model.result.tags));

acceleratorSelection = model.component('comp1').selection('selbracket');
assert(strcmp(char(acceleratorSelection.getString('xmin')), ...
    'x_accel_center-accel_shield_half'), ...
    'selbracket xmin is not linked to x_accel_center.');
assert(strcmp(char(acceleratorSelection.getString('xmax')), ...
    'x_accel_center+accel_shield_half'), ...
    'selbracket xmax is not linked to x_accel_center.');
acceleratorDomains = acceleratorSelection.entities(3);
assert(numel(acceleratorDomains) >= 6, ...
    'selbracket resolved to only %d domains.', numel(acceleratorDomains));
fprintf(fid, 'SELBRACKET_DOMAIN_COUNT=%d\n', numel(acceleratorDomains));
meshFeatureTags = joinJavaStrings(model.component('comp1').mesh('mesh1').feature.tags);
assert(~contains(meshFeatureTags, 'szbracket'), ...
    'Obsolete whole-accelerator submillimetre mesh feature still exists.');
fprintf(fid, 'MESH_FEATURE_TAGS=%s\n', meshFeatureTags);

detectorFeature = model.component('comp1').geom('geom1').feature('detector');
detectorRadiusExpr = char(detectorFeature.getString('r'));
detectorPositionExpr = detectorFeature.getStringArray('pos');
assert(any(strcmp(detectorRadiusExpr, {'40[mm]', 'detector_radius'})), ...
    'Detector radius is not the synchronized 40 mm geometry: %s', detectorRadiusExpr);
assert(any(strcmp(char(detectorPositionExpr(1)), {'48.80', 'detector_x'})), ...
    'Detector x is not linked/equivalent to +48.80 mm: %s', char(detectorPositionExpr(1)));
assert(strcmp(char(detectorPositionExpr(3)), 'detector_z-1[mm]'), ...
    'Detector z no longer follows detector_z: %s', char(detectorPositionExpr(3)));
fprintf(fid, 'DETECTOR_RADIUS_EXPR=%s\n', detectorRadiusExpr);
fprintf(fid, 'DETECTOR_POSITION_EXPR=%s,%s,%s\n', ...
    char(detectorPositionExpr(1)), char(detectorPositionExpr(2)), ...
    char(detectorPositionExpr(3)));

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
