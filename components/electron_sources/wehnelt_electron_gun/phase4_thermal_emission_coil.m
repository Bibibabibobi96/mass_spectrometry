function phase4_thermal_emission_coil()
% Phase 4: same coil-filament electron gun as phase3_particle_tracing_coil.m,
% but electrons are released with a proper thermal (Maxwell-Boltzmann)
% initial velocity distribution at a typical tungsten filament operating
% temperature (~2700 K, the standard value used for thermionic tungsten
% hairpin/coil emitters - balances emission current against wire
% evaporation lifetime), instead of the v0=0 baseline used in Phase 3.
%
% COMSOL's Inlet feature has a built-in VelocitySpecification='Thermal'
% mode (discovered via the deliberate-bad-value error-message technique:
% valid values are "SpecifyVelocity"/"SpecifyMomentum"/
% "SpecifyKineticEnergy"/"Thermal") that samples a proper flux-weighted
% Maxwellian at temperature T -- this is used here instead of hand-picking
% a single equivalent speed.

componentRoot = fileparts(mfilename('fullpath'));
addpath(componentRoot);
paths = egun_paths();
addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
mphstart(2036);
import com.comsol.model.*
import com.comsol.model.util.*

modelPath = fullfile(paths.modelWorkspaceDir, 'ElectronGun_Coil_ES.mph');
savePath  = fullfile(paths.modelWorkspaceDir, 'ElectronGun_Coil_Thermal_CPT.mph');
if any(strcmp(cell(ModelUtil.tags()), 'Model'))
    ModelUtil.remove('Model');
end
model = ModelUtil.load('Model', modelPath);
comp1 = model.component('comp1');

sel_vac  = 'sel_vac';

%% Physics: Charged Particle Tracing, restricted to the vacuum domain
cpt = comp1.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
cpt.selection.named(sel_vac);

inl1 = cpt.create('inl1', 'Inlet', 2);
inl1.label('Cathode Coil Emission (Thermal)');
inl1.selection.named('selb_cath');
inl1.set('N', 1);
inl1.set('VelocitySpecification', 'Thermal');
inl1.set('T_src', 'userdef');
inl1.set('T', '2700[K]');   % typical tungsten filament operating temperature

%% Electric Force
ef1 = cpt.create('ef1', 'ElectricForce', 3);
ef1.selection.named(sel_vac);
ef1.set('E_src', 'root.comp1.es.Ex');

%% Study 2: time-dependent particle trace
std2 = model.study.create('std2');
std2.label('Particle Tracing Study (Thermal)');
tstep = std2.create('time1', 'Transient');
tstep.set('tlist', 'range(0,0.1[ns],40[ns])');
tstep.setEntry('activate', 'es', false);
tstep.setEntry('activate', 'cpt', true);

model.sol.create('sol2');
model.sol('sol2').study('std2');
model.sol('sol2').createAutoSequence('std2');
model.sol('sol2').feature('v1').set('notsolmethod', 'sol');
model.sol('sol2').feature('v1').set('notsol', 'sol1');
model.sol('sol2').runAll;

fprintf('SUCCESS: Particle tracing (thermal emission) solved.\n');

%% Results: trajectory plot
resultsDir = paths.resultsDir;
if ~exist(resultsDir, 'dir')
    mkdir(resultsDir);
end
try
    pdset1 = model.result.dataset.create('pdset1', 'Particle');
    pdset1.set('solution', 'sol2');
    pg3 = model.result.create('pg_traj', 'PlotGroup3D');
    pg3.label('Electron Trajectories (Thermal)');
    pg3.set('data', 'pdset1');
    tr1 = pg3.create('traj1', 'ParticleTrajectories');
    tr1.set('data', 'pdset1');
    imgT = model.result.export.create('imgT', 'Image');
    imgT.set('plotgroup', 'pg_traj');
    imgT.set('pngfilename', fullfile(resultsDir, 'electron_trajectories_thermal.png'));
    imgT.set('width', 1200);
    imgT.set('height', 900);
    imgT.run;
    fprintf('SUCCESS: Trajectory image exported.\n');
catch ME
    fprintf('WARNING: Trajectory plot/export failed: %s\n', ME.message);
end

%% Final stats (NaN-aware: absorbed particles, incl. near-instant
% inter-turn self-absorption, show up as NaN at later times -- see
% COMSOL_自动化建模经验总结.md CPT section)
pd = mphparticle(model, 'dataset', 'pdset1');
n_released = size(pd.p, 2);
qx_end = pd.p(end,:,1); qy_end = pd.p(end,:,2); qz_end = pd.p(end,:,3);
valid = ~isnan(qz_end);
fprintf('\nParticles released: %d\n', n_released);
fprintf('Valid (non-NaN) at t=40ns: %d (%.1f%%)  |  lost (NaN, self-absorbed): %d (%.1f%%)\n', ...
    sum(valid), 100*sum(valid)/n_released, sum(~valid), 100*sum(~valid)/n_released);

coords = [qx_end(valid); qy_end(valid); qz_end(valid)];
KE = mphinterp(model, 'V', 'coord', coords, 'dataset', 'dset1', 'matherr', 'off');
n_arrived = sum(KE > 60 & KE < 75);
fprintf('KE[eV] among valid survivors: min=%.3f max=%.3f mean=%.3f median=%.3f (n=%d)\n', ...
    min(KE), max(KE), mean(KE), median(KE), numel(KE));
fprintf('Reached ~70eV band (passed anode): %d / %d released (%.1f%%)\n', ...
    n_arrived, n_released, 100*n_arrived/n_released);

% Initial speed sanity check: mean should correspond to ~kT thermal spread
% (kT at 2700K = 8.617e-5*2700 = 0.2327 eV -> v_th = sqrt(2*kT*e/m) ~ 2.86e5 m/s)
vx0 = pd.v(1,:,1); vy0 = pd.v(1,:,2); vz0 = pd.v(1,:,3);
speed0 = sqrt(vx0.^2+vy0.^2+vz0.^2);
fprintf('\nInitial speed at t=0: min=%.3e max=%.3e mean=%.3e m/s (theory v_th @2700K ~ 2.86e5 m/s)\n', ...
    min(speed0), max(speed0), mean(speed0));

model.save(savePath);
fprintf('\nSUCCESS: model saved to %s\n', savePath);
end
