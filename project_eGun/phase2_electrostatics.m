function phase2_electrostatics()
% Phase 2: materials, voltage boundary conditions, electrostatics solve,
% potential/field result plots and key on-axis value summary.

addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
mphstart(2036);
import com.comsol.model.*
import com.comsol.model.util.*

modelPath = 'C:\Users\Liao\PycharmProjects\PythonProject\comsol_models\project_eGun\ElectronGun.mph';
savePath  = 'C:\Users\Liao\PycharmProjects\PythonProject\comsol_models\project_eGun\ElectronGun_ES.mph';
if any(strcmp(cell(ModelUtil.tags()), 'Model'))
    ModelUtil.remove('Model');
end
model = ModelUtil.load('Model', modelPath);
comp1 = model.component('comp1');
geom1 = comp1.geom('geom1');

%% Enable output selections on the 4 top-level solids so we can reference
% their domains by name (avoids guessing raw domain index numbers).
geom1.feature('cyl6').set('selresult', 'on');
geom1.feature('chdif1').set('selresult', 'on');
geom1.feature('chdif2').set('selresult', 'on');
geom1.feature('chdif3').set('selresult', 'on');
geom1.run;

sel_vac  = 'geom1_cyl6_dom';
sel_cath = 'geom1_chdif1_dom';
sel_weh  = 'geom1_chdif2_dom';
sel_an   = 'geom1_chdif3_dom';

% Boundary selections = boundaries adjacent to each electrode domain
comp1.selection.create('selb_cath', 'Adjacent');
comp1.selection('selb_cath').label('Cathode Surface');
comp1.selection('selb_cath').set('input', {sel_cath});

comp1.selection.create('selb_weh', 'Adjacent');
comp1.selection('selb_weh').label('Wehnelt Surface');
comp1.selection('selb_weh').set('input', {sel_weh});

comp1.selection.create('selb_an', 'Adjacent');
comp1.selection('selb_an').label('Anode Surface');
comp1.selection('selb_an').set('input', {sel_an});

%% Materials
mat_vac = model.material.create('mat_vac', 'Common');
mat_vac.label('Vacuum');
mat_vac.selection.named(sel_vac);
mat_vac.propertyGroup('def').set('relpermittivity', {'1'});

mat_cath = model.material.create('mat_cath', 'Common');
mat_cath.label('Tungsten (Cathode)');
mat_cath.selection.named(sel_cath);
mat_cath.propertyGroup('def').set('relpermittivity', {'1'});

mat_weh = model.material.create('mat_weh', 'Common');
mat_weh.label('Stainless Steel (Wehnelt)');
mat_weh.selection.named(sel_weh);
mat_weh.propertyGroup('def').set('relpermittivity', {'1'});

mat_an = model.material.create('mat_an', 'Common');
mat_an.label('Stainless Steel (Anode)');
mat_an.selection.named(sel_an);
mat_an.propertyGroup('def').set('relpermittivity', {'1'});

%% Physics: Electrostatics, solved only in the vacuum domain
es = comp1.physics.create('es', 'Electrostatics', 'geom1');
es.selection.named(sel_vac);

pot_c = es.create('pot_cath', 'ElectricPotential', 2);
pot_c.selection.named('selb_cath');
pot_c.set('V0', 'V_cathode');

pot_w = es.create('pot_weh', 'ElectricPotential', 2);
pot_w.selection.named('selb_weh');
pot_w.set('V0', 'V_wehnelt');

pot_a = es.create('pot_an', 'ElectricPotential', 2);
pot_a.selection.named('selb_an');
pot_a.set('V0', 'V_anode');
% Remaining outer envelope boundaries default to Zero Charge (open boundary).

%% Mesh
mesh1 = comp1.mesh.create('mesh1');
mesh1.feature('size').set('hauto', 3);   % "Finer" global preset
mesh1.run;

%% Study + solve
std1 = model.study.create('std1');
std1.create('stat1', 'Stationary');
std1.label('Electrostatics Study');
model.sol.create('sol1');
model.sol('sol1').study('std1');
model.sol('sol1').createAutoSequence('std1');
model.sol('sol1').runAll;

fprintf('SUCCESS: Electrostatics solved.\n');

%% Result plots: potential slice + electric field norm slice
pg1 = model.result.create('pg_V', 'PlotGroup3D');
pg1.label('Electric Potential (V)');
sl1 = pg1.create('slice1', 'Slice');
sl1.set('quickplane', 'zx');
sl1.set('quickznumber', '1');
sl1.set('quickxnumber', '1');
sl1.set('quickynumber', '1');
sl1.set('expr', 'V');

pg2 = model.result.create('pg_E', 'PlotGroup3D');
pg2.label('Electric Field Norm (normE)');
sl2 = pg2.create('slice2', 'Slice');
sl2.set('quickplane', 'zx');
sl2.set('quickznumber', '1');
sl2.set('quickxnumber', '1');
sl2.set('quickynumber', '1');
sl2.set('expr', 'es.normE');

resultsDir = 'C:\Users\Liao\PycharmProjects\PythonProject\comsol_results';
if ~exist(resultsDir, 'dir')
    mkdir(resultsDir);
end

imgV = model.result.export.create('imgV', 'Image');
imgV.set('plotgroup', 'pg_V');
imgV.set('pngfilename', fullfile(resultsDir, 'potential_distribution.png'));
imgV.set('width', 1200);
imgV.set('height', 800);
imgV.run;

imgE = model.result.export.create('imgE', 'Image');
imgE.set('plotgroup', 'pg_E');
imgE.set('pngfilename', fullfile(resultsDir, 'efield_distribution.png'));
imgE.set('width', 1200);
imgE.set('height', 800);
imgE.run;

fprintf('SUCCESS: Result images exported to %s\n', resultsDir);

%% Key on-axis potential / field values (electron flight path, r=0)
zvals = [1.2 1.5 2.0 8.0 13.9 14.5 15.1 17.9]; % mm, avoids solid interiors
% NOTE: mphinterp coordinates are interpreted in the geometry's length
% unit (mm here, per geom1.lengthUnit('mm')), not SI meters.
coords = [zeros(1,numel(zvals)); zeros(1,numel(zvals)); zvals];
Vq = mphinterp(model, 'V', 'coord', coords, 'dataset', 'dset1');
Eq = mphinterp(model, 'es.normE', 'coord', coords, 'dataset', 'dset1');

fprintf('\nOn-axis (r=0) potential / field along electron flight path:\n');
fprintf('%10s %12s %14s\n', 'z [mm]', 'V [V]', '|E| [V/m]');
for i = 1:numel(zvals)
    fprintf('%10.2f %12.4f %14.3e\n', zvals(i), Vq(i), Eq(i));
end

model.save(savePath);
fprintf('\nSUCCESS: model saved with electrostatics solution to %s\n', savePath);
end
