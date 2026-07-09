function phase3_particle_tracing()
% Phase 3: charged particle tracing - release electrons from the cathode
% surface (~0 eV initial energy), trace them through the Wehnelt aperture
% and accelerating gap to the anode/drift region using the electric field
% already solved in Phase 2, then report trajectories + final energy.

addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
mphstart(2036);
import com.comsol.model.*
import com.comsol.model.util.*

modelPath = 'C:\Users\Liao\PycharmProjects\PythonProject\comsol_models\ElectronGun_ES.mph';
savePath  = 'C:\Users\Liao\PycharmProjects\PythonProject\comsol_models\ElectronGun_CPT.mph';
if any(strcmp(cell(ModelUtil.tags()), 'Model'))
    ModelUtil.remove('Model');
end
model = ModelUtil.load('Model', modelPath);
comp1 = model.component('comp1');

sel_vac  = 'geom1_cyl6_dom';

%% Physics: Charged Particle Tracing, restricted to the vacuum domain
cpt = comp1.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
cpt.selection.named(sel_vac);

% Particle properties (pp1) already default to electron: mp=me_const, Z=-1

% Release electrons from the full cathode surface, ~0 eV, direction =
% surface normal (default when SpecifyInletTangentialNormal is off).
inl1 = cpt.create('inl1', 'Inlet', 2);
inl1.label('Cathode Emission');
inl1.selection.named('selb_cath');
inl1.set('N', 1);
% v0 = 0 (default) => ~0 eV initial kinetic energy, as required.

% wall1 (default, selection=all boundaries) already WallCondition=Freeze,
% Otherwise=Freeze -> particles are absorbed (frozen) wherever they hit
% Wehnelt/anode surfaces or the outer envelope (i.e. also acts as the
% "detector" at the far end of the drift region).

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

% Deactivating 'es' in std2 only skips RE-SOLVING it; by itself it does NOT
% make cpt reuse the Phase-2 field. The auto-created Variables node (v1)
% defaults to notsolmethod='init', i.e. the deactivated es fields fall back
% to zero (initial values), not the stored ES solution -> zero E everywhere
% -> ElectricForce computes zero force -> particles (v0=0) never move.
% Fix: explicitly point "values of variables not solved for" at sol1.
model.sol('sol2').feature('v1').set('notsolmethod', 'sol');
model.sol('sol2').feature('v1').set('notsol', 'sol1');

model.sol('sol2').runAll;

fprintf('SUCCESS: Particle tracing solved.\n');

%% Results: trajectory plot
resultsDir = 'C:\Users\Liao\PycharmProjects\PythonProject\comsol_results';
if ~exist(resultsDir, 'dir')
    mkdir(resultsDir);
end

try
    pdset1 = model.result.dataset.create('pdset1', 'Particle');
    pdset1.set('solution', 'sol2');

    pg3 = model.result.create('pg_traj', 'PlotGroup3D');
    pg3.label('Electron Trajectories');
    pg3.set('data', 'pdset1');
    tr1 = pg3.create('traj1', 'ParticleTrajectories');
    tr1.set('data', 'pdset1');

    imgT = model.result.export.create('imgT', 'Image');
    imgT.set('plotgroup', 'pg_traj');
    imgT.set('pngfilename', fullfile(resultsDir, 'electron_trajectories.png'));
    imgT.set('width', 1200);
    imgT.set('height', 900);
    imgT.run;

    fprintf('SUCCESS: Trajectory image exported.\n');
catch ME
    fprintf('WARNING: Trajectory plot/export failed: %s\n', ME.message);
end

%% Final energy statistics at the last simulated time (t = tlist end).
% cpt.Ep is not a valid postprocessing variable in this installation, so
% kinetic energy is obtained from energy conservation instead: since all
% electrons start at the cathode (V=0, ~0 eV), KE[eV] at any later point
% equals the local electrostatic potential V there (Phase-2 solution).
%
% IMPORTANT: mpheval(...,'dataset','dset2','edim',0) does NOT return
% per-particle data for a Particle Tracing solution -- it silently
% evaluates on the underlying FEM mesh's 0-D geometric vertices instead
% (same coordinates at every t, spanning the full domain bounding box).
% The correct accessor is mphparticle(model,'dataset','pdset1'), which
% returns p/v/t as [nTimes x nParticles x 3] arrays.
tend = 40e-9; % must match the last value in std2/time1's tlist
pd = mphparticle(model, 'dataset', 'pdset1');
qx = pd.p(end, :, 1).'; qy = pd.p(end, :, 2).'; qz = pd.p(end, :, 3).';
n_released = numel(qz);
coords = [qx'; qy'; qz'];
KE = mphinterp(model, 'V', 'coord', coords, 'dataset', 'dset1');

n_arrived = sum(KE > 60 & KE < 75);
n_absorbed_early = sum(qz < 3);

fprintf('\nParticles released: %d\n', n_released);
fprintf('Final (t=%.0fns) kinetic energy [eV] via energy conservation: min=%.3f max=%.3f mean=%.3f median=%.3f\n', ...
    tend*1e9, min(KE), max(KE), mean(KE), median(KE));
fprintf('Particles that reached ~70 eV (60-75 eV band, i.e. passed the anode): %d / %d (%.1f%%)\n', ...
    n_arrived, n_released, 100*n_arrived/n_released);
fprintf('Particles absorbed early near cathode/Wehnelt (z<3mm): %d / %d (%.1f%%)\n', ...
    n_absorbed_early, n_released, 100*n_absorbed_early/n_released);

model.save(savePath);
fprintf('\nSUCCESS: model saved to %s\n', savePath);
end
