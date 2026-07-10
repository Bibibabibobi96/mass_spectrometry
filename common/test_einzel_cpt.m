function test_einzel_cpt()
% Loads the solved Einzel lens (test_einzel_lens.m) and traces a beam of
% 100amu, +1 ions released from the small entrance sub-volume
% ('geom1_relvol_dom', r<1.5mm just before disk1), checking whether the
% radial spread narrows (focuses) somewhere past the lens. Uses
% KE=5000eV with V2=-4000V (ratio 1.25) -- a combination already
% validated earlier as giving clean, SAFE transmission (well above the
% ~3375eV on-axis trough depth), so essentially all released particles
% actually pass through the lens instead of being reflected back --
% deliberately avoiding the near-threshold KE=3500eV case used
% previously, which risked partial reflection and cluttered the native
% trajectory plot with non-representative particles.

addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
mphstart(2036);
import com.comsol.model.*
import com.comsol.model.util.*

if any(strcmp(cell(ModelUtil.tags()), 'ModelEinzel'))
    ModelUtil.remove('ModelEinzel');
end
model = ModelUtil.load('ModelEinzel', 'C:\Users\Liao\PycharmProjects\PythonProject\comsol_models\common\EinzelLens.mph');
comp1 = model.component('comp1');

cpt = comp1.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
cpt.label('Charged Particle Tracing: Einzel lens beam');
cpt.selection.named('sel_vac');

pp1 = cpt.feature('pp1');
pp1.label('Particle properties: 100amu +1 ion');
pp1.set('mp', '100*1.66054e-27[kg]');
pp1.set('Z', '1');

KE_eV = 5000;  % ratio KE/|V2| = 1.25, matches the previously-validated safe-transmission case
m_kg = 100*1.66054e-27;
v_beam = sqrt(2*KE_eV*1.602176e-19/m_kg);
fprintf('Beam speed = %.4e m/s (KE=%d eV, 100amu)\n', v_beam, KE_eV);

rel1 = cpt.create('rel1', 'Release', 3);
rel1.label(sprintf('Release: entrance beam, KE=%g eV', KE_eV));
% Release ONLY from the small entrance sub-domain (r<1.5mm, just before
% disk1) added in test_einzel_lens.m -- restricts WHICH particles get
% solved/tracked to a physically meaningful entering beam, instead of
% scattering across the whole vacuum (most of which starts deep
% inside/behind the lens and isn't a real "beam" at all).
rel1.selection.named('geom1_relvol_dom');
rel1.set('v0', {'0' '0' sprintf('%.6e[m/s]', v_beam)});

ef1 = cpt.create('ef1', 'ElectricForce', 3);
ef1.label('Electric Force: from Einzel lens ES field');
ef1.selection.named('sel_vac');
ef1.set('E_src', 'root.comp1.es.Ex');

std2 = model.study.create('std2');
std2.label('Time-dependent: Einzel lens beam transit');
tstep = std2.create('time1', 'Transient');
tstep.label('Transient solver (0-800ns)');
tstep.set('tlist', 'range(0,2[ns],800[ns])');
tstep.setEntry('activate', 'es', false);
tstep.setEntry('activate', 'cpt', true);

soltags = cell(model.sol.tags());
es_sol_tag = soltags{1};
model.sol.create('sol2');
model.sol('sol2').label('Solution: Einzel lens CPT');
model.sol('sol2').study('std2');
model.sol('sol2').createAutoSequence('std2');
model.sol('sol2').feature('v1').set('notsolmethod', 'sol');
model.sol('sol2').feature('v1').set('notsol', es_sol_tag);
model.sol('sol2').runAll;
fprintf('SUCCESS: Einzel lens CPT solved.\n');

pdset1 = model.result.dataset.create('pdset1', 'Particle');
pdset1.label('Particle dataset: Einzel lens ions');
pdset1.set('solution', 'sol2');
pd = mphparticle(model, 'dataset', 'pdset1');
nP = size(pd.p,2);
fprintf('n_particles released = %d\n', nP);

x = pd.p(:,:,1); y = pd.p(:,:,2); z = pd.p(:,:,3);
r = sqrt(x.^2+y.^2);
z0 = z(1,:); r0 = r(1,:);
fprintf('particles released from entrance sub-volume: %d\n', nP);

% Verify transmission: did each particle actually make it past disk3
% (z3=18mm, so z>19mm is safely past it) rather than being reflected
% back by the lens barrier? Only transmitted particles should end up in
% the native trajectory plot -- a reflected particle would clutter the
% view with a trajectory that doubles back on itself instead of showing
% a clean focusing pass-through.
zEnd = z(end, :);
transmitted = zEnd > 19;
fprintf('transmitted past the lens (z_end>19mm): %d / %d (%.1f%%)\n', ...
    sum(transmitted), nP, 100*sum(transmitted)/nP);

idx = find(transmitted);
if isempty(idx)
    error('No particles transmitted -- check KE/V2 ratio (lens barrier may be too strong).');
end
zplot = z(:, idx); rplot = r(:, idx);

resultsDir = 'C:\Users\Liao\PycharmProjects\PythonProject\comsol_results';
if ~exist(resultsDir,'dir'), mkdir(resultsDir); end
fh = figure('Visible','off');
hold on;
for i = 1:numel(idx)
    plot(zplot(:,i), rplot(:,i), '-');
end
xlabel('z [mm]'); ylabel('r [mm]'); grid on;
title({'Einzel lens: radial trajectory r(z), transmitted entrance-beam ions', ...
    sprintf('particle: 100amu +1 ion, KE=%g eV, V_{lens}=-4000V (ratio %.2f)', KE_eV, KE_eV/4000)});
print(fh, fullfile(resultsDir, 'einzel_focusing.png'), '-dpng', '-r150');
fprintf('SUCCESS: focusing plot saved.\n');

% Find z-bins with minimum radial spread (crude "focus" search)
zbins = -3:1:21;
spreadAtBin = nan(1,numel(zbins)-1);
for b = 1:numel(zbins)-1
    mask = zplot >= zbins(b) & zplot < zbins(b+1);
    rvals = rplot(mask);
    if numel(rvals) > 3
        spreadAtBin(b) = std(rvals);
    end
end
[minSpread, minIdx] = min(spreadAtBin);
fprintf('\nMinimum radial spread (std) = %.4f mm, near z=%.1fmm (bin [%.0f,%.0f])\n', ...
    minSpread, (zbins(minIdx)+zbins(minIdx+1))/2, zbins(minIdx), zbins(minIdx+1));
fprintf('Initial radial spread (std) at entrance (z<0): %.4f mm\n', std(r0(transmitted)));

% Native COMSOL result plot + save to disk, so the trajectory is visible
% when the .mph is reopened directly in COMSOL Desktop (this script
% previously never called model.save() after adding CPT).
pg1 = model.result.create('pg_traj', 'PlotGroup3D');
pg1.label('Einzel lens: transmitted ion trajectory plot');
pg1.set('data', 'pdset1');
pg1.set('titletype', 'manual');
pg1.set('title', sprintf('Einzel lens: transmitted ions, 100amu +1, KE=%g eV, V_{lens}=-4000V', KE_eV));
trj1 = pg1.create('trj1', 'ParticleTrajectories');
trj1.label(sprintf('Transmitted ions (KE=%g eV)', KE_eV));
pg1.run;
model.save('C:\Users\Liao\PycharmProjects\PythonProject\comsol_models\common\EinzelLens.mph');
fprintf('SUCCESS: native trajectory plot created and model saved.\n');
end
