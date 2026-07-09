function result = test_resonant_charge_exchange(Nd_val, KE_eV, label)
% Resonant Charge Exchange collision test: reuses the collision-cell
% geometry (test_collision_cell.m) but attaches a 'ResonantChargeExchange'
% Attribute to the Collisions node instead of 'Elastic'. Physically
% distinct mechanism: in resonant charge exchange, BOTH charge and
% momentum transfer to the (originally neutral, ~stationary) background
% gas atom, leaving a fast NEUTRAL atom (untracked, since CPT only
% follows the charged species) and a newly-charged ion that inherits the
% gas atom's near-zero velocity. So instead of Elastic's gradual
% direction-randomizing scattering, a resonant charge exchange event
% should show up as a near-INSTANTANEOUS drop in the tracked ion's speed
% to nearly zero -- a qualitatively different signature.

addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
mphstart(2036);
import com.comsol.model.*
import com.comsol.model.util.*

if nargin < 1, Nd_val = 1e19; end
if nargin < 2, KE_eV = 10; end
if nargin < 3, label = sprintf('Nd%.0e_KE%geV', Nd_val, KE_eV); end

if any(strcmp(cell(ModelUtil.tags()), 'ModelCEX'))
    ModelUtil.remove('ModelCEX');
end
model = ModelUtil.create('ModelCEX');
comp1 = model.component.create('comp1', true);
geom1 = comp1.geom.create('geom1', 3);
geom1.label('Resonant charge exchange test geometry');
geom1.lengthUnit('mm');

p = model.param;
p.set('R_tube', '5[mm]');
p.set('L_cell', '100[mm]');
p.set('t_disk', '1[mm]');
p.set('r_hole', '2[mm]');
p.set('V_in', '10[V]');
p.set('V_out', '0[V]');

geom1.feature.create('elecInO', 'Cylinder');
geom1.feature('elecInO').set('r', 'R_tube'); geom1.feature('elecInO').set('h', 't_disk');
geom1.feature('elecInO').set('pos', {'0' '0' '-t_disk'});
geom1.feature.create('elecInH', 'Cylinder');
geom1.feature('elecInH').set('r', 'r_hole'); geom1.feature('elecInH').set('h', 't_disk+0.4[mm]');
geom1.feature('elecInH').set('pos', {'0' '0' '-t_disk-0.2[mm]'});
geom1.feature.create('elecIn', 'Difference');
geom1.feature('elecIn').label('Entrance electrode (V_in)');
geom1.feature('elecIn').selection('input').set({'elecInO'});
geom1.feature('elecIn').selection('input2').set({'elecInH'});

geom1.feature.create('elecOutO', 'Cylinder');
geom1.feature('elecOutO').set('r', 'R_tube'); geom1.feature('elecOutO').set('h', 't_disk');
geom1.feature('elecOutO').set('pos', {'0' '0' 'L_cell'});
geom1.feature.create('elecOutH', 'Cylinder');
geom1.feature('elecOutH').set('r', 'r_hole'); geom1.feature('elecOutH').set('h', 't_disk+0.4[mm]');
geom1.feature('elecOutH').set('pos', {'0' '0' 'L_cell-0.2[mm]'});
geom1.feature.create('elecOut', 'Difference');
geom1.feature('elecOut').label('Exit electrode (V_out, grounded)');
geom1.feature('elecOut').selection('input').set({'elecOutO'});
geom1.feature('elecOut').selection('input2').set({'elecOutH'});

geom1.feature.create('cylv', 'Cylinder');
geom1.feature('cylv').label('Gas cell body');
geom1.feature('cylv').set('r', 'R_tube'); geom1.feature('cylv').set('h', 'L_cell+2*t_disk');
geom1.feature('cylv').set('pos', {'0' '0' '-t_disk'});

geom1.feature.create('relvol', 'Cylinder');
geom1.feature('relvol').label('Release volume (entrance beam spot)');
geom1.feature('relvol').set('r', '1[mm]'); geom1.feature('relvol').set('h', '1[mm]');
geom1.feature('relvol').set('pos', {'0' '0' '0.5[mm]'});
geom1.feature('relvol').set('selresult', 'on');

for t = {'elecIn','elecOut'}
    geom1.feature(t{1}).set('selresult', 'on');
end
geom1.run;
gi = mphgeominfo(model, 'geom1');
fprintf('Geometry built. Ndomains=%d\n', gi.Ndomains);

comp1.selection.create('sel_vac', 'Complement');
comp1.selection('sel_vac').label('Vacuum/gas (all domains except electrodes)');
comp1.selection('sel_vac').set('input', {'geom1_elecIn_dom','geom1_elecOut_dom'});
vac_n = numel(comp1.selection('sel_vac').entities());
fprintf('sel_vac resolves to %d domain(s)\n', vac_n);
if vac_n ~= 2, error('Expected 2 vacuum domains, got %d', vac_n); end

mat_vac = model.material.create('mat_vac', 'Common');
mat_vac.selection.named('sel_vac');
mat_vac.propertyGroup('def').set('relpermittivity', {'1'});
for t = {'elecIn','elecOut'}
    matk = model.material.create(sprintf('mat_%s', t{1}), 'Common');
    matk.selection.named(sprintf('geom1_%s_dom', t{1}));
    matk.propertyGroup('def').set('relpermittivity', {'1'});
end

es = comp1.physics.create('es', 'Electrostatics', 'geom1');
es.label('Electrostatics: weak axial push field');
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
mesh1.label('Mesh (hauto=4)');
mesh1.feature('size').set('hauto', 4);
mesh1.feature.create('ftet1', 'FreeTet');
mesh1.run;

std1 = model.study.create('std1');
std1.label('Stationary: ES');
std1.create('stat1', 'Stationary');
model.sol.create('sol1');
model.sol('sol1').label('Solution: ES');
model.sol('sol1').study('std1');
model.sol('sol1').createAutoSequence('std1');
model.sol('sol1').runAll;
fprintf('SUCCESS: electrostatics solved.\n');

m_kg = 100*1.66054e-27;
cpt = comp1.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
cpt.label(sprintf('Charged Particle Tracing: CEX %s', label));
cpt.selection.named('sel_vac');
pp1 = cpt.feature('pp1');
pp1.label('Particle properties: 100amu +1 ion');
pp1.set('mp', sprintf('%.6e[kg]', m_kg));
pp1.set('Z', '1');

rel1 = cpt.create('rel1', 'Release', 3);
rel1.label(sprintf('Release: entrance beam, KE=%g eV', KE_eV));
rel1.selection.named('geom1_relvol_dom');
v_beam = sqrt(2*KE_eV*1.602176e-19/m_kg);
fprintf('beam speed = %.4e m/s (KE=%g eV, 100amu)\n', v_beam, KE_eV);
rel1.set('v0', {'0' '0' sprintf('%.6e[m/s]', v_beam)});

ef1 = cpt.create('ef1', 'ElectricForce', 3);
ef1.label('Electric Force: from weak axial push field');
ef1.selection.named('sel_vac');
ef1.set('E_src', 'root.comp1.es.Ex');

coll1 = cpt.create('coll1', 'Collisions', 3);
coll1.label(sprintf('Collisions: background gas Nd=%.2g /m^3', Nd_val));
coll1.selection.named('sel_vac');
coll1.set('Nd', sprintf('%.6e[1/m^3]', Nd_val));
coll1.set('CollisionDetection', 'NullCollisionMethodColdGasApproximation');
coll1.set('CountAllCollisions', true);

cex1 = coll1.create('cex1', 'ResonantChargeExchange');
cex1.label('Resonant charge exchange (constant cross section)');
cex1.set('CountCollisions', true);
% xsec left at COMSOL default -- matches the same realistic ion-neutral
% cross-section scale used for the Elastic test (see COMSOL_自动化
% 建模经验总结.md §7.22).

Tsim = 200e-6;
dtstep = 1e-6;
std2 = model.study.create('std2');
std2.label(sprintf('Time-dependent: CEX %s', label));
tstep = std2.create('time1', 'Transient');
tstep.label('Transient solver (0-200us)');
tstep.set('tlist', sprintf('range(0,%g,%g)', dtstep, Tsim));
tstep.setEntry('activate', 'es', false);
tstep.setEntry('activate', 'cpt', true);
pp1.set('StudyStep', 'std2/time1');
coll1.set('StudyStep', 'std2/time1');
cex1.set('StudyStep', 'std2/time1');

soltags = cell(model.sol.tags());
es_sol_tag = soltags{1};
model.sol.create('sol2');
model.sol('sol2').label(sprintf('Solution: CEX CPT %s', label));
model.sol('sol2').study('std2');
model.sol('sol2').createAutoSequence('std2');
model.sol('sol2').feature('v1').set('notsolmethod', 'sol');
model.sol('sol2').feature('v1').set('notsol', es_sol_tag);
model.sol('sol2').feature('t1').set('tstepsbdf', 'strict');
model.sol('sol2').runAll;
fprintf('[%s] SUCCESS: CEX collision cell CPT solved.\n', label);

pdset1 = model.result.dataset.create('pdset1', 'Particle');
pdset1.label(sprintf('Particle dataset: CEX %s', label));
pdset1.set('solution', 'sol2');
pd = mphparticle(model, 'dataset', 'pdset1', 'expr', {'cpt.coll1.cex1.Nc'});
nP = size(pd.p,2);
fprintf('[%s] particles released: %d\n', label, nP);

x = squeeze(pd.p(:,:,1)); y = squeeze(pd.p(:,:,2)); z = squeeze(pd.p(:,:,3));
vx = squeeze(pd.v(:,:,1)); vy = squeeze(pd.v(:,:,2)); vz = squeeze(pd.v(:,:,3));
speed = sqrt(vx.^2+vy.^2+vz.^2);
t = pd.t;
Nc_end = pd.d1(end,:);
meanNc = mean(Nc_end);
fprintf('[%s] mean cumulative charge-exchange events per particle: %.3f\n', label, meanNc);

% Look for the qualitative CEX signature: a near-instantaneous speed
% drop (>90% loss in a single solver step) somewhere along each particle
% trajectory, contrasted against Elastic collisions' gradual scattering.
speedDropFrac = (speed(1:end-1,:) - speed(2:end,:)) ./ speed(1:end-1,:);
nBigDrops = sum(speedDropFrac > 0.9, 1, 'omitnan');
fprintf('[%s] particles showing a >90%% single-step speed drop (CEX signature): %d / %d\n', ...
    label, sum(nBigDrops>0), nP);

result = struct('label', label, 'Nd', Nd_val, 'KE_eV', KE_eV, 'nP', nP, ...
    'mean_cex_events', meanNc, 'n_bigdrop_particles', sum(nBigDrops>0));

resultsDir = 'C:\Users\Liao\PycharmProjects\PythonProject\comsol_results';
if ~exist(resultsDir,'dir'), mkdir(resultsDir); end
fh = figure('Visible','off');
subplot(1,2,1);
hold on;
for i = 1:min(20,nP)
    plot(t*1e6, speed(:,i), '-');
end
xlabel('t [\mus]'); ylabel('speed [m/s]'); grid on;
title('speed vs time (look for sudden drops = CEX events)');
subplot(1,2,2);
hold on;
for i = 1:min(20,nP)
    plot(z(:,i), sqrt(x(:,i).^2+y(:,i).^2), '-');
end
xlabel('z [mm]'); ylabel('r [mm]'); grid on;
title('radial drift vs axial position');
sgtitle({sprintf('Resonant Charge Exchange: %s', label), ...
    sprintf('100amu +1 ion, KE=%g eV, Nd=%.2g /m^3, mean CEX events=%.2f', KE_eV, Nd_val, meanNc)}, 'Interpreter', 'none');
print(fh, fullfile(resultsDir, sprintf('cex_%s.png', strrep(label,' ','_'))), '-dpng', '-r150');
fprintf('[%s] SUCCESS: trajectory plot saved.\n', label);

pg1 = model.result.create('pg_traj', 'PlotGroup3D');
pg1.label(sprintf('CEX: %s trajectory plot', label));
pg1.set('data', 'pdset1');
pg1.set('titletype', 'manual');
pg1.set('title', sprintf('Resonant Charge Exchange: %s, mean events=%.2f', label, meanNc));
trj1 = pg1.create('trj1', 'ParticleTrajectories');
trj1.label(sprintf('Ion trajectories (%s)', label));
pg1.run;

modelsDir = 'C:\Users\Liao\PycharmProjects\PythonProject\comsol_models';
if ~exist(modelsDir, 'dir'), mkdir(modelsDir); end
model.save(fullfile(modelsDir, sprintf('CEX_%s.mph', strrep(label,' ','_'))));
fprintf('[%s] SUCCESS: native trajectory plot created and model saved.\n', label);
end
