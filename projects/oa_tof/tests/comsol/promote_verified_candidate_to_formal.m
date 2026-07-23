reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
testDir = fileparts(mfilename('fullpath'));
componentDir = fileparts(fileparts(testDir));
addpath(componentDir);
paths = oatof_paths();
contract = jsondecode(fileread(fullfile(componentDir, 'config', 'resolved_geometry.json')));
g = contract.geometry_mm;

candidatePath = getenv('OATOF_CANDIDATE_MODEL_PATH');
assert(~isempty(candidatePath), 'OATOF_CANDIDATE_MODEL_PATH is required.');
formalPath = fullfile(paths.comsolFormalDir, ...
    'oa_tof__model.mph');
transaction = oatof_assert_formal_write_authorized(formalPath,'comsol_model');
assert(isfile(candidatePath), 'Verified candidate is missing: %s', candidatePath);

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, 'CANDIDATE=%s\n', candidatePath);
fprintf(fid, 'FORMAL=%s\n', formalPath);

import com.comsol.model.util.*
model = mphload(candidatePath, 'OaTofPromotion');
expected = {
    'x_accel_center',         contract.coordinate_convention.accelerator_axis_x*1e-3;
    'L_accel',                g.L_accel*1e-3;
    'z_accel_origin',         g.accelerator_repeller_z*1e-3;
    'z_accel_grid1',          g.accelerator_grid1_z*1e-3;
    'z_accel_grid2',          g.accelerator_grid2_z*1e-3;
    'detector_z',             g.detector_z*1e-3;
    'accel_shield_half',      g.accelerator_exit_grid_half_width*1e-3;
    'accel_shield_wall',      g.accelerator_shield_wall*1e-3;
    'accel_ring_gap',         g.accelerator_insulation_gap*1e-3;
    'accel_ring_bore_half',   g.accelerator_bore_half*1e-3;
    'accel_shield_back_extra',g.accelerator_rear_clearance*1e-3;
    'endcap_gap',             g.shield_near_endcap_gap*1e-3;
    'flight_tube_r',          g.flight_tube_r*1e-3;
    'flight_tube_wall',       g.flight_tube_wall*1e-3;
    'shield_axial_gap',       g.shield_axial_gap*1e-3;
    'ring_thickness',         g.ring_thickness*1e-3;
    'L_flight',               g.L_flight*1e-3;
    'L_refl',                 g.L_reflectron*1e-3};
for k = 1:size(expected, 1)
    actual = model.param.evaluate(expected{k, 1});
    target = expected{k, 2};
    assert(abs(actual-target) <= max(1e-10, abs(target)*1e-8), ...
        '%s mismatch: actual %.15g expected %.15g', ...
        expected{k, 1}, actual, target);
    fprintf(fid, 'PARAM_%s_SI=%.15g\n', expected{k, 1}, actual);
end

geom1 = model.component('comp1').geom('geom1');
shield = geom1.feature('flighttubewall');
assert(contains(char(shield.label), 'one-piece shell with both ends closed'), ...
    'Candidate does not contain the authoritative closed shield.');
grid2Size = geom1.feature('wp_grid2').geom.feature('r1').getStringArray('size');
assert(strcmp(char(grid2Size(1)), '2*accel_shield_half') && ...
    strcmp(char(grid2Size(2)), '2*accel_shield_half'), ...
    'Candidate accelerator exit grid is not linked to accel_shield_half.');

releaseLabel = char(model.component('comp1').physics('cpt') ...
    .feature('rel1').label);
assert(contains(releaseLabel, 'fixed SIMION particle table (N=100)'), ...
    'Promotion candidate is not the verified fixed N=100 release: %s', ...
    releaseLabel);
assert(model.sol('sol1').isAttached() && model.sol('sol2').isAttached(), ...
    'Candidate solver attachment is incomplete.');
fprintf(fid, 'RELEASE_LABEL=%s\n', releaseLabel);
fprintf(fid, 'SHIELD_LABEL=%s\n', char(shield.label));
fprintf(fid, 'GRID2_SIZE_EXPR=%s,%s\n', ...
    char(grid2Size(1)), char(grid2Size(2)));

meshHmaxAccel = model.param.evaluate('mesh_hmax_accel');
assert(abs(meshHmaxAccel-1e-3) <= 1e-12, ...
    'Candidate accelerator mesh hmax is %.15g m, expected 1 mm.', meshHmaxAccel);
mesh = model.component('comp1').mesh('mesh1');
meshTags = string(cell(mesh.feature.tags()));
szaccelIndex = find(meshTags == "szaccel", 1);
ftetIndex = find(meshTags == "ftet1", 1);
assert(~isempty(szaccelIndex) && ~isempty(ftetIndex) && szaccelIndex < ftetIndex, ...
    'Accelerator Size must exist before Free Tetrahedral: %s', join(meshTags, ','));
assert(strcmp(char(mesh.feature('szaccel').getString('hmax')), ...
    'mesh_hmax_accel'), 'Accelerator Size does not use the GUI parameter.');
fprintf(fid, 'MESH_HMAX_ACCEL_MM=%.12g\n', meshHmaxAccel*1e3);
fprintf(fid, 'MESH_FEATURES=%s\n', join(meshTags, ','));
meshInfo = mphmeshstats(model, 'mesh1');
assert(meshInfo.numelem(2) > 300000, ...
    ['Candidate claims a 1 mm accelerator mesh but contains only %d ' ...
     'tetrahedra; overlapping Size-feature order is invalid.'], ...
    meshInfo.numelem(2));
fprintf(fid, 'MESH_TETRAHEDRA=%d\n', meshInfo.numelem(2));

runtime = contract.comsol_runtime;
assert(abs(model.param.evaluate('cpt_dt_fine')- ...
    runtime.fine_output_step_ns*1e-9) <= 1e-15, ...
    'Fine output step does not match baseline.json.');
assert(abs(model.param.evaluate('cpt_dt_drift')- ...
    runtime.field_free_output_step_ns*1e-9) <= 1e-15, ...
    'Field-free output step does not match baseline.json.');
timeStudy = model.study('std2').feature('time1');
tlist = char(timeStudy.getString('tlist'));
requiredTimeTokens = {'cpt_dt_fine','cpt_dt_drift', ...
    'cpt_t_refl_start','cpt_t_refl_end', ...
    'cpt_t_detector_start','cpt_t_detector_end'};
for k = 1:numel(requiredTimeTokens)
    assert(contains(tlist, requiredTimeTokens{k}), ...
        'Study Output times omit %s: %s', requiredTimeTokens{k}, tlist);
end
solverTime = model.sol('sol2').feature('t1');
assert(strcmp(char(solverTime.getString('tstepsbdf')), 'free'), ...
    'Solver Steps taken must be GUI-visible free mode.');
assert(strcmp(char(solverTime.getString('tout')), 'tlist'), ...
    'Solver Times to store must follow the GUI Study Output times.');
cpt = model.component('comp1').physics('cpt');
assert(~cpt.prop('StoreExtra').getBoolean('StoreExtra'), ...
    'Store extra wall times must be disabled in the routine model.');
assert(~cpt.prop('StoreParticleStatusData').getBoolean( ...
    'StoreParticleStatusData'), ...
    'Particle status storage must be disabled in the routine model.');
fprintf(fid, 'GUI_OUTPUT_TIMES=%s\n', tlist);
fprintf(fid, 'GUI_FINE_STEP_NS=%.12g\n', ...
    model.param.evaluate('cpt_dt_fine')*1e9);
fprintf(fid, 'GUI_DRIFT_STEP_NS=%.12g\n', ...
    model.param.evaluate('cpt_dt_drift')*1e9);
fprintf(fid, 'GUI_PREDICTED_TOF_US=%.12g\n', ...
    model.param.evaluate('t_detector_ref')*1e6);

if ~isfolder(paths.comsolFormalDir), mkdir(paths.comsolFormalDir); end
model.label('oa_tof__model.mph');
stagedPath = formalPath + ".promotion-" + string(transaction.authorization_id) + ".tmp.mph";
stagedCleanup = onCleanup(@() delete_if_present(stagedPath));
model.save(stagedPath);
assert(isfile(stagedPath), 'Staged Formal MPH was not written: %s', stagedPath);
[moved,message] = movefile(stagedPath,formalPath,'f');
assert(moved,'Formal MPH atomic replacement failed: %s',message);
clear stagedCleanup
assert(isfile(formalPath), 'Formal MPH was not written: %s', formalPath);
fprintf(fid, 'STATUS=PASS\n');
clear cleanup
ModelUtil.remove('OaTofPromotion');

function delete_if_present(path)
if isfile(path), delete(path); end
end
