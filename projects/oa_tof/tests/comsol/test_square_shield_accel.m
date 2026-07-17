function test_square_shield_accel()
% Standalone minimal test: square shield tube + square annular ring
% electrodes for the accelerator's grid1-grid2 region (the part that
% showed the worst fringing with a cylindrical shield -- see doc §7.32).
% Electrostatics only, no CPT -- just checking field linearity along the
% axis and confirming zero leakage outside the shield, before touching
% the full ms_oaTOF_two_stage_ringstack_reflectron.m model again.
%
% Geometry mirrors the real accelerator's second stage: gap=16.83mm,
% V_grid1=1760V at z=0 down to 0V at z=16.83mm (target Ez=104.575 V/mm
% uniform). Shield half-width chosen to match the real design's
% accel_shield_r=35mm attempt.

addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
componentRoot = fileparts(fileparts(fileparts(mfilename('fullpath'))));
addpath(componentRoot);
paths = oatof_paths();
import com.comsol.model.*
import com.comsol.model.util.*

model = ModelUtil.create('SquareShieldTest');
model.component.create('comp1', true);
comp1 = model.component('comp1');
comp1.geom.create('geom1', 3);
geom1 = comp1.geom('geom1');
geom1.lengthUnit('mm');

p = model.param;
p.set('gap', '16.83[mm]', 'Grid1-grid2 gap length');
p.set('V0', '1760[V]', 'Grid1-side potential');
p.set('shield_half', '35[mm]', 'Shield inner half-width (square)');
p.set('shield_wall', '2[mm]', 'Shield wall thickness');
p.set('N_rings', '5', 'Number of intermediate graded ring electrodes');
p.set('ring_gap', '2[mm]', 'Vacuum gap between ring electrode edge and shield inner wall');
p.set('ring_bore_half', '15[mm]', 'Ring electrode bore half-width (square hole)');

%% Shield: square tube, outer minus inner (Block-Block, same Difference
% technique as the reflectron's Cylinder-Cylinder rings, just square).
geom1.feature.create('shieldO', 'Block');
geom1.feature('shieldO').label('Shield outer solid');
geom1.feature('shieldO').set('size', {'2*(shield_half+shield_wall)', '2*(shield_half+shield_wall)', 'gap+4[mm]'});
geom1.feature('shieldO').set('pos', {'-(shield_half+shield_wall)', '-(shield_half+shield_wall)', '-2[mm]'});
geom1.feature.create('shieldH', 'Block');
geom1.feature('shieldH').label('Shield bore (inner vacuum)');
geom1.feature('shieldH').set('size', {'2*shield_half', '2*shield_half', 'gap+4[mm]'});
geom1.feature('shieldH').set('pos', {'-shield_half', '-shield_half', '-2[mm]'});
geom1.feature.create('shield', 'Difference');
geom1.feature('shield').label('Shield (grounded square tube wall)');
geom1.feature('shield').selection('input').set({'shieldO'});
geom1.feature('shield').selection('input2').set({'shieldH'});

%% Vacuum inside the shield (the region CPT/es actually cares about).
geom1.feature.create('vac', 'Block');
geom1.feature('vac').label('Vacuum inside shield');
geom1.feature('vac').set('size', {'2*shield_half', '2*shield_half', 'gap'});
geom1.feature('vac').set('pos', {'-shield_half', '-shield_half', '0'});

%% Endpoint flat grids (idealized interior boundaries, ion-transparent):
% same WorkPlane+Union+intbnd technique as the main model, sized to
% match the shield's OWN bore (flush, no gap needed here since these are
% CO-PLANAR interior boundaries inside the vacuum, not separate solids
% that could touch the shield wall -- only SOLID objects like the rings
% need a physical gap from the shield).
gridspecs = {'wp_g1','0[mm]'; 'wp_g2','gap'};
for gi_ = 1:size(gridspecs,1)
    wptag = gridspecs{gi_,1};
    zexpr = gridspecs{gi_,2};
    wp = geom1.feature.create(wptag, 'WorkPlane');
    wp.set('quickplane', 'xy');
    wp.set('quickz', zexpr);
    wp.geom.feature.create('r1', 'Rectangle');
    wp.geom.feature('r1').set('size', {'2*shield_half', '2*shield_half'});
    wp.geom.feature('r1').set('pos', {'-shield_half', '-shield_half'});
end

%% Intermediate graded ring electrodes: square annulus (Block outer minus
% Block inner bore), with a REQUIRED gap from the shield wall (different
% voltage conductors must not touch -- see doc §7.32 for why this bit
% the cylindrical attempt).
ringtags = {};
for k = 1:5 % N_rings (hardcoded to match the p.set above)
    tagk = sprintf('ring_%d', k);
    zk_expr = sprintf('%d*gap/(N_rings+1)', k);
    Vk_expr = sprintf('V0*(1-%d/(N_rings+1))', k);
    outer_half = 'shield_half-ring_gap';
    geom1.feature.create([tagk 'O'], 'Block');
    geom1.feature([tagk 'O']).label(sprintf('Ring %d outer solid', k));
    geom1.feature([tagk 'O']).set('size', {['2*(' outer_half ')'], ['2*(' outer_half ')'], '1[mm]'});
    geom1.feature([tagk 'O']).set('pos', {['-(' outer_half ')'], ['-(' outer_half ')'], [zk_expr '-0.5[mm]']});
    geom1.feature.create([tagk 'H'], 'Block');
    geom1.feature([tagk 'H']).label(sprintf('Ring %d bore', k));
    geom1.feature([tagk 'H']).set('size', {'2*ring_bore_half', '2*ring_bore_half', '1[mm]'});
    geom1.feature([tagk 'H']).set('pos', {'-ring_bore_half', '-ring_bore_half', [zk_expr '-0.5[mm]']});
    geom1.feature.create(tagk, 'Difference');
    geom1.feature(tagk).label(sprintf('Ring %d (V=%s)', k, Vk_expr));
    geom1.feature(tagk).selection('input').set({[tagk 'O']});
    geom1.feature(tagk).selection('input2').set({[tagk 'H']});
    ringtags{end+1} = tagk; %#ok<AGROW>
end

for t = [{'shield'}, ringtags]
    geom1.feature(t{1}).set('selresult', 'on');
end
geom1.feature('vac').set('selresult', 'on');

geom1.run;
gi = mphgeominfo(model, 'geom1');
fprintf('Geometry built. Ndomains=%d\n', gi.Ndomains);

%% Selections
soliddoms = [{'shield'}, ringtags];
soliddomtags = cellfun(@(t) sprintf('geom1_%s_dom', t), soliddoms, 'UniformOutput', false);
comp1.selection.create('sel_vac', 'Complement');
comp1.selection('sel_vac').set('input', soliddomtags);
vac_n = numel(comp1.selection('sel_vac').entities());
fprintf('sel_vac resolves to %d domain(s)\n', vac_n);

mat_vac = model.material.create('mat_vac', 'Common');
mat_vac.selection.named('sel_vac');
mat_vac.propertyGroup('def').set('relpermittivity', {'1'});
for t = soliddoms
    matk = model.material.create(sprintf('mat_%s', t{1}), 'Common');
    matk.selection.named(sprintf('geom1_%s_dom', t{1}));
    matk.propertyGroup('def').set('relpermittivity', {'1'});
end

for t = soliddoms
    tagb = sprintf('selb_%s', t{1});
    comp1.selection.create(tagb, 'Adjacent');
    comp1.selection(tagb).set('input', {sprintf('geom1_%s_dom', t{1})});
end

gridsel = {
    'selb_g1',  '0[mm]'  '0.3[mm]'
    'selb_g2',  'gap'    '0.3[mm]'
};
for gi_ = 1:size(gridsel,1)
    seltag = gridsel{gi_,1};
    zexpr = gridsel{gi_,2};
    zhalf = gridsel{gi_,3};
    comp1.selection.create(seltag, 'Box');
    comp1.selection(seltag).set('xmin', '-shield_half'); comp1.selection(seltag).set('xmax', 'shield_half');
    comp1.selection(seltag).set('ymin', '-shield_half'); comp1.selection(seltag).set('ymax', 'shield_half');
    comp1.selection(seltag).set('zmin', [zexpr '-' zhalf]); comp1.selection(seltag).set('zmax', [zexpr '+' zhalf]);
    comp1.selection(seltag).set('condition', 'allvertices');
    comp1.selection(seltag).geom('geom1', 2);
    fprintf('%s boundary count: %d\n', seltag, numel(comp1.selection(seltag).entities()));
end
for t = soliddoms
    fprintf('%s boundary count: %d\n', sprintf('selb_%s',t{1}), numel(comp1.selection(sprintf('selb_%s',t{1})).entities()));
end

comp1.selection.create('sel_vac_allbnd', 'Adjacent');
comp1.selection('sel_vac_allbnd').set('input', {'sel_vac'});
allbnd_ents = comp1.selection('sel_vac_allbnd').entities();
elecbnd_ents = [];
for t = soliddoms
    elecbnd_ents = [elecbnd_ents; comp1.selection(sprintf('selb_%s', t{1})).entities()]; %#ok<AGROW>
end
for gi_ = 1:size(gridsel,1)
    elecbnd_ents = [elecbnd_ents; comp1.selection(gridsel{gi_,1}).entities()]; %#ok<AGROW>
end
elecbnd_ents = unique(elecbnd_ents);
outerwall_ents = setdiff(allbnd_ents, elecbnd_ents);
fprintf('Outer walls: %d boundary/boundaries found\n', numel(outerwall_ents));
comp1.selection.create('selb_outerwall', 'Explicit');
comp1.selection('selb_outerwall').geom('geom1', 2);
comp1.selection('selb_outerwall').set(outerwall_ents);

%% Electrostatics
es = comp1.physics.create('es', 'Electrostatics', 'geom1');
es.selection.named('sel_vac');

pot_shield = es.create('pot_shield', 'ElectricPotential', 2);
pot_shield.selection.named('selb_shield');
pot_shield.set('V0', '0');
pot_outer = es.create('pot_outer', 'ElectricPotential', 2);
pot_outer.selection.named('selb_outerwall');
pot_outer.set('V0', '0');

pot_g1 = es.create('pot_g1', 'ElectricPotential', 2);
pot_g1.selection.named('selb_g1');
pot_g1.set('V0', 'V0');
pot_g2 = es.create('pot_g2', 'ElectricPotential', 2);
pot_g2.selection.named('selb_g2');
pot_g2.set('V0', '0');

for k = 1:5
    tagk = sprintf('ring_%d', k);
    tagb = sprintf('selb_%s', tagk);
    potk = es.create(sprintf('pot_%s', tagk), 'ElectricPotential', 2);
    potk.selection.named(tagb);
    potk.set('V0', sprintf('V0*(1-%d/(N_rings+1))', k));
end

%% Mesh + solve
mesh1 = comp1.mesh.create('mesh1');
mesh1.autoMeshSize(4);
mesh1.run;
gi2 = mphmeshstats(model, 'mesh1');
fprintf('mesh: Nelem=%d\n', gi2.numelem);

std1 = model.study.create('std1');
std1.create('stat1', 'Stationary');
model.sol.create('sol1');
model.sol('sol1').study('std1');
model.sol('sol1').createAutoSequence('std1');
t0 = tic;
model.sol('sol1').runAll;
fprintf('SUCCESS: electrostatics solved (%.2fs).\n', toc(t0));

%% Diagnostics: field linearity along axis + off-axis uniformity near
% the shield wall (checking the field stays contained/uniform even near
% the shield, not just on-axis -- this test model has no vacuum defined
% beyond the shield wall, so there's nothing to "leak into"; the
% relevant check here is whether the field near the shield's inner
% surface still matches the on-axis value, confirming good containment).
% V decreases with z (V0 at z=0 down to 0 at z=gap), so Ez=-dV/dz is
% POSITIVE.
Ez_theory_Vm = p.evaluate('V0','V')/p.evaluate('gap','mm')*1000;
fprintf('\n--- On-axis Ez along the gap (target %.2f V/m, uniform) ---\n', Ez_theory_Vm);
for zc = linspace(1, 15.83, 10)
    coord = [0; 0; zc];
    Ez = mphinterp(model, 'es.Ez', 'coord', coord, 'dataset', 'dset1', 'matherr', 'off');
    fprintf('  z=%6.2fmm: Ez=%10.4f V/m (diff=%.4f%%)\n', zc, Ez, 100*(Ez-Ez_theory_Vm)/Ez_theory_Vm);
end

fprintf('\n--- Off-axis uniformity near the shield inner wall (x=30mm, still inside shield_half=35mm) ---\n');
for zc = linspace(1, 15.83, 5)
    coord = [30; 0; zc];
    Ez = mphinterp(model, 'es.Ez', 'coord', coord, 'dataset', 'dset1', 'matherr', 'off');
    fprintf('  x=30mm z=%6.2fmm: Ez=%10.4f V/m (diff=%.4f%%)\n', zc, Ez, 100*(Ez-Ez_theory_Vm)/Ez_theory_Vm);
end

modelsDir = paths.comsolScratchDir;
if ~exist(modelsDir, 'dir'), mkdir(modelsDir); end
model.save(fullfile(modelsDir, 'test_square_shield_accel.mph'));
fprintf('\nSUCCESS: model saved.\n');
end
