% Build a GUI-visible oa-TOF accelerator geometry candidate from the formal MPH.

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
contractPath = getenv('OATOF_ACCELERATOR_CONTRACT_PATH');
candidatePath = getenv('OATOF_COMSOL_CANDIDATE_PATH');
dryRun = strcmp(getenv('OATOF_COMSOL_DRY_RUN'), '1');
assert(~isempty(reportPath), 'COMSOL_BOOTSTRAP_REPORT is not set.');
assert(~isempty(contractPath) && isfile(contractPath), 'Candidate contract is absent.');

testDir = fileparts(mfilename('fullpath'));
projectDir = fileparts(fileparts(testDir));
addpath(projectDir);
paths = oatof_paths();
formalPath = fullfile(paths.comsolFormalDir, ...
    'oa_tof__model.mph');
assert(isfile(formalPath), 'Formal source MPH is absent: %s', formalPath);
contract = jsondecode(fileread(contractPath));
expected = contract.expected_derived;
acceleratorRingCount = double(contract.design.local_geometry_mm.ring_count);
assert(acceleratorRingCount==floor(acceleratorRingCount) && acceleratorRingCount>0, ...
    'Candidate accelerator ring_count must be a positive integer.');

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Cannot open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, 'SOURCE_MODEL=%s\nCONTRACT=%s\nDRY_RUN=%d\n', ...
    formalPath, contractPath, dryRun);

model = mphopen(formalPath);
geom = model.component('comp1').geom('geom1');
required = {'repeller','accelshieldO','accelshieldH','relvol', ...
    'wp_grid1','wp_grid2','accelring_1O', ...
    sprintf('accelring_%dH',acceleratorRingCount)};
tags = string(cell(geom.feature.tags()));
assert(all(ismember(string(required), tags)), 'Formal MPH lacks accelerator geometry nodes.');
if dryRun
    fprintf(fid, 'REQUIRED_GEOMETRY_NODES=PASS\nSTATUS=PASS\n');
    com.comsol.model.util.ModelUtil.remove(model.tag());
    return;
end
assert(~isempty(candidatePath), 'OATOF_COMSOL_CANDIDATE_PATH is not set.');
candidateDir = fileparts(candidatePath);
if ~isfolder(candidateDir), mkdir(candidateDir); end

z0 = double(expected.assembly_translation_z_mm);
d1 = double(contract.design.local_geometry_mm.d1);
d2 = double(contract.design.local_geometry_mm.d2);
p = model.param;
p.set('z_accel_origin', sprintf('%.15g[mm]', z0), ...
    'Candidate rigid accelerator/source translation from strict time-focus contract');
p.set('L_accel_local', sprintf('%.15g[mm]', d1+d2), ...
    'Candidate local repeller-to-grid2 length');
p.set('L_accel', 'z_accel_origin+L_accel_local', ...
    'Global grid2 z-coordinate; separated from detector/time-focus plane');
p.set('detector_z', '19.83[mm]', 'Unchanged formal detector active plane');
p.set('L_flight', '619.83[mm]', 'Unchanged formal reflectron entrance coordinate');

geom.feature('repeller').set('pos', ...
    {'x_accel_center-(accel_shield_half-accel_ring_gap)', ...
     '-(accel_shield_half-accel_ring_gap)', 'z_accel_origin-1[mm]'});
geom.feature('accelshieldO').set('size', ...
    {'2*(accel_shield_half+accel_shield_wall)', ...
     '2*(accel_shield_half+accel_shield_wall)', ...
     'L_accel_local+1[mm]+accel_shield_back_extra+accel_shield_wall'});
geom.feature('accelshieldO').set('pos', ...
    {'x_accel_center-(accel_shield_half+accel_shield_wall)', ...
     '-(accel_shield_half+accel_shield_wall)', ...
     'z_accel_origin-1[mm]-accel_shield_back_extra-accel_shield_wall'});
geom.feature('accelshieldH').set('size', ...
    {'2*accel_shield_half','2*accel_shield_half', ...
     'L_accel_local+1[mm]+accel_shield_back_extra'});
geom.feature('accelshieldH').set('pos', ...
    {'x_accel_center-accel_shield_half','-accel_shield_half', ...
     'z_accel_origin-1[mm]-accel_shield_back_extra'});

for k = 1:acceleratorRingCount
    center = sprintf('z_accel_origin+3[mm]+%d*(L_accel_local-3[mm])/%d', ...
        k,acceleratorRingCount+1);
    geom.feature(sprintf('accelring_%dO', k)).set('pos', ...
        {'x_accel_center-(accel_shield_half-accel_ring_gap)', ...
         '-(accel_shield_half-accel_ring_gap)', [center '-0.5[mm]']});
    geom.feature(sprintf('accelring_%dH', k)).set('pos', ...
        {'x_accel_center-accel_ring_bore_half', ...
         '-accel_ring_bore_half', [center '-0.5[mm]']});
end
geom.feature('relvol').set('pos', {'x_accel_center-0.5','-0.5','z_accel_origin+1[mm]'});
geom.feature('wp_grid1').set('quickz', 'z_accel_origin+3[mm]');
geom.feature('wp_grid2').set('quickz', 'L_accel');

selGrid1 = model.component('comp1').selection('selb_grid1');
selGrid1.set('zmin', 'z_accel_origin+2.5[mm]');
selGrid1.set('zmax', 'z_accel_origin+3.5[mm]');
selGrid2 = model.component('comp1').selection('selb_grid2');
% The fixed 19.83 mm detector plane is only 0.128642 mm downstream of
% candidate grid2.  The formal +/-0.2 mm slab therefore also catches that
% boundary after the accelerator moves; keep this candidate selection local.
% The inherited xy box also spans the 38 x 38 mm shield end face.  Restrict
% it to the 30 x 30 mm grid rectangle so the GUI potential node owns only
% the ideal grid, while the shield remains covered by its own condition.
selGrid2.set('xmin', 'x_accel_center-accel_shield_half-0.01[mm]');
selGrid2.set('xmax', 'x_accel_center+accel_shield_half+0.01[mm]');
selGrid2.set('ymin', '-accel_shield_half-0.01[mm]');
selGrid2.set('ymax', 'accel_shield_half+0.01[mm]');
selGrid2.set('zmin', 'L_accel-0.05[mm]');
selGrid2.set('zmax', 'L_accel+0.05[mm]');
selBracket = model.component('comp1').selection('selbracket');
selBracket.set('zmin', 'z_accel_origin');
selBracket.set('zmax', 'L_accel');

geom.run();
grid1Boundaries = selGrid1.entities(2);
grid2Boundaries = selGrid2.entities(2);
fprintf(fid, 'GRID1_BOUNDARY_IDS=%s\n', strjoin(string(grid1Boundaries), ','));
fprintf(fid, 'GRID2_BOUNDARY_IDS=%s\n', strjoin(string(grid2Boundaries), ','));
for boundaryId = grid2Boundaries(:).'
    xyz = mphgetcoords(model, 'geom1', 'boundary', boundaryId);
    fprintf(fid, 'GRID2_CANDIDATE_BOUNDARY_%d_BOUNDS_MM=%.15g,%.15g,%.15g,%.15g,%.15g,%.15g\n', ...
        boundaryId, min(xyz(1,:)), max(xyz(1,:)), min(xyz(2,:)), ...
        max(xyz(2,:)), min(xyz(3,:)), max(xyz(3,:)));
end
assert(numel(grid1Boundaries) == 1, 'Candidate grid1 selection is not unique.');
assert(numel(grid2Boundaries) == 1, 'Candidate grid2 selection is not unique.');
assert(numel(selBracket.entities(3)) >= 6, 'Candidate accelerator domain selection is incomplete.');
model.component('comp1').mesh('mesh1').run();
model.study('std1').run();
model.label('oa-TOF strict-focus 0.1 mm accelerator geometry candidate');
mphsave(model, candidatePath);

fprintf(fid, 'Z_ACCEL_ORIGIN_MM=%.15g\n', mphevaluate(model, 'z_accel_origin', 'mm'));
fprintf(fid, 'GRID2_GLOBAL_Z_MM=%.15g\n', mphevaluate(model, 'L_accel', 'mm'));
fprintf(fid, 'DETECTOR_Z_MM=%.15g\n', mphevaluate(model, 'detector_z', 'mm'));
fprintf(fid, 'L_FLIGHT_MM=%.15g\n', mphevaluate(model, 'L_flight', 'mm'));
fprintf(fid, 'GRID1_BOUNDARIES=%d\nGRID2_BOUNDARIES=%d\nACCELERATOR_DOMAINS=%d\n', ...
    numel(grid1Boundaries), numel(grid2Boundaries), numel(selBracket.entities(3)));
fprintf(fid, 'GUI_STUDY_COMPUTE=std1\nCANDIDATE_MODEL=%s\nSTATUS=PASS\n', candidatePath);
com.comsol.model.util.ModelUtil.remove(model.tag());
