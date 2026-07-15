function test_einzel_lens()
% Einzel lens: 3 coaxial aperture disks (grounded-lens-grounded), same
% "aperture disk" technique validated for the electron gun's Wehnelt/
% anode plates. Middle disk held at a large negative voltage (decel-mode
% lens for positive ions); outer two grounded so the beam enters and
% exits at the same energy. Tests whether a beam of ions released at a
% spread of radii converges (focuses) after passing through.

commonDir = fileparts(mfilename('fullpath'));
addpath(commonDir);
paths = common_artifact_paths();
addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
mphstart(2036);
import com.comsol.model.*
import com.comsol.model.util.*

if any(strcmp(cell(ModelUtil.tags()), 'ModelEinzel'))
    ModelUtil.remove('ModelEinzel');
end
model = ModelUtil.create('ModelEinzel');
comp1 = model.component.create('comp1', true);
geom1 = comp1.geom.create('geom1', 3);
geom1.label('Einzel lens geometry');
geom1.lengthUnit('mm');

p = model.param;
p.set('R_disk', '10[mm]', 'Disk outer radius');
p.set('r_hole', '3[mm]', 'Aperture radius');
p.set('t_disk', '1[mm]', 'Disk thickness');
p.set('gap', '8[mm]', 'Gap between disks');
p.set('V1', '0[V]', 'Entrance disk (grounded)');
p.set('V2', '-4000[V]', 'Middle lens disk');
p.set('V3', '0[V]', 'Exit disk (grounded)');
p.set('z1', '0[mm]');
p.set('z2', 'z1+t_disk+gap');
p.set('z3', 'z2+t_disk+gap');

diskNames = {'Entrance disk (V1, grounded)', 'Lens disk (V2, focusing)', 'Exit disk (V3, grounded)'};
for k = 1:3
    tagOuter = sprintf('cylO%d',k);
    tagHole = sprintf('cylH%d',k);
    tagDiff = sprintf('disk%d',k);
    zk = sprintf('z%d', k);
    geom1.feature.create(tagOuter, 'Cylinder');
    geom1.feature(tagOuter).label(sprintf('Disk %d outer solid', k));
    geom1.feature(tagOuter).set('r', 'R_disk');
    geom1.feature(tagOuter).set('h', 't_disk');
    geom1.feature(tagOuter).set('pos', {'0' '0' zk});
    geom1.feature.create(tagHole, 'Cylinder');
    geom1.feature(tagHole).label(sprintf('Disk %d aperture hole', k));
    geom1.feature(tagHole).set('r', 'r_hole');
    geom1.feature(tagHole).set('h', 't_disk+0.4[mm]');
    geom1.feature(tagHole).set('pos', {'0' '0' [zk '-0.2[mm]']});
    geom1.feature.create(tagDiff, 'Difference');
    geom1.feature(tagDiff).label(diskNames{k});
    geom1.feature(tagDiff).selection('input').set({tagOuter});
    geom1.feature(tagDiff).selection('input2').set({tagHole});
end

geom1.feature.create('cylv', 'Cylinder');
geom1.feature('cylv').label('Vacuum envelope (bounding cylinder)');
geom1.feature('cylv').set('r', 'R_disk');
geom1.feature('cylv').set('h', 'z3+t_disk+3[mm]-(z1-3[mm])');
geom1.feature('cylv').set('pos', {'0' '0' 'z1-3[mm]'});

% Small dedicated "release volume" at the entrance, just before disk1 --
% represents an incoming collimated beam spot rather than releasing
% particles across the WHOLE vacuum (which scatters most of them deep
% inside/behind the lens where they don't represent a physical beam at
% all). Same technique validated for the LIT/quadrupole native trajectory
% plots: the geometry union carves this out as its own domain, and CPT's
% Release feature selects just this region.
geom1.feature.create('relvol', 'Cylinder');
geom1.feature('relvol').label('Release volume (entrance beam spot)');
geom1.feature('relvol').set('r', '1.5[mm]');
geom1.feature('relvol').set('h', '2[mm]');
geom1.feature('relvol').set('pos', {'0' '0' '-2.5[mm]'});
geom1.feature('relvol').set('selresult', 'on');

for k = 1:3
    geom1.feature(sprintf('disk%d',k)).set('selresult', 'on');
end
geom1.run;

gi = mphgeominfo(model, 'geom1');
fprintf('Geometry built. Ndomains=%d\n', gi.Ndomains);

comp1.selection.create('sel_vac', 'Complement');
comp1.selection('sel_vac').label('Vacuum (all domains except the 3 disks)');
comp1.selection('sel_vac').set('input', {'geom1_disk1_dom','geom1_disk2_dom','geom1_disk3_dom'});
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

es = comp1.physics.create('es', 'Electrostatics', 'geom1');
es.label('Electrostatics: Einzel lens');
es.selection.named('sel_vac');
Vparams = {'V1','V2','V3'};
diskLabels = {'Entrance', 'Lens', 'Exit'};
for k = 1:3
    seldom = sprintf('geom1_disk%d_dom', k);
    selb = sprintf('selb_disk%d', k);
    comp1.selection.create(selb, 'Adjacent');
    comp1.selection(selb).label(sprintf('%s disk boundary', diskLabels{k}));
    comp1.selection(selb).set('input', {seldom});
    matk = model.material.create(sprintf('mat_disk%d',k), 'Common');
    matk.label(sprintf('%s disk material', diskLabels{k}));
    matk.selection.named(seldom);
    matk.propertyGroup('def').set('relpermittivity', {'1'});
    potk = es.create(sprintf('pot%d',k), 'ElectricPotential', 2);
    potk.label(sprintf('%s disk potential (%s)', diskLabels{k}, Vparams{k}));
    potk.selection.named(selb);
    potk.set('V0', Vparams{k});
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
std1.label('Stationary: Einzel lens electrostatics');
std1.create('stat1', 'Stationary');
model.sol.create('sol1');
model.sol('sol1').label('Solution: Einzel lens ES');
model.sol('sol1').study('std1');
model.sol('sol1').createAutoSequence('std1');
model.sol('sol1').runAll;
fprintf('SUCCESS: electrostatics solved.\n');

% Quick on-axis potential check
zvals = [-2 1.5 4.5 9.5 14.5 17.5 21];
coords = [zeros(1,numel(zvals)); zeros(1,numel(zvals)); zvals];
Vq = mphinterp(model, 'V', 'coord', coords, 'dataset', 'dset1', 'matherr', 'off');
fprintf('\nOn-axis potential:\n');
for i=1:numel(zvals)
    fprintf('  z=%6.2fmm  V=%9.3fV\n', zvals(i), Vq(i));
end

resultsDir = paths.resultsDir;
if ~exist(resultsDir,'dir'), mkdir(resultsDir); end
pg1 = model.result.create('pg_V', 'PlotGroup3D');
pg1.label('Einzel lens: potential slice plot');
pg1.set('titletype', 'manual');
pg1.set('title', 'Einzel lens: electric potential V, zx-plane slice');
sl1 = pg1.create('slice1', 'Slice');
sl1.label('Potential V (zx-plane through axis)');
sl1.set('quickplane','zx'); sl1.set('quickznumber','1'); sl1.set('quickxnumber','1'); sl1.set('quickynumber','1');
sl1.set('expr','V');
imgV = model.result.export.create('imgV','Image');
imgV.label('Export: Einzel lens potential image');
imgV.set('plotgroup','pg_V'); imgV.set('pngfilename', fullfile(resultsDir,'einzel_potential.png'));
imgV.set('width',1200); imgV.set('height',700); imgV.run;
fprintf('SUCCESS: potential image exported.\n');

model.save(fullfile(paths.modelsDir, 'EinzelLens.mph'));
fprintf('SUCCESS: model saved.\n');
end
