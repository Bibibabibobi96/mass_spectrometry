function test_lit_geometry_es()
% Linear ion trap: quadrupole rods (RF radial confinement, same as
% test_multipole_geometry(4)) + two DC end-cap aperture plates (axial
% confinement) -- the simplified "end-lens" LIT model (real commercial
% LTQ traps use segmented rods instead, which would need splitting each
% rod into 3 axial sections; end-cap plates are a legitimate simpler
% pedagogical substitute reusing the aperture-disk technique already
% validated for the electron gun and Einzel lens).
%
% Since the rods (RF, time-oscillating) and end-caps (DC, static) vary
% independently in time, they CANNOT share one electrostatic solve if we
% want to scale them independently in CPT -- solve TWO separate unit-
% amplitude problems (rods-only and endcaps-only, with the other group
% grounded in each), then recombine with independent time-dependent scale
% factors in the CPT ElectricForce expression (E = scale_rf(t)*es_rf.Ex
% + scale_dc*es_dc.Ex). This generalizes to any number of independently-
% driven electrode groups.

commonDir = fileparts(mfilename('fullpath'));
addpath(commonDir);
paths = common_artifact_paths();
addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
mphstart(2036);
import com.comsol.model.*
import com.comsol.model.util.*

if any(strcmp(cell(ModelUtil.tags()), 'ModelLIT'))
    ModelUtil.remove('ModelLIT');
end
model = ModelUtil.create('ModelLIT');
comp1 = model.component.create('comp1', true);
geom1 = comp1.geom.create('geom1', 3);
geom1.label('Linear Ion Trap geometry');
geom1.lengthUnit('mm');

p = model.param;
p.set('r0', '4[mm]');
p.set('rod_ratio', '1.1468');
p.set('r_rod', 'rod_ratio*r0');
p.set('R_center', 'r0+r_rod');
p.set('rod_len', '20[mm]');
p.set('rod_z0', '0[mm]');
p.set('V_rf_unit', '100[V]');
p.set('R_disk', 'R_center+r_rod+2[mm]');
p.set('r_hole_cap', '2[mm]');
p.set('t_cap', '1[mm]');
p.set('gap_cap', '2[mm]');
p.set('z_cap1', 'rod_z0-gap_cap-t_cap');
p.set('z_cap2', 'rod_z0+rod_len+gap_cap');
p.set('V_dc_unit', '100[V]');

Npoles = 4;
rodtags = {};
for k = 1:Npoles
    theta_deg = (k-1)*360/Npoles;
    tagk = sprintf('rod%d', k);
    xk = sprintf('R_center*cos(%g[deg])', theta_deg);
    yk = sprintf('R_center*sin(%g[deg])', theta_deg);
    geom1.feature.create(tagk, 'Cylinder');
    geom1.feature(tagk).label(sprintf('RF rod %d (r0=4mm, alternating +/-V_rf)', k));
    geom1.feature(tagk).set('r', 'r_rod');
    geom1.feature(tagk).set('h', 'rod_len');
    geom1.feature(tagk).set('pos', {xk yk 'rod_z0'});
    geom1.feature(tagk).set('axis', [0 0 1]);
    rodtags{end+1} = tagk; %#ok<AGROW>
end

% End-cap aperture plates
capNames = {'End cap 1 (z_cap1, DC axial barrier)', 'End cap 2 (z_cap2, DC axial barrier)'};
for k = 1:2
    tagOuter = sprintf('capO%d',k);
    tagHole = sprintf('capH%d',k);
    tagDiff = sprintf('cap%d',k);
    zk = sprintf('z_cap%d', k);
    geom1.feature.create(tagOuter, 'Cylinder');
    geom1.feature(tagOuter).label(sprintf('End cap %d outer solid', k));
    geom1.feature(tagOuter).set('r', 'R_disk');
    geom1.feature(tagOuter).set('h', 't_cap');
    geom1.feature(tagOuter).set('pos', {'0' '0' zk});
    geom1.feature.create(tagHole, 'Cylinder');
    geom1.feature(tagHole).label(sprintf('End cap %d aperture hole', k));
    geom1.feature(tagHole).set('r', 'r_hole_cap');
    geom1.feature(tagHole).set('h', 't_cap+0.4[mm]');
    geom1.feature(tagHole).set('pos', {'0' '0' [zk '-0.2[mm]']});
    geom1.feature.create(tagDiff, 'Difference');
    geom1.feature(tagDiff).label(capNames{k});
    geom1.feature(tagDiff).selection('input').set({tagOuter});
    geom1.feature(tagDiff).selection('input2').set({tagHole});
end

geom1.feature.create('cylv', 'Cylinder');
geom1.feature('cylv').label('Vacuum envelope (bounding cylinder)');
geom1.feature('cylv').set('r', 'R_disk');
geom1.feature('cylv').set('h', 'z_cap2+t_cap-z_cap1');
geom1.feature('cylv').set('pos', {'0' '0' 'z_cap1'});

% Small dedicated "release volume" INSIDE the vacuum, near the trap
% center (matches the post-hoc filter criteria used previously: r0<1mm,
% z0 in [8,12]mm). The geometry union/imprint automatically splits it out
% as its own domain (still vacuum -- same material), so CPT's Release
% feature can select JUST this small region instead of the whole
% vacuum -- this is what actually restricts WHICH particles get released
% (not just which are shown afterward), giving a clean, uncluttered
% native trajectory plot with no post-hoc filtering needed.
geom1.feature.create('relvol', 'Cylinder');
geom1.feature('relvol').label('Release volume (trap center, r<1mm)');
geom1.feature('relvol').set('r', '1[mm]');
geom1.feature('relvol').set('h', '4[mm]');
geom1.feature('relvol').set('pos', {'0' '0' '8[mm]'});
geom1.feature('relvol').set('selresult', 'on'); % so it gets an auto-named domain selection like the electrode solids do

allsoldtags = [rodtags, {'cap1','cap2'}];
for i = 1:numel(allsoldtags)
    geom1.feature(allsoldtags{i}).set('selresult', 'on');
end
geom1.run;
gi = mphgeominfo(model, 'geom1');
fprintf('Geometry built. Ndomains=%d\n', gi.Ndomains);

selDoms = cellfun(@(t) sprintf('geom1_%s_dom', t), allsoldtags, 'UniformOutput', false);
comp1.selection.create('sel_vac', 'Complement');
comp1.selection('sel_vac').label('Vacuum (all domains except rods+end caps)');
comp1.selection('sel_vac').set('input', selDoms);
vac_n = numel(comp1.selection('sel_vac').entities());
fprintf('sel_vac resolves to %d domain(s)\n', vac_n);
if vac_n ~= 2
    error('Expected 2 vacuum domains (rest-of-vacuum + relvol), got %d', vac_n);
end

fprintf('geom1_relvol_dom resolves to %d domain(s)\n', numel(comp1.selection('geom1_relvol_dom').entities()));

mat_vac = model.material.create('mat_vac', 'Common');
mat_vac.label('Vacuum (relpermittivity=1)');
mat_vac.selection.named('sel_vac');
mat_vac.propertyGroup('def').set('relpermittivity', {'1'});
elecLabels = [arrayfun(@(k) sprintf('RF rod %d material', k), 1:Npoles, 'UniformOutput', false), {'End cap 1 material', 'End cap 2 material'}];
for i = 1:numel(allsoldtags)
    matk = model.material.create(sprintf('mat_%s', allsoldtags{i}), 'Common');
    matk.label(elecLabels{i});
    matk.selection.named(selDoms{i});
    matk.propertyGroup('def').set('relpermittivity', {'1'});
end

% Boundary selections
selbLabels = [arrayfun(@(k) sprintf('RF rod %d boundary', k), 1:Npoles, 'UniformOutput', false), {'End cap 1 boundary', 'End cap 2 boundary'}];
selb = struct();
for i = 1:numel(allsoldtags)
    tagb = sprintf('selb_%s', allsoldtags{i});
    comp1.selection.create(tagb, 'Adjacent');
    comp1.selection(tagb).label(selbLabels{i});
    comp1.selection(tagb).set('input', {selDoms{i}});
    selb.(allsoldtags{i}) = tagb;
end

% Physics 1: es_rf -- rods at alternating +/-V_rf_unit, end caps grounded (0V)
es_rf = comp1.physics.create('es_rf', 'Electrostatics', 'geom1');
es_rf.label('Electrostatics: RF rods (unit amplitude, end caps grounded)');
es_rf.selection.named('sel_vac');
for k = 1:Npoles
    potk = es_rf.create(sprintf('pot_rod%d',k), 'ElectricPotential', 2);
    if mod(k,2)==1
        potk.label(sprintf('RF rod %d potential (+V_rf_unit)', k));
        potk.selection.named(selb.(rodtags{k}));
        potk.set('V0', 'V_rf_unit');
    else
        potk.label(sprintf('RF rod %d potential (-V_rf_unit)', k));
        potk.selection.named(selb.(rodtags{k}));
        potk.set('V0', '-V_rf_unit');
    end
end
for k = 1:2
    potk = es_rf.create(sprintf('pot_cap%d',k), 'ElectricPotential', 2);
    potk.label(sprintf('End cap %d potential (grounded, RF solve)', k));
    potk.selection.named(selb.(sprintf('cap%d',k)));
    potk.set('V0', '0');
end

% Physics 2: es_dc -- rods grounded, end caps at +V_dc_unit (both, symmetric barrier)
es_dc = comp1.physics.create('es_dc', 'Electrostatics', 'geom1');
es_dc.label('Electrostatics: DC end caps (unit amplitude, rods grounded)');
es_dc.selection.named('sel_vac');
for k = 1:Npoles
    potk = es_dc.create(sprintf('pot_rod%d',k), 'ElectricPotential', 2);
    potk.label(sprintf('RF rod %d potential (grounded, DC solve)', k));
    potk.selection.named(selb.(rodtags{k}));
    potk.set('V0', '0');
end
for k = 1:2
    potk = es_dc.create(sprintf('pot_cap%d',k), 'ElectricPotential', 2);
    potk.label(sprintf('End cap %d potential (+V_dc_unit)', k));
    potk.selection.named(selb.(sprintf('cap%d',k)));
    potk.set('V0', 'V_dc_unit');
end

mesh1 = comp1.mesh.create('mesh1');
mesh1.label('Mesh (hauto=4)');
mesh1.feature('size').set('hauto', 4);
mesh1.feature.create('ftet1', 'FreeTet');
mesh1.run;
mi = mphmeshstats(model, 'mesh1');
fprintf('mesh: isempty=%d iscomplete=%d\n', mi.isempty, mi.iscomplete);
if mi.isempty || ~mi.iscomplete
    error('mesh failed');
end

std1 = model.study.create('std1');
std1.label('Stationary: RF+DC unit-amplitude solves');
std1.create('stat1', 'Stationary');
model.sol.create('sol1');
model.sol('sol1').label('Solution: LIT electrostatics (RF+DC)');
model.sol('sol1').study('std1');
model.sol('sol1').createAutoSequence('std1');
model.sol('sol1').runAll;
fprintf('SUCCESS: both electrostatic solves (es_rf, es_dc) done.\n');

% Check on-axis DC potential profile (should show a barrier hump near
% each end cap, and be flat/low in the middle -- an axial potential well
% for positive ions if V_dc_unit>0)
fprintf('\nphysics tags in model: %s\n', strjoin(cell(comp1.physics.tags()), ', '));
zvals = [-2.5 0 5 10 15 20 22.5];
coords = [zeros(1,numel(zvals)); zeros(1,numel(zvals)); zvals];
% Potential/field variable namespace for a second Electrostatics
% interface is not guaranteed -- probe several candidates defensively
% instead of assuming '<tag>.normE' works.
candidates = {'es_dc.normE','es_rf.normE','V','V2','comp1.es_dc.normE'};
for ci = 1:numel(candidates)
    try
        vals = mphinterp(model, candidates{ci}, 'coord', coords, 'dataset', 'dset1', 'matherr', 'off');
        fprintf('%-20s : %s\n', candidates{ci}, mat2str(vals, 4));
    catch ME
        fprintf('%-20s : FAILED\n', candidates{ci});
    end
end

if ~exist(paths.modelsDir, 'dir'), mkdir(paths.modelsDir); end
model.save(fullfile(paths.modelsDir, 'LinearIonTrap.mph'));
fprintf('SUCCESS: model saved.\n');
end
