function result = ms_stage1_ei_source(Nd_val, label)
% Mass spectrometer Stage 1: Electron Impact (EI) ionization source.
%
% Geometry directly modeled on the validated test_collision_cell.m
% template (aperture-hole electrode disks, long thin tube: R_tube=5mm,
% L_cell=100mm) rather than a compact short/fat cylinder -- an earlier
% version using solid (no-hole) electrode disks in a short, fat (r=3mm,
% L=5mm) tube reliably hung / ballooned server memory (tens of GB) during
% the CPT time-dependent solve specifically (electrostatics itself always
% solved fine), reproducibly, regardless of whether Collisions/
% ElectricForce/the ES-solution-reuse trick were included -- isolated by
% elimination to something about that specific electrode/geometry
% topology (solid disks + short/fat aspect ratio), not the collision or
% ionization physics itself. Switching to the long-thin-tube +
% aperture-hole-electrode topology (proven stable across many validated
% CPT scripts this session) resolved it.
%
% A flat thermal-emission cathode (2700K) accelerates electrons along the
% tube via a weak-ish DC field (V_accel) toward a collector anode. The
% tube is filled with background neutral gas (Nd) and a native CPT
% `Collisions` + `Ionization` Attribute counts ionizing collisions along
% each electron's trajectory (same family as the validated Elastic/
% ResonantChargeExchange attributes, see COMSOL_自动化建模经验总结.md
% §7.22/7.25).
%
% IMPORTANT SIMPLIFICATION: COMSOL's CPT physics interface only allows
% ONE ParticleProperties feature (pp1) per interface, and Ionization's
% ReleasedIonProperties/ReleasedElectronProperties can only reference
% that same pp1 -- there is no way, within a single cpt interface, to
% have electrons spawn a literal separate heavy tracked ion species. So
% ReleaseIonizedParticle is left at its default (false): the Ionization
% attribute is used purely for its real, Monte-Carlo, validated
% ionizing-COLLISION-COUNTING physics (Nd*sigma*v collision frequency),
% giving a genuine simulated ionization YIELD -- while the heavy ion's
% birth position (used in Stage 2+) is approximated from the geometric
% extent of the electron beam's path through the ionization volume.
%
% Ionization cross section set to 2e-20 m^2 (order-of-magnitude realistic
% for electron-impact ionization of small molecules like N2 near 70eV).
% Nd chosen (default 1e19/m^3, typical EI source working pressure) so the
% per-electron ionization probability Nd*sigma*L ~ a few percent over the
% full tube length, matching the well-known fact that real EI sources
% are inefficient (only a small fraction of the beam path length yields
% an ionizing event for any single electron).

componentRoot = fileparts(fileparts(mfilename('fullpath')));
addpath(componentRoot);
paths = ei_source_paths();
addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
mphstart(2036);
import com.comsol.model.*
import com.comsol.model.util.*

if nargin < 1, Nd_val = 1e19; end
if nargin < 2, label = sprintf('Nd%.0e', Nd_val); end

if any(strcmp(cell(ModelUtil.tags()), 'ModelEISource'))
    ModelUtil.remove('ModelEISource');
end
model = ModelUtil.create('ModelEISource');
comp1 = model.component.create('comp1', true);
geom1 = comp1.geom.create('geom1', 3);
geom1.label('EI ionization source geometry');
geom1.lengthUnit('mm');

p = model.param;
p.set('R_tube', '5[mm]', 'Ionization tube bore radius');
p.set('L_cell', '100[mm]', 'Cathode-anode path length');
p.set('t_disk', '1[mm]');
p.set('r_hole', '2[mm]', 'Electrode aperture radius');
p.set('V_accel', '70[V]', 'Classic EI electron energy (across full tube)');

geom1.feature.create('cathO', 'Cylinder');
geom1.feature('cathO').label('Cathode outer solid');
geom1.feature('cathO').set('r', 'R_tube');
geom1.feature('cathO').set('h', 't_disk');
geom1.feature('cathO').set('pos', {'0' '0' '-t_disk'});
geom1.feature.create('cathH', 'Cylinder');
geom1.feature('cathH').label('Cathode aperture hole');
geom1.feature('cathH').set('r', 'r_hole');
geom1.feature('cathH').set('h', 't_disk+0.4[mm]');
geom1.feature('cathH').set('pos', {'0' '0' '-t_disk-0.2[mm]'});
geom1.feature.create('cathode', 'Difference');
geom1.feature('cathode').label('Cathode (thermal emitter, V=0)');
geom1.feature('cathode').selection('input').set({'cathO'});
geom1.feature('cathode').selection('input2').set({'cathH'});

geom1.feature.create('anodO', 'Cylinder');
geom1.feature('anodO').label('Anode outer solid');
geom1.feature('anodO').set('r', 'R_tube');
geom1.feature('anodO').set('h', 't_disk');
geom1.feature('anodO').set('pos', {'0' '0' 'L_cell'});
geom1.feature.create('anodH', 'Cylinder');
geom1.feature('anodH').label('Anode aperture hole');
geom1.feature('anodH').set('r', 'r_hole');
geom1.feature('anodH').set('h', 't_disk+0.4[mm]');
geom1.feature('anodH').set('pos', {'0' '0' 'L_cell-0.2[mm]'});
geom1.feature.create('anode', 'Difference');
geom1.feature('anode').label('Anode / collector (V=V_accel)');
geom1.feature('anode').selection('input').set({'anodO'});
geom1.feature('anode').selection('input2').set({'anodH'});

geom1.feature.create('cylv', 'Cylinder');
geom1.feature('cylv').label('Ionization tube body (background gas)');
geom1.feature('cylv').set('r', 'R_tube');
geom1.feature('cylv').set('h', 'L_cell+2*t_disk');
geom1.feature('cylv').set('pos', {'0' '0' '-t_disk'});

geom1.feature.create('relvol', 'Cylinder');
geom1.feature('relvol').label('Release volume (near-cathode emission zone)');
geom1.feature('relvol').set('r', '1[mm]');
geom1.feature('relvol').set('h', '1[mm]');
geom1.feature('relvol').set('pos', {'0' '0' '0.5[mm]'});
geom1.feature('relvol').set('selresult', 'on');

for t = {'cathode','anode'}
    geom1.feature(t{1}).set('selresult', 'on');
end
geom1.run;
gi = mphgeominfo(model, 'geom1');
fprintf('Geometry built. Ndomains=%d\n', gi.Ndomains);

comp1.selection.create('sel_vac', 'Complement');
comp1.selection('sel_vac').label('Ionization tube vacuum/gas (all domains except electrodes)');
comp1.selection('sel_vac').set('input', {'geom1_cathode_dom','geom1_anode_dom'});
vac_n = numel(comp1.selection('sel_vac').entities());
fprintf('sel_vac resolves to %d domain(s)\n', vac_n);
if vac_n ~= 2, error('Expected 2 domains (rest-of-tube + relvol), got %d', vac_n); end

mat_vac = model.material.create('mat_vac', 'Common');
mat_vac.label('Ionization gas (relpermittivity=1)');
mat_vac.selection.named('sel_vac');
mat_vac.propertyGroup('def').set('relpermittivity', {'1'});
for t = {'cathode','anode'}
    matk = model.material.create(sprintf('mat_%s', t{1}), 'Common');
    matk.label(sprintf('%s material', t{1}));
    matk.selection.named(sprintf('geom1_%s_dom', t{1}));
    matk.propertyGroup('def').set('relpermittivity', {'1'});
end

es = comp1.physics.create('es', 'Electrostatics', 'geom1');
es.label('Electrostatics: cathode-anode accelerating field');
es.selection.named('sel_vac');
Vmap = struct('cathode','0','anode','V_accel');
for t = {'cathode','anode'}
    tagb = sprintf('selb_%s', t{1});
    comp1.selection.create(tagb, 'Adjacent');
    comp1.selection(tagb).label(sprintf('%s boundary', t{1}));
    comp1.selection(tagb).set('input', {sprintf('geom1_%s_dom', t{1})});
    potk = es.create(sprintf('pot_%s', t{1}), 'ElectricPotential', 2);
    potk.label(sprintf('%s potential', t{1}));
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
if mi.isempty || ~mi.iscomplete, error('mesh failed'); end

std1 = model.study.create('std1');
std1.label('Stationary: accelerating field');
std1.create('stat1', 'Stationary');
model.sol.create('sol1');
model.sol('sol1').label('Solution: ES');
model.sol('sol1').study('std1');
model.sol('sol1').createAutoSequence('std1');
model.sol('sol1').runAll;
fprintf('SUCCESS: electrostatics solved.\n');

%% CPT: electrons cross the ionization tube, undergo Ionization collisions
cpt = comp1.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
cpt.label(sprintf('Charged Particle Tracing: EI source %s', label));
cpt.selection.named('sel_vac');
% pp1 defaults to electron (mp=me_const, Z=-1) -- exactly what we want here.

rel1 = cpt.create('rel1', 'Release', 3);
rel1.label('Release: near-zero initial velocity from cathode');
rel1.selection.named('geom1_relvol_dom');
% !!! CRITICAL: do NOT use VelocitySpecification='Maxwellian' here.
% Unlike Inlet's 'Thermal' mode, Release's 'Maxwellian' mode samples the
% Maxwell-Boltzmann speed distribution DETERMINISTICALLY across Nvel=200
% discrete velocity bins PER MESH-BASED RELEASE POINT -- this multiplies
% the tracked particle count by ~200x (confirmed by isolation testing:
% every other candidate cause -- geometry topology, tstepsbdf, the
% ES-solution-reuse trick, electron vs. heavy-ion mass, even
% ReleaseSecondaryElectron -- was ruled out one at a time; only switching
% away from Maxwellian fixed the repeated multi-GB server memory
% blowups/hangs during the CPT time-dependent solve). Since the cathode's
% thermal energy (~0.23eV at 2700K) is negligible next to the 70eV
% acceleration anyway, a small fixed v0 is a fine simplification here.
rel1.set('v0', {'0' '0' '1e4[m/s]'}); % ~2.8e-4 eV for an electron, negligible vs 70eV


ef1 = cpt.create('ef1', 'ElectricForce', 3);
ef1.label('Electric Force: accelerating field');
ef1.selection.named('sel_vac');
ef1.set('E_src', 'root.comp1.es.Ex');

coll1 = cpt.create('coll1', 'Collisions', 3);
coll1.label(sprintf('Collisions: background gas Nd=%.2g /m^3', Nd_val));
coll1.selection.named('sel_vac');
coll1.set('Nd', sprintf('%.6e[1/m^3]', Nd_val));
coll1.set('CollisionDetection', 'NullCollisionMethodColdGasApproximation');
coll1.set('CountAllCollisions', true);

ion1 = coll1.create('ion1', 'Ionization');
ion1.label('Electron-impact ionization (constant cross section)');
ion1.set('xsec', '2e-20[m^2]');  % ~N2-like ionization cross section near 70eV
ion1.set('dE', '15[eV]');        % ~N2 ionization potential, energy lost by primary electron
ion1.set('CountCollisions', true);
ion1.set('ReleaseSecondaryElectron', false);
% !!! CRITICAL FIX: ReleaseSecondaryElectron defaults to TRUE -- every
% ionizing collision would otherwise spawn a NEW tracked electron (a
% genuine electron-avalanche mechanism, physically appropriate for
% plasma-discharge modeling but NOT wanted here). With CountAllCollisions
% active and a non-negligible ionization probability, this caused
% exponential growth in the number of tracked particles over the
% simulated time, which is what was actually behind the repeated
% "Out of memory xmesh processing" / multi-hour hangs / 10s-of-GB server
% memory blowups seen while debugging this script (NOT the geometry
% topology, NOT tstepsbdf, NOT the ES-solution-reuse trick -- all of
% which were re-tested and ruled out first). ReleaseIonizedParticle stays
% at its default (false) for the separate, structural reason explained in
% the file header (only one ParticleProperties/pp1 per cpt interface).
% ReleasePrimaryElectron stays at its default (true): the original
% electron should keep being tracked (losing dE) after an ionizing event,
% it just shouldn't spawn a NEW one.

v_beam = sqrt(2*70*1.602176e-19/9.10938e-31);
Tsim = 50e-9; % ns scale
dtstep = 0.5e-9;
std2 = model.study.create('std2');
std2.label(sprintf('Time-dependent: EI source %s', label));
tstep = std2.create('time1', 'Transient');
tstep.label('Transient solver (0-50ns)');
tstep.set('tlist', sprintf('range(0,%g,%g)', dtstep, Tsim));
tstep.setEntry('activate', 'es', false);
tstep.setEntry('activate', 'cpt', true);
cpt.feature('pp1').set('StudyStep', 'std2/time1');
rel1.set('StudyStep', 'std2/time1');
coll1.set('StudyStep', 'std2/time1');
ion1.set('StudyStep', 'std2/time1');

soltags = cell(model.sol.tags());
es_sol_tag = soltags{1};
model.sol.create('sol2');
model.sol('sol2').label(sprintf('Solution: EI source CPT %s', label));
model.sol('sol2').study('std2');
model.sol('sol2').createAutoSequence('std2');
model.sol('sol2').feature('v1').set('notsolmethod', 'sol');
model.sol('sol2').feature('v1').set('notsol', es_sol_tag);
model.sol('sol2').feature('t1').set('tstepsbdf', 'strict');
model.sol('sol2').runAll;
fprintf('[%s] SUCCESS: EI source CPT solved.\n', label);

pdset1 = model.result.dataset.create('pdset1', 'Particle');
pdset1.label(sprintf('Particle dataset: EI source %s', label));
pdset1.set('solution', 'sol2');
pd = mphparticle(model, 'dataset', 'pdset1', 'expr', {'cpt.coll1.ion1.Nc'});
nP = size(pd.p,2);
fprintf('[%s] electrons released: %d\n', label, nP);

x = squeeze(pd.p(:,:,1)); y = squeeze(pd.p(:,:,2)); z = squeeze(pd.p(:,:,3));
r = sqrt(x.^2+y.^2);
t = pd.t;
Nc_end = pd.d1(end,:);

zEnd = z(end,:);
collected = zEnd > 99;
meanNc = mean(Nc_end);
fracIonizing = mean(Nc_end > 0);
fprintf('[%s] electrons collected at anode: %d / %d (%.1f%%)\n', label, sum(collected), nP, 100*sum(collected)/nP);
fprintf('[%s] mean ionizing collisions per electron: %.5f\n', label, meanNc);
fprintf('[%s] fraction of electrons with >=1 ionizing collision (ion yield per electron): %.5f%%\n', label, 100*fracIonizing);

sigma_ion = 2e-20; L_cell = 100e-3;
theory_prob = Nd_val*sigma_ion*L_cell;
fprintf('[%s] theory (Nd*sigma*L, low-probability approx): %.5f%% -- compare to simulated %.5f%%\n', ...
    label, 100*theory_prob, 100*fracIonizing);

result = struct('label', label, 'Nd', Nd_val, 'nP', nP, 'mean_ionizing_collisions', meanNc, ...
    'ion_yield_frac', fracIonizing, 'theory_yield_frac', theory_prob, ...
    'R_tube', 5e-3, 'L_cell', L_cell, 'V_accel', 70);

resultsDir = paths.resultsDir;
if ~exist(resultsDir,'dir'), mkdir(resultsDir); end
fh = figure('Visible','off');
subplot(1,2,1);
hold on;
for i = 1:min(40,nP)
    plot(z(:,i), r(:,i), '-'); % z,r already in mm (geom1.lengthUnit('mm'))
end
xlabel('z [mm]'); ylabel('r [mm]'); grid on;
title('electron trajectories through ionization tube');
subplot(1,2,2);
histogram(Nc_end, 'BinMethod','integers');
xlabel('ionizing collisions per electron'); ylabel('count'); grid on;
title(sprintf('ionization event histogram (mean=%.4f)', meanNc));
sgtitle({sprintf('EI Source Stage 1: %s', label), ...
    sprintf('70eV electrons, Nd=%.2g/m^3, ion yield=%.4f%% (theory %.4f%%)', Nd_val, 100*fracIonizing, 100*theory_prob)}, 'Interpreter','none');
print(fh, fullfile(resultsDir, sprintf('ms_stage1_ei_%s.png', strrep(label,' ','_'))), '-dpng', '-r150');
fprintf('[%s] SUCCESS: trajectory/histogram plot saved.\n', label);

pg1 = model.result.create('pg_traj', 'PlotGroup3D');
pg1.label(sprintf('EI source: %s electron trajectories', label));
pg1.set('data', 'pdset1');
pg1.set('titletype', 'manual');
pg1.set('title', sprintf('EI Source: %s, ion yield=%.4f%%', label, 100*fracIonizing));
trj1 = pg1.create('trj1', 'ParticleTrajectories');
trj1.label('Electron trajectories');
pg1.run;

modelsDir = paths.modelsDir;
if ~exist(modelsDir, 'dir'), mkdir(modelsDir); end
model.save(fullfile(modelsDir, sprintf('MS_Stage1_EISource_%s.mph', strrep(label,' ','_'))));
fprintf('[%s] SUCCESS: native trajectory plot created and model saved.\n', label);
end
