reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
testDir = fileparts(mfilename('fullpath'));
componentDir = fileparts(fileparts(testDir));
addpath(componentDir);
paths = oatof_paths();
contract = jsondecode(fileread(fullfile(componentDir, 'config', 'baseline.json')));
g = contract.geometry_mm;

candidatePath = fullfile(paths.comsolCandidateDir, ...
    'MS_oaTOF_TwoStageRingStackReflectron_Candidate_524amu_FixedN100_real_dt0.2ns.mph');
formalPath = fullfile(paths.comsolFormalDir, ...
    'MS_oaTOF_TwoStageRingStackReflectron_Final.mph');
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

if ~isfolder(paths.comsolFormalDir), mkdir(paths.comsolFormalDir); end
model.label('MS_oaTOF_TwoStageRingStackReflectron_Final.mph');
model.save(formalPath);
assert(isfile(formalPath), 'Formal MPH was not written: %s', formalPath);
fprintf(fid, 'STATUS=PASS\n');
clear cleanup
ModelUtil.remove('OaTofPromotion');
