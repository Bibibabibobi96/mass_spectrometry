function phase3_particle_tracing_coil()
% Phase 3 (coil variant): charged particle tracing on the coil-filament
% electron gun. Same physics setup as phase3_particle_tracing.m (all
% fixes from the straight-cylinder debugging session applied from the
% start: notsolmethod/notsol field reuse, mphparticle for data
% extraction), electrons released from the FULL coil wire surface at
% ~0 eV (thermal energy added separately in phase4).

scriptDir = fileparts(mfilename('fullpath'));
componentRoot = fileparts(fileparts(scriptDir));
addpath(componentRoot);
paths = egun_paths();
addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
mphstart(2036);
import com.comsol.model.*
import com.comsol.model.util.*

modelPath = fullfile(paths.modelWorkspaceDir, 'ElectronGun_Coil_ES.mph');
savePath  = fullfile(paths.modelWorkspaceDir, 'ElectronGun_Coil_CPT.mph');
if any(strcmp(cell(ModelUtil.tags()), 'Model'))
    ModelUtil.remove('Model');
end
model = ModelUtil.load('Model', modelPath);
comp1 = model.component('comp1');

sel_vac  = 'sel_vac';   % Complement selection created in phase2_electrostatics_coil.m

%% Physics: Charged Particle Tracing, restricted to the vacuum domain
cpt = comp1.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
cpt.selection.named(sel_vac);

% Release electrons from the FULL coil wire surface, ~0 eV, direction =
% surface normal (default when SpecifyInletTangentialNormal is off).
inl1 = cpt.create('inl1', 'Inlet', 2);
inl1.label('Cathode Coil Emission');
inl1.selection.named('selb_cath');
inl1.set('N', 1);
% v0 = 0 (default) => ~0 eV initial kinetic energy for this baseline check.

%% Electric Force: couples the 'es' electric field into the particle force
ef1 = cpt.create('ef1', 'ElectricForce', 3);
ef1.selection.named(sel_vac);
ef1.set('E_src', 'root.comp1.es.Ex');

%% Study 2: time-dependent particle trace, reusing the Phase-2 ES solution
std2 = model.study.create('std2');
std2.label('Particle Tracing Study');
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

fprintf('SUCCESS: Particle tracing solved.\n');

%% Results: trajectory plot
resultsDir = paths.resultsDir;
if ~exist(resultsDir, 'dir')
    mkdir(resultsDir);
end

try
    pdset1 = model.result.dataset.create('pdset1', 'Particle');
    pdset1.set('solution', 'sol2');

    pg3 = model.result.create('pg_traj', 'PlotGroup3D');
    pg3.label('Electron Trajectories (Coil)');
    pg3.set('data', 'pdset1');
    tr1 = pg3.create('traj1', 'ParticleTrajectories');
    tr1.set('data', 'pdset1');

    imgT = model.result.export.create('imgT', 'Image');
    imgT.set('plotgroup', 'pg_traj');
    imgT.set('pngfilename', fullfile(resultsDir, 'electron_trajectories_coil.png'));
    imgT.set('width', 1200);
    imgT.set('height', 900);
    imgT.run;

    fprintf('SUCCESS: Trajectory image exported.\n');
catch ME
    fprintf('WARNING: Trajectory plot/export failed: %s\n', ME.message);
end

%% Final energy statistics at the last simulated time (t = tlist end).
pd = mphparticle(model, 'dataset', 'pdset1');
qx = pd.p(end, :, 1).'; qy = pd.p(end, :, 2).'; qz = pd.p(end, :, 3).';
n_released = numel(qz);
coords = [qx'; qy'; qz'];
KE = mphinterp(model, 'V', 'coord', coords, 'dataset', 'dset1', 'matherr', 'off');

n_arrived = sum(KE > 60 & KE < 75);
n_absorbed_early = sum(qz < 3);

fprintf('\nParticles released: %d\n', n_released);
fprintf('Final (t=40ns) kinetic energy [eV] via energy conservation: min=%.3f max=%.3f mean=%.3f median=%.3f\n', ...
    min(KE), max(KE), mean(KE), median(KE));
fprintf('Particles that reached ~70 eV (60-75 eV band, i.e. passed the anode): %d / %d (%.1f%%)\n', ...
    n_arrived, n_released, 100*n_arrived/n_released);
fprintf('Particles absorbed early near cathode/Wehnelt (z<3mm): %d / %d (%.1f%%)\n', ...
    n_absorbed_early, n_released, 100*n_absorbed_early/n_released);

% Quick time-evolution sanity check (motion should NOT be frozen at t=0)
z0 = pd.p(1,:,3); zend = pd.p(end,:,3);
fprintf('\nz at t=0:   min=%.4f max=%.4f mean=%.4f mm\n', min(z0), max(z0), mean(z0));
fprintf('z at t=40ns: min=%.4f max=%.4f mean=%.4f mm\n', min(zend), max(zend), mean(zend));
vx = pd.v(:,:,1).'; vy = pd.v(:,:,2).'; vz = pd.v(:,:,3).';
speed_final = sqrt(vx(:,end).^2+vy(:,end).^2+vz(:,end).^2);
fprintf('speed[m/s] at final time: min=%.3e max=%.3e mean=%.3e (theory @70eV = %.3e)\n', ...
    min(speed_final), max(speed_final), mean(speed_final), sqrt(2*70*1.602e-19/9.11e-31));

model.save(savePath);
fprintf('\nSUCCESS: model saved to %s\n', savePath);
end
