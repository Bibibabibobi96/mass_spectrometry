function test_multipole_es(Npoles)
% Loads the N-pole rod array geometry, assigns alternating +/-V_rf to
% adjacent rods (valid for even N), solves electrostatics with a unit RF
% amplitude, and checks: (a) potential/field ~0 at the exact center
% (true for an ideal balanced multipole), (b) field magnitude growing
% with radius along a line toward a rod (multipole field scales like
% r^(N/2-1), e.g. quadrupole E~r linear, to sanity-check pole order).
if nargin < 1
    Npoles = 4;
end
addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
mphstart(2036);
import com.comsol.model.*
import com.comsol.model.util.*

tag = sprintf('ModelPole%d', Npoles);
modelPath = sprintf('C:\\Users\\Liao\\PycharmProjects\\PythonProject\\comsol_models\\common\\Multipole%d.mph', Npoles);
if any(strcmp(cell(ModelUtil.tags()), tag))
    ModelUtil.remove(tag);
end
model = ModelUtil.load(tag, modelPath);
comp1 = model.component('comp1');
geom1 = comp1.geom('geom1');

rodtags = arrayfun(@(k) sprintf('rod%d',k), 1:Npoles, 'UniformOutput', false);
for k = 1:Npoles
    geom1.feature(rodtags{k}).set('selresult', 'on');
end
geom1.feature('cylv').set('selresult', 'on');
geom1.run;

sel_rods = cellfun(@(t) sprintf('geom1_%s_dom', t), rodtags, 'UniformOutput', false);
comp1.selection.create('sel_vac', 'Complement');
comp1.selection('sel_vac').label('Vacuum (all domains except rods)');
comp1.selection('sel_vac').set('input', sel_rods);
vac_n = numel(comp1.selection('sel_vac').entities());
fprintf('sel_vac resolves to %d domain(s)\n', vac_n);
if vac_n ~= 2
    error('Expected 2 vacuum domains (rest-of-vacuum + relvol), got %d', vac_n);
end
fprintf('geom1_relvol_dom resolves to %d domain(s)\n', numel(comp1.selection('geom1_relvol_dom').entities()));

% Boundary selections + materials + ElectricPotential per rod, alternating sign
mat_vac = model.material.create('mat_vac', 'Common');
mat_vac.label('Vacuum (relpermittivity=1)');
mat_vac.selection.named('sel_vac');
mat_vac.propertyGroup('def').set('relpermittivity', {'1'});

es = comp1.physics.create('es', 'Electrostatics', 'geom1');
es.label(sprintf('Electrostatics: %d-pole RF field (unit amplitude)', Npoles));
es.selection.named('sel_vac');

for k = 1:Npoles
    selb = sprintf('selb_rod%d', k);
    comp1.selection.create(selb, 'Adjacent');
    comp1.selection(selb).label(sprintf('Rod %d boundary', k));
    comp1.selection(selb).set('input', {sel_rods{k}});

    matk = sprintf('mat_rod%d', k);
    mat_k = model.material.create(matk, 'Common');
    mat_k.label(sprintf('Rod %d material', k));
    mat_k.selection.named(sel_rods{k});
    mat_k.propertyGroup('def').set('relpermittivity', {'1'});

    potk = es.create(sprintf('pot%d',k), 'ElectricPotential', 2);
    if mod(k,2) == 1
        potk.label(sprintf('Rod %d potential (+V_rf)', k));
        potk.selection.named(selb);
        potk.set('V0', 'V_rf');
    else
        potk.label(sprintf('Rod %d potential (-V_rf)', k));
        potk.selection.named(selb);
        potk.set('V0', '-V_rf');
    end
end

mesh1 = comp1.mesh.create('mesh1');
mesh1.label('Mesh (hauto=3, coarsened at relvol)');
mesh1.feature('size').set('hauto', 3);
% Locally coarsen the mesh in the small release sub-volume specifically
% -- the global hauto=3 mesh alone still produced ~2000-6500 release
% points in 'relvol' (way more than needed for a clean trajectory plot);
% a domain-specific coarse Size feature cuts that down substantially
% without affecting field-resolution accuracy anywhere else.
sz_relvol = mesh1.feature.create('sz_relvol', 'Size');
sz_relvol.label('Coarse mesh override: release volume');
sz_relvol.selection.geom('geom1', 3);
sz_relvol.selection.named('geom1_relvol_dom');
sz_relvol.set('hauto', 9);
mesh1.feature.create('ftet1', 'FreeTet');
mesh1.run;
mi = mphmeshstats(model, 'mesh1');
fprintf('mesh: isempty=%d iscomplete=%d\n', mi.isempty, mi.iscomplete);
if mi.isempty || ~mi.iscomplete
    error('Mesh failed.');
end

std1 = model.study.create('std1');
std1.label(sprintf('Stationary: %d-pole electrostatics', Npoles));
std1.create('stat1', 'Stationary');
model.sol.create('sol1');
model.sol('sol1').label(sprintf('Solution: %d-pole ES', Npoles));
model.sol('sol1').study('std1');
model.sol('sol1').createAutoSequence('std1');
model.sol('sol1').runAll;
fprintf('SUCCESS: electrostatics solved.\n');

% Check field near center (should be ~0 at exact axis for ideal balanced
% multipole) and growth of |E| along a radial line toward rod 1 (angle=0)
zmid = 10; % mm, mid-length
rvals = [0 0.5 1 2 3];
coords = zeros(3, numel(rvals));
for i=1:numel(rvals)
    coords(:,i) = [rvals(i); 0; zmid];
end
Vq = mphinterp(model, 'V', 'coord', coords, 'dataset', 'dset1', 'matherr', 'off');
Eq = mphinterp(model, 'es.normE', 'coord', coords, 'dataset', 'dset1', 'matherr', 'off');
fprintf('\nOn the x-axis (toward rod 1), z=%.0fmm:\n', zmid);
fprintf('%8s %12s %14s\n', 'r[mm]', 'V[V]', '|E|[V/m]');
for i=1:numel(rvals)
    fprintf('%8.2f %12.4f %14.4e\n', rvals(i), Vq(i), Eq(i));
end

model.save(modelPath);
fprintf('SUCCESS: model saved.\n');
end
