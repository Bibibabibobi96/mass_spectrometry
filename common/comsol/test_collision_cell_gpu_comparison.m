function test_collision_cell_gpu_comparison(Nd_val, KE_eV)
% Compares solve time for the collision-cell time-dependent CPT study
% (test_collision_cell.m) using:
%   (a) the default/regular solver configuration (CPU, time-dependent
%       BDF with default iterative linear solver, i1)
%   (b) the direct solver switched to NVIDIA cuDSS (GPU), same pattern
%       validated for the stationary ES solve in gpu_solver_comparison.m
%       (see COMSOL_API.md §4/§7.11) -- applied here to the
%       nested Direct solver under the TIME solver (t1.feature('dDef')),
%       which has the same dDef/fc1 structure as the stationary case.
% Also verifies the two solves give IDENTICAL particle trajectories
% (switching the linear solver backend must not change the physics).

addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
mphstart(2036);
import com.comsol.model.*
import com.comsol.model.util.*

if nargin < 1, Nd_val = 1e24; end
if nargin < 2, KE_eV = 10; end

%% (a) Regular / default solver (CPU, iterative i1)
mA = build_collision_cell('ModelCollCPU', Nd_val, KE_eV);
sol2a = mA.sol('sol2');
fprintf('Regular solver (t1.fc1.linsolver=%s)\n', char(sol2a.feature('t1').feature('fc1').getString('linsolver')));
tic;
sol2a.runAll;
t_regular = toc;
fprintf('Regular (CPU) solve time: %.3f s\n\n', t_regular);
pdA = mphparticle(mA, 'dataset', 'pdset1');
zA = squeeze(pdA.p(:,:,3));
ModelUtil.remove('ModelCollCPU');

%% (b) GPU solver: Direct solver (dDef) with cuDSS
mB = build_collision_cell('ModelCollGPU', Nd_val, KE_eV);
sol2b = mB.sol('sol2');
t1b = sol2b.feature('t1');
dDefb = t1b.feature('dDef');
dDefb.set('linsolver', 'cudss');
t1b.feature('fc1').set('linsolver', 'dDef');
fprintf('GPU solver (t1.fc1.linsolver=%s, dDef.linsolver=%s)\n', ...
    char(t1b.feature('fc1').getString('linsolver')), char(dDefb.getString('linsolver')));
tic;
sol2b.runAll;
t_gpu = toc;
fprintf('GPU (cuDSS) solve time: %.3f s\n\n', t_gpu);
pdB = mphparticle(mB, 'dataset', 'pdset1');
zB = squeeze(pdB.p(:,:,3));
ModelUtil.remove('ModelCollGPU');

maxdiff = max(abs(zA(:) - zB(:)));
fprintf('=== Comparison ===\n');
fprintf('n_particles: %d\n', size(zA,2));
fprintf('Regular (CPU iterative): %.3f s\n', t_regular);
fprintf('GPU (cuDSS direct):      %.3f s\n', t_gpu);
fprintf('Speedup factor: %.2fx\n', t_regular / t_gpu);
fprintf('max |z_CPU - z_GPU| across all particles/times: %.3e mm (should be ~0, floating-point noise only)\n', maxdiff);
end

function model = build_collision_cell(tag, Nd_val, KE_eV)
% Builds the collision-cell geometry + ES + CPT setup (rel1/ef1/coll1),
% solves the ES stationary study, and creates (but does NOT run) the
% time-dependent CPT study/solution -- identical setup to
% test_collision_cell.m, factored out here so both CPU/GPU runs start
% from the exact same unsolved state.
import com.comsol.model.*
import com.comsol.model.util.*

if any(strcmp(cell(ModelUtil.tags()), tag))
    ModelUtil.remove(tag);
end
model = ModelUtil.create(tag);
comp1 = model.component.create('comp1', true);
geom1 = comp1.geom.create('geom1', 3);
geom1.lengthUnit('mm');

p = model.param;
p.set('R_tube', '5[mm]');
p.set('L_cell', '100[mm]');
p.set('t_disk', '1[mm]');
p.set('r_hole', '2[mm]');
p.set('V_in', '10[V]');
p.set('V_out', '0[V]');

geom1.feature.create('elecInO', 'Cylinder');
geom1.feature('elecInO').set('r', 'R_tube');
geom1.feature('elecInO').set('h', 't_disk');
geom1.feature('elecInO').set('pos', {'0' '0' '-t_disk'});
geom1.feature.create('elecInH', 'Cylinder');
geom1.feature('elecInH').set('r', 'r_hole');
geom1.feature('elecInH').set('h', 't_disk+0.4[mm]');
geom1.feature('elecInH').set('pos', {'0' '0' '-t_disk-0.2[mm]'});
geom1.feature.create('elecIn', 'Difference');
geom1.feature('elecIn').selection('input').set({'elecInO'});
geom1.feature('elecIn').selection('input2').set({'elecInH'});

geom1.feature.create('elecOutO', 'Cylinder');
geom1.feature('elecOutO').set('r', 'R_tube');
geom1.feature('elecOutO').set('h', 't_disk');
geom1.feature('elecOutO').set('pos', {'0' '0' 'L_cell'});
geom1.feature.create('elecOutH', 'Cylinder');
geom1.feature('elecOutH').set('r', 'r_hole');
geom1.feature('elecOutH').set('h', 't_disk+0.4[mm]');
geom1.feature('elecOutH').set('pos', {'0' '0' 'L_cell-0.2[mm]'});
geom1.feature.create('elecOut', 'Difference');
geom1.feature('elecOut').selection('input').set({'elecOutO'});
geom1.feature('elecOut').selection('input2').set({'elecOutH'});

geom1.feature.create('cylv', 'Cylinder');
geom1.feature('cylv').set('r', 'R_tube');
geom1.feature('cylv').set('h', 'L_cell+2*t_disk');
geom1.feature('cylv').set('pos', {'0' '0' '-t_disk'});

geom1.feature.create('relvol', 'Cylinder');
geom1.feature('relvol').set('r', '1[mm]');
geom1.feature('relvol').set('h', '1[mm]');
geom1.feature('relvol').set('pos', {'0' '0' '0.5[mm]'});
geom1.feature('relvol').set('selresult', 'on');

for t = {'elecIn','elecOut'}
    geom1.feature(t{1}).set('selresult', 'on');
end
geom1.run;

comp1.selection.create('sel_vac', 'Complement');
comp1.selection('sel_vac').set('input', {'geom1_elecIn_dom','geom1_elecOut_dom'});

mat_vac = model.material.create('mat_vac', 'Common');
mat_vac.selection.named('sel_vac');
mat_vac.propertyGroup('def').set('relpermittivity', {'1'});
for t = {'elecIn','elecOut'}
    matk = model.material.create(sprintf('mat_%s', t{1}), 'Common');
    matk.selection.named(sprintf('geom1_%s_dom', t{1}));
    matk.propertyGroup('def').set('relpermittivity', {'1'});
end

es = comp1.physics.create('es', 'Electrostatics', 'geom1');
es.selection.named('sel_vac');
Vmap = struct('elecIn','V_in','elecOut','V_out');
for t = {'elecIn','elecOut'}
    tagb = sprintf('selb_%s', t{1});
    comp1.selection.create(tagb, 'Adjacent');
    comp1.selection(tagb).set('input', {sprintf('geom1_%s_dom', t{1})});
    potk = es.create(sprintf('pot_%s', t{1}), 'ElectricPotential', 2);
    potk.selection.named(tagb);
    potk.set('V0', Vmap.(t{1}));
end

mesh1 = comp1.mesh.create('mesh1');
mesh1.feature('size').set('hauto', 4);
mesh1.feature.create('ftet1', 'FreeTet');
mesh1.run;

std1 = model.study.create('std1');
std1.create('stat1', 'Stationary');
model.sol.create('sol1');
model.sol('sol1').study('std1');
model.sol('sol1').createAutoSequence('std1');
model.sol('sol1').runAll;

m_kg = 100*1.66054e-27;
cpt = comp1.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
cpt.selection.named('sel_vac');
pp1 = cpt.feature('pp1');
pp1.set('mp', sprintf('%.6e[kg]', m_kg));
pp1.set('Z', '1');

rel1 = cpt.create('rel1', 'Release', 3);
rel1.selection.named('geom1_relvol_dom');
v_beam = sqrt(2*KE_eV*1.602176e-19/m_kg);
rel1.set('v0', {'0' '0' sprintf('%.6e[m/s]', v_beam)});

ef1 = cpt.create('ef1', 'ElectricForce', 3);
ef1.selection.named('sel_vac');
ef1.set('E_src', 'root.comp1.es.Ex');

coll1 = cpt.create('coll1', 'Collisions', 3);
coll1.selection.named('sel_vac');
coll1.set('Nd', sprintf('%.6e[1/m^3]', Nd_val));
coll1.set('CollisionDetection', 'NullCollisionMethodColdGasApproximation');
coll1.set('CountAllCollisions', true);

Tsim = 200e-6;
dtstep = 1e-6;
std2 = model.study.create('std2');
tstep = std2.create('time1', 'Transient');
tstep.set('tlist', sprintf('range(0,%g,%g)', dtstep, Tsim));
tstep.setEntry('activate', 'es', false);
tstep.setEntry('activate', 'cpt', true);
pp1.set('StudyStep', 'std2/time1');
coll1.set('StudyStep', 'std2/time1');

soltags = cell(model.sol.tags());
es_sol_tag = soltags{1};
model.sol.create('sol2');
model.sol('sol2').study('std2');
model.sol('sol2').createAutoSequence('std2');
model.sol('sol2').feature('v1').set('notsolmethod', 'sol');
model.sol('sol2').feature('v1').set('notsol', es_sol_tag);

pdset1 = model.result.dataset.create('pdset1', 'Particle');
pdset1.set('solution', 'sol2');
end
