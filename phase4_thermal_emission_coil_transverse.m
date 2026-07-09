function phase4_thermal_emission_coil_transverse()
% Thermal (2700K) CPT emission for the TRANSVERSE-coil electron gun
% (helix axis perpendicular to the beam axis), directly comparable to
% phase4_thermal_emission_coil.m (axial/coaxial coil) under the same
% Wehnelt baseline (r_weh_hole=1.0mm, V_wehnelt=-0.5V) to assess whether
% electron utilization (collection efficiency) actually improves.

addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
mphstart(2036);
import com.comsol.model.*
import com.comsol.model.util.*

modelPath = 'C:\Users\Liao\PycharmProjects\PythonProject\comsol_models\ElectronGun_CoilT_ES.mph';
savePath  = 'C:\Users\Liao\PycharmProjects\PythonProject\comsol_models\ElectronGun_CoilT_Thermal_CPT.mph';
if any(strcmp(cell(ModelUtil.tags()), 'Model'))
    ModelUtil.remove('Model');
end
model = ModelUtil.load('Model', modelPath);
comp1 = model.component('comp1');

sel_vac  = 'sel_vac';

cpt = comp1.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
cpt.selection.named(sel_vac);

inl1 = cpt.create('inl1', 'Inlet', 2);
inl1.label('Cathode Coil Emission (Thermal, transverse)');
inl1.selection.named('selb_cath');
inl1.set('N', 1);
inl1.set('VelocitySpecification', 'Thermal');
inl1.set('T_src', 'userdef');
inl1.set('T', '2700[K]');

ef1 = cpt.create('ef1', 'ElectricForce', 3);
ef1.selection.named(sel_vac);
ef1.set('E_src', 'root.comp1.es.Ex');

std2 = model.study.create('std2');
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
fprintf('SUCCESS: Particle tracing (thermal, transverse coil) solved.\n');

resultsDir = 'C:\Users\Liao\PycharmProjects\PythonProject\comsol_results';
if ~exist(resultsDir, 'dir'), mkdir(resultsDir); end
try
    pdset1 = model.result.dataset.create('pdset1', 'Particle');
    pdset1.set('solution', 'sol2');
    pg3 = model.result.create('pg_traj', 'PlotGroup3D');
    pg3.set('data', 'pdset1');
    tr1 = pg3.create('traj1', 'ParticleTrajectories');
    tr1.set('data', 'pdset1');
    imgT = model.result.export.create('imgT', 'Image');
    imgT.set('plotgroup', 'pg_traj');
    imgT.set('pngfilename', fullfile(resultsDir, 'electron_trajectories_transverse.png'));
    imgT.set('width', 1200); imgT.set('height', 900);
    imgT.run;
    fprintf('SUCCESS: Trajectory image exported.\n');
catch ME
    fprintf('WARNING: Trajectory plot/export failed: %s\n', ME.message);
end

pd = mphparticle(model, 'dataset', 'pdset1');
me_ = 9.10938e-31; qe = 1.602176e-19;
n_released = size(pd.p, 2);
qz_end = pd.p(end,:,3);
vx = pd.v(end,:,1); vy = pd.v(end,:,2); vz = pd.v(end,:,3);
valid = ~isnan(qz_end);
speed = sqrt(vx.^2+vy.^2+vz.^2);
KE_eV = 0.5*me_*speed.^2/qe;
n_arrived = sum(valid & KE_eV > 60 & KE_eV < 75);
n_selfabs = sum(~valid);

fprintf('\n=== Transverse-coil thermal emission results ===\n');
fprintf('Particles released: %d\n', n_released);
fprintf('Lost (NaN, self-absorbed on coil/Wehnelt before reaching a valid state): %d (%.2f%%)\n', ...
    n_selfabs, 100*n_selfabs/n_released);
fprintf('Reached ~70eV band (passed anode, i.e. USABLE for ionization/collection): %d / %d (%.2f%%)\n', ...
    n_arrived, n_released, 100*n_arrived/n_released);
KEv = KE_eV(valid);
fprintf('KE[eV] among valid: min=%.4f max=%.4f mean=%.4f median=%.4f\n', ...
    min(KEv), max(KEv), mean(KEv), median(KEv));

model.save(savePath);
fprintf('\nSUCCESS: model saved to %s\n', savePath);
end
