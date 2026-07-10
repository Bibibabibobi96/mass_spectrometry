function test_lit_cpt()
% Combines the RF (radial, quadrupole) and DC (axial, end-cap) unit-field
% solves from test_lit_geometry_es.m into one CPT force: E(t) =
% scale_rf(t)*es.Ex + scale_dc*es2.Ex. IMPORTANT: the physics interfaces
% were created with custom tags 'es_rf'/'es_dc', but those tags are NOT
% used for the model's variable namespace -- COMSOL silently falls back
% to its own default incrementing shortcut based on physics TYPE +
% creation order ('es' for the first Electrostatics interface, 'es2' for
% the second), regardless of the custom tag. Confirmed by direct probing
% (see COMSOL_自动化建模经验总结.md §7.17/§10).

addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
mphstart(2036);
import com.comsol.model.*
import com.comsol.model.util.*

if any(strcmp(cell(ModelUtil.tags()), 'ModelLIT'))
    ModelUtil.remove('ModelLIT');
end
model = ModelUtil.load('ModelLIT', 'C:\Users\Liao\PycharmProjects\PythonProject\comsol_models\common\LinearIonTrap.mph');
comp1 = model.component('comp1');

cpt = comp1.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
cpt.label('Charged Particle Tracing: LIT confinement');
cpt.selection.named('sel_vac');

pp1 = cpt.feature('pp1');
pp1.label('Particle properties: 100amu +1 ion');
pp1.set('mp', '100*1.66054e-27[kg]');
pp1.set('Z', '1');

rel1 = cpt.create('rel1', 'Release', 3);
rel1.label('Release: trap center, KE_axial=0.5eV');
% Release ONLY from the small dedicated 'relvol' sub-domain (near the
% trap center, r<1mm, z in [8,12]mm) added in test_lit_geometry_es.m --
% this actually restricts WHICH particles get solved/tracked, giving a
% clean native trajectory plot with no post-hoc filtering needed (the
% CPT physics/ElectricForce below still use the FULL vacuum 'sel_vac' so
% released particles remain free to move anywhere in the trap).
rel1.selection.named('geom1_relvol_dom');
KE_axial_eV = 0.5;
m_kg = 100*1.66054e-27;
v_axial = sqrt(2*KE_axial_eV*1.602176e-19/m_kg);
fprintf('Axial release speed = %.4e m/s (KE=%.1f eV)\n', v_axial, KE_axial_eV);
rel1.set('v0', {'0' '0' sprintf('%.6e[m/s]', v_axial)});

Vamp_rf = 82;   % same as the q=0.5 stable quadrupole test (r0=4mm, 1MHz, 100amu)
f_rf = 1e6;
Vamp_dc = 5;    % modest DC barrier depth
ef1 = cpt.create('ef1', 'ElectricForce', 3);
ef1.label(sprintf('Electric Force: RF %gV@%.0fMHz + DC %gV', Vamp_rf, f_rf/1e6, Vamp_dc));
ef1.selection.named('sel_vac');
ef1.set('E_src', 'userdef');
rfscale = sprintf('(%g/100)*cos(2*pi*%g*t)', Vamp_rf, f_rf);
dcscale = sprintf('(%g/100)', Vamp_dc);
ef1.set('E', { ...
    sprintf('%s*es.Ex+%s*es2.Ex', rfscale, dcscale), ...
    sprintf('%s*es.Ey+%s*es2.Ey', rfscale, dcscale), ...
    sprintf('%s*es.Ez+%s*es2.Ez', rfscale, dcscale) });

Tper = 1/f_rf;
tmax = 40e-6; % 40us -- long enough for a couple of axial bounces at 0.5eV
dtstep = Tper/20;
std2 = model.study.create('std2');
std2.label('Time-dependent: LIT axial confinement');
tstep = std2.create('time1', 'Transient');
tstep.label('Transient solver (0-40us)');
tstep.set('tlist', sprintf('range(0,%g,%g)', dtstep, tmax));
tstep.setEntry('activate', 'es_rf', false);
tstep.setEntry('activate', 'es_dc', false);
tstep.setEntry('activate', 'cpt', true);

soltags = cell(model.sol.tags());
es_sol_tag = soltags{1};
model.sol.create('sol2');
model.sol('sol2').label('Solution: LIT CPT');
model.sol('sol2').study('std2');
model.sol('sol2').createAutoSequence('std2');
model.sol('sol2').feature('v1').set('notsolmethod', 'sol');
model.sol('sol2').feature('v1').set('notsol', es_sol_tag);
model.sol('sol2').runAll;
fprintf('SUCCESS: LIT CPT solved.\n');

pdset1 = model.result.dataset.create('pdset1', 'Particle');
pdset1.label('Particle dataset: LIT confined ions');
pdset1.set('solution', 'sol2');
pd = mphparticle(model, 'dataset', 'pdset1');
nP = size(pd.p,2);
fprintf('n_particles released = %d\n', nP);

x = pd.p(:,:,1); y = pd.p(:,:,2); z = pd.p(:,:,3);
r = sqrt(x.^2+y.^2);
z0 = z(1,:); r0v = r(1,:);
% Near-center, near-axis subset (same filtering technique as the
% quadrupole/Einzel tests -- MeshBased release is dominated by points
% near curved surfaces, not the axis)
nearCenter = z0 > 8 & z0 < 12 & r0v < 1;
fprintf('particles near trap center (z in [8,12], r0<1mm): %d\n', sum(nearCenter));

idx = find(nearCenter);
zc = z(:, idx);
z_cap1 = -3; z_cap2 = 22; % approx cap positions (rod_z0=0, gap_cap=2, t_cap=1)
escaped = any(zc < z_cap1 | zc > z_cap2, 1);
fprintf('escaped past end caps: %d / %d (%.1f%%)\n', sum(escaped), numel(idx), 100*sum(escaped)/numel(idx));
fprintf('z range among near-center subset: min=%.2f max=%.2f mm (cap positions ~ -3/+22mm)\n', ...
    min(zc(:)), max(zc(:)));

resultsDir = 'C:\Users\Liao\PycharmProjects\PythonProject\comsol_results';
if ~exist(resultsDir,'dir'), mkdir(resultsDir); end
fh = figure('Visible','off');
tvals = pd.t*1e6; % us
hold on;
for i = 1:min(15,numel(idx))
    plot(tvals, z(:,idx(i)), '-');
end
yline(z_cap1, 'k--'); yline(z_cap2, 'k--');
xlabel('t [\mus]'); ylabel('z [mm]'); grid on;
title({'Linear Ion Trap: axial position vs time, confined near-center ions', ...
    sprintf('particle: 100amu +1 ion, KE_{axial}=%.1f eV, RF: %gV @ %.0fMHz, DC end-cap: %gV', ...
    KE_axial_eV, Vamp_rf, f_rf/1e6, Vamp_dc)});
print(fh, fullfile(resultsDir, 'lit_axial_confinement.png'), '-dpng', '-r150');
fprintf('SUCCESS: axial trajectory plot saved.\n');

% Native COMSOL result plot (Results > 3D Plot Group > Particle
% Trajectories) so the trajectories are visible when the .mph file is
% reopened directly in COMSOL Desktop, not just as an external MATLAB
% PNG. Previously this script never called model.save() after adding
% the CPT physics/study/solution, so none of that (nor any plot) was
% ever persisted back to LinearIonTrap.mph on disk.
pg1 = model.result.create('pg_traj', 'PlotGroup3D');
pg1.label('LIT: axial confinement trajectory plot');
pg1.set('data', 'pdset1');
pg1.set('titletype', 'manual');
pg1.set('title', sprintf('Linear Ion Trap: 100amu +1 ion, RF %gV@%.0fMHz, DC %gV', Vamp_rf, f_rf/1e6, Vamp_dc));
trj1 = pg1.create('trj1', 'ParticleTrajectories');
trj1.label('Confined near-center ions');
pg1.run;
fprintf('SUCCESS: native particle trajectory plot created.\n');

model.save('C:\Users\Liao\PycharmProjects\PythonProject\comsol_models\common\LinearIonTrap.mph');
fprintf('SUCCESS: model (incl. CPT physics/solution/plot) saved to disk.\n');
end
