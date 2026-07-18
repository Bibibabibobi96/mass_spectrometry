function result = test_collision_cell(Nd_val, KE_eV, label)
% Collision cell / ion source: a straight cylindrical tube filled with
% background gas (CPT 'Collisions' feature), with a small axial DC field
% to sweep ions through (like a real CID/collision-cell drift field), no
% radial confinement -- so collision-induced transverse diffusion can
% genuinely knock ions into the tube wall, giving a physically meaningful
% "ion loss rate" alongside the collision rate itself.
%
% Nd_val: background gas number density [1/m^3] (COMSOL default 1e20).
% KE_eV: ion injection kinetic energy [eV].

commonDir = fileparts(mfilename('fullpath'));
addpath(commonDir);
paths = common_artifact_paths();
addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
mphstart(2036);
import com.comsol.model.*
import com.comsol.model.util.*

if nargin < 1, Nd_val = 1e20; end
if nargin < 2, KE_eV = 10; end
if nargin < 3, label = sprintf('Nd%.0e_KE%geV', Nd_val, KE_eV); end

if any(strcmp(cell(ModelUtil.tags()), 'ModelCollCell'))
    ModelUtil.remove('ModelCollCell');
end
model = ModelUtil.create('ModelCollCell');
comp1 = model.component.create('comp1', true);
geom1 = comp1.geom.create('geom1', 3);
geom1.label('Collision cell geometry');
geom1.lengthUnit('mm');

p = model.param;
p.set('R_tube', '5[mm]', 'Cell bore radius');
p.set('L_cell', '100[mm]', 'Cell length');
p.set('t_disk', '1[mm]');
p.set('r_hole', '2[mm]', 'Entrance/exit aperture radius');
p.set('V_in', '10[V]', 'Entrance electrode (weak axial push field)');
p.set('V_out', '0[V]', 'Exit electrode (grounded)');

% Entrance electrode (aperture disk, weak push field)
geom1.feature.create('elecInO', 'Cylinder');
geom1.feature('elecInO').label('Entrance electrode outer solid');
geom1.feature('elecInO').set('r', 'R_tube');
geom1.feature('elecInO').set('h', 't_disk');
geom1.feature('elecInO').set('pos', {'0' '0' '-t_disk'});
geom1.feature.create('elecInH', 'Cylinder');
geom1.feature('elecInH').label('Entrance electrode aperture hole');
geom1.feature('elecInH').set('r', 'r_hole');
geom1.feature('elecInH').set('h', 't_disk+0.4[mm]');
geom1.feature('elecInH').set('pos', {'0' '0' '-t_disk-0.2[mm]'});
geom1.feature.create('elecIn', 'Difference');
geom1.feature('elecIn').label('Entrance electrode (V_in)');
geom1.feature('elecIn').selection('input').set({'elecInO'});
geom1.feature('elecIn').selection('input2').set({'elecInH'});

% Exit electrode (aperture disk, grounded)
geom1.feature.create('elecOutO', 'Cylinder');
geom1.feature('elecOutO').label('Exit electrode outer solid');
geom1.feature('elecOutO').set('r', 'R_tube');
geom1.feature('elecOutO').set('h', 't_disk');
geom1.feature('elecOutO').set('pos', {'0' '0' 'L_cell'});
geom1.feature.create('elecOutH', 'Cylinder');
geom1.feature('elecOutH').label('Exit electrode aperture hole');
geom1.feature('elecOutH').set('r', 'r_hole');
geom1.feature('elecOutH').set('h', 't_disk+0.4[mm]');
geom1.feature('elecOutH').set('pos', {'0' '0' 'L_cell-0.2[mm]'});
geom1.feature.create('elecOut', 'Difference');
geom1.feature('elecOut').label('Exit electrode (V_out, grounded)');
geom1.feature('elecOut').selection('input').set({'elecOutO'});
geom1.feature('elecOut').selection('input2').set({'elecOutH'});

% Vacuum/gas-filled cell body
geom1.feature.create('cylv', 'Cylinder');
geom1.feature('cylv').label('Gas cell body (bounding cylinder)');
geom1.feature('cylv').set('r', 'R_tube');
geom1.feature('cylv').set('h', 'L_cell+2*t_disk');
geom1.feature('cylv').set('pos', {'0' '0' '-t_disk'});

% Small dedicated release volume just inside the entrance
geom1.feature.create('relvol', 'Cylinder');
geom1.feature('relvol').label('Release volume (entrance beam spot)');
geom1.feature('relvol').set('r', '1[mm]');
geom1.feature('relvol').set('h', '1[mm]');
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
if vac_n ~= 2
    error('Expected 2 vacuum domains (rest-of-cell + relvol), got %d', vac_n);
end
fprintf('geom1_relvol_dom resolves to %d domain(s)\n', numel(comp1.selection('geom1_relvol_dom').entities()));

mat_vac = model.material.create('mat_vac', 'Common');
mat_vac.label('Gas fill (relpermittivity=1)');
mat_vac.selection.named('sel_vac');
mat_vac.propertyGroup('def').set('relpermittivity', {'1'});
elecLabels = struct('elecIn','Entrance electrode material','elecOut','Exit electrode material');
for t = {'elecIn','elecOut'}
    matk = model.material.create(sprintf('mat_%s', t{1}), 'Common');
    matk.label(elecLabels.(t{1}));
    matk.selection.named(sprintf('geom1_%s_dom', t{1}));
    matk.propertyGroup('def').set('relpermittivity', {'1'});
end

es = comp1.physics.create('es', 'Electrostatics', 'geom1');
es.label('Electrostatics: weak axial push field');
es.selection.named('sel_vac');
Vmap = struct('elecIn','V_in','elecOut','V_out');
potLabels = struct('elecIn','Entrance potential (V_in)','elecOut','Exit potential (V_out, grounded)');
for t = {'elecIn','elecOut'}
    tagb = sprintf('selb_%s', t{1});
    comp1.selection.create(tagb, 'Adjacent');
    comp1.selection(tagb).label(sprintf('%s boundary', t{1}));
    comp1.selection(tagb).set('input', {sprintf('geom1_%s_dom', t{1})});
    potk = es.create(sprintf('pot_%s', t{1}), 'ElectricPotential', 2);
    potk.label(potLabels.(t{1}));
    potk.selection.named(tagb);
    potk.set('V0', Vmap.(t{1}));
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
std1.label('Stationary: collision cell electrostatics');
std1.create('stat1', 'Stationary');
model.sol.create('sol1');
model.sol('sol1').label('Solution: collision cell ES');
model.sol('sol1').study('std1');
model.sol('sol1').createAutoSequence('std1');
model.sol('sol1').runAll;
fprintf('SUCCESS: electrostatics solved.\n');

zvals = [0 25 50 75 100];
coords = [zeros(1,numel(zvals)); zeros(1,numel(zvals)); zvals];
Vq = mphinterp(model, 'V', 'coord', coords, 'dataset', 'dset1', 'matherr', 'off');
fprintf('\nOn-axis potential (weak push field):\n');
for i=1:numel(zvals)
    fprintf('  z=%6.1fmm  V=%9.4fV\n', zvals(i), Vq(i));
end

%% CPT: ion beam with background-gas collisions
m_kg = 100*1.66054e-27; % 100amu, +1 -- consistent with the rest of the session
cpt = comp1.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
cpt.label(sprintf('Charged Particle Tracing: collision cell %s', label));
cpt.selection.named('sel_vac');

pp1 = cpt.feature('pp1');
pp1.label('Particle properties: 100amu +1 ion');
pp1.set('mp', sprintf('%.6e[kg]', m_kg));
pp1.set('Z', '1');

rel1 = cpt.create('rel1', 'Release', 3);
rel1.label(sprintf('Release: entrance beam, KE=%g eV', KE_eV));
rel1.selection.named('geom1_relvol_dom');
v_beam = sqrt(2*KE_eV*1.602176e-19/m_kg);
fprintf('\nBeam speed = %.4e m/s (KE=%g eV, 100amu)\n', v_beam, KE_eV);
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
% mg/T left at COMSOL defaults (Ar mass, 293.15K) -- see
% COMSOL_API.md under wall, termination, and collisions.

% !!! CRITICAL FIX: 'Collisions' is just a container (Nd/T/detection
% method) -- it has ZERO effect on particle motion unless at least one
% collision-TYPE Attribute (Elastic, Resonant Charge Exchange, etc.) is
% attached under it. That attribute is where the actual cross section
% (xsec) is defined; without one, the cross section is implicitly zero,
% which is exactly why Nd from 1e20 to 1e28/m^3 all produced bit-identical
% trajectories. Confirmed against COMSOL's own 'ion_drift_velocity_
% benchmark' example (Particle Tracing Module application library).
elastic1 = coll1.create('elastic1', 'Elastic');
elastic1.label('Elastic collisions (constant cross section)');
elastic1.set('CountCollisions', true);
% xsec left at COMSOL default (3e-19 m^2, a realistic ion-neutral elastic
% cross section) -- NumberDensitySpecification/MolarMassSpecification
% default to 'FromParent' so Nd/mg above are inherited automatically.
% (StudyStep set later, once std2/time1 exists -- see below.)

Tsim = 200e-6; % 200us -- generous given the weak push field and possible collisions
dtstep = 1e-6;
std2 = model.study.create('std2');
std2.label(sprintf('Time-dependent: collision cell %s', label));
tstep = std2.create('time1', 'Transient');
tstep.label('Transient solver (0-200us)');
tstep.set('tlist', sprintf('range(0,%g,%g)', dtstep, Tsim));
tstep.setEntry('activate', 'es', false);
tstep.setEntry('activate', 'cpt', true);

% !!! CRITICAL: pp1/coll1 (and CPT sub-features generally) carry their
% OWN 'StudyStep' property recording which study step they're considered
% "live" for -- this defaulted to 'std1/stat1' (the stationary ES study
% that existed when they were created), NOT the new time-dependent
% std2/time1 that actually runs the particle/collision solve. Left
% unfixed, Collisions had ZERO measurable effect on particle trajectories
% even at absurd gas densities (confirmed empirically: Nd=1e20 through
% Nd=1e28/m^3, both collision-detection modes, all gave bit-identical
% trajectories) because the feature wasn't bound to the study actually
% being solved.
pp1.set('StudyStep', 'std2/time1');
coll1.set('StudyStep', 'std2/time1');
elastic1.set('StudyStep', 'std2/time1');

soltags = cell(model.sol.tags());
es_sol_tag = soltags{1};
model.sol.create('sol2');
model.sol('sol2').label(sprintf('Solution: collision cell CPT %s', label));
model.sol('sol2').study('std2');
model.sol('sol2').createAutoSequence('std2');
model.sol('sol2').feature('v1').set('notsolmethod', 'sol');
model.sol('sol2').feature('v1').set('notsol', es_sol_tag);
% !!! IMPORTANT: default 'tstepsbdf'='free' lets the adaptive BDF solver
% take internal steps MUCH larger than the requested output 'tlist'
% (which only controls save points, not integration granularity) --
% collision probability is evaluated once per internal solver step, so
% with 'free' stepping the solver can silently skip almost all collision
% opportunities even at absurdly high gas density (confirmed empirically:
% Nd=1e20 and Nd=1e24 gave bit-identical trajectories). 'strict' forces
% the solver to actually stop at every requested tlist point.
model.sol('sol2').feature('t1').set('tstepsbdf', 'strict');
model.sol('sol2').runAll;
fprintf('[%s] SUCCESS: collision cell CPT solved.\n', label);

pdset1 = model.result.dataset.create('pdset1', 'Particle');
pdset1.label(sprintf('Particle dataset: collision cell %s', label));
pdset1.set('solution', 'sol2');
% mphparticle's 'expr' option extracts additional per-particle derived
% quantities alongside position/velocity -- this is the ONLY method that
% worked for the collision-count variable: mphinterp flatly refuses
% particle datasets, and mpheval reports "Undefined variable" for the
% exact same (correct) expression despite matching COMSOL's own
% 'ion_drift_velocity_benchmark' example's naming pattern exactly
% (<physics>.<collisions_tag>.<attribute_tag>.Nc).
pd = mphparticle(model, 'dataset', 'pdset1', 'expr', {'cpt.coll1.elastic1.Nc'});
nP = size(pd.p,2);
fprintf('[%s] particles released: %d\n', label, nP);

x = squeeze(pd.p(:,:,1)); y = squeeze(pd.p(:,:,2)); z = squeeze(pd.p(:,:,3));
r = sqrt(x.^2+y.^2);
t = pd.t;

zEnd = z(end,:); rEnd = r(end,:);
transmitted = zEnd > 99;   % reached past the exit electrode
lostToWall = rEnd > 4.9 & zEnd < 99;  % stopped at the tube wall before exiting
stillInTransit = ~transmitted & ~lostToWall;

fprintf('\n=== %s: Nd=%.3g /m^3, KE=%g eV ===\n', label, Nd_val, KE_eV);
fprintf('transmitted (reached exit): %d / %d (%.1f%%)\n', sum(transmitted), nP, 100*sum(transmitted)/nP);
fprintf('lost to tube wall: %d / %d (%.1f%%)\n', sum(lostToWall), nP, 100*sum(lostToWall)/nP);
fprintf('still in transit at t_end: %d / %d (%.1f%%)\n', sum(stillInTransit), nP, 100*sum(stillInTransit)/nP);

% Real per-particle cumulative collision count (see mphparticle 'expr'
% call above). Nc freezes once a particle is absorbed by the wall (Wall
% condition default = Freeze), so mean Nc at t_end reflects "collisions
% before loss/exit", not a full 200us exposure for every particle.
Nc_all = pd.d1; % [nTimes x nParticles]
Nc_end = Nc_all(end, :);
meanNc = mean(Nc_end);
fprintf('mean cumulative collisions per particle (cpt.coll1.elastic1.Nc @ t_end): %.3f\n', meanNc);

% Theoretical collision rate (kinetic theory): nu = Nd*sigma*v_rel. Cold-
% gas-approximation ignores background gas thermal motion, so v_rel is
% just the (changing) ion speed -- use the INITIAL beam speed as a rough
% reference scale (ion decelerates/randomizes over the transit, so this
% is only an order-of-magnitude check, not an exact prediction).
xsec_default = 3e-19; % m^2, COMSOL's default Elastic cross section
nu_theory = Nd_val*xsec_default*v_beam;
meanFreeTime_theory = 1/nu_theory;
fprintf('theoretical collision frequency (Nd*sigma*v_beam) = %.3e /s (mean free time %.3e s)\n', ...
    nu_theory, meanFreeTime_theory);
fprintf('  expected collisions over simulated %.0fus: %.3f (order-of-magnitude check vs measured %.3f above)\n', ...
    Tsim*1e6, nu_theory*Tsim, meanNc);

result = struct('label', label, 'Nd', Nd_val, 'KE_eV', KE_eV, 'nP', nP, ...
    'transmitted_frac', sum(transmitted)/nP, 'lost_frac', sum(lostToWall)/nP, ...
    'mean_collisions', meanNc, 'nu_theory', nu_theory);

resultsDir = paths.resultsDir;
if ~exist(resultsDir,'dir'), mkdir(resultsDir); end
fh = figure('Visible','off');
subplot(1,2,1);
hold on;
for i = 1:min(20,nP)
    plot(z(:,i), r(:,i), '-');
end
xlabel('z [mm]'); ylabel('r [mm]'); grid on;
yline(5, 'k--');
title('radial drift vs axial position');
subplot(1,2,2);
hold on;
for i = 1:min(20,nP)
    plot(t*1e6, z(:,i), '-');
end
xlabel('t [\mus]'); ylabel('z [mm]'); grid on;
title('axial position vs time');
sgtitle({sprintf('Collision cell: %s', label), ...
    sprintf('100amu +1 ion, KE=%g eV, Nd=%.2g /m^3, V_{in}=10V push field', KE_eV, Nd_val)}, 'Interpreter', 'none');
print(fh, fullfile(resultsDir, sprintf('collision_cell_%s.png', strrep(label,' ','_'))), '-dpng', '-r150');
fprintf('[%s] SUCCESS: trajectory plot saved.\n', label);

pg1 = model.result.create('pg_traj', 'PlotGroup3D');
pg1.label(sprintf('Collision cell: %s trajectory plot', label));
pg1.set('data', 'pdset1');
pg1.set('titletype', 'manual');
pg1.set('title', sprintf('Collision cell: %gamu +1 ion, KE=%g eV, Nd=%.2g /m^3', 100, KE_eV, Nd_val));
trj1 = pg1.create('trj1', 'ParticleTrajectories');
trj1.label(sprintf('Ion trajectories (%s)', label));
pg1.run;

modelsDir = paths.modelsDir;
if ~exist(modelsDir, 'dir'), mkdir(modelsDir); end
model.save(fullfile(modelsDir, sprintf('CollisionCell_%s.mph', strrep(label,' ','_'))));
fprintf('[%s] SUCCESS: native trajectory plot created and model saved.\n', label);
end
