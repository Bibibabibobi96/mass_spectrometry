function test_multipole_stability(Npoles, Vamp, label)
% Runs a CPT RF-confinement test in an N-pole rod array (Multipole{N}.mph,
% already ES-solved with rod potentials at +/-100V, see
% test_multipole_es.m). The RF electric force is built manually as
%   E(t) = (Vamp/100) * E_static * cos(2*pi*f_rf*t)
% i.e. the statically-solved unit field (from the 100V ES solve) rescaled
% to the desired peak RF amplitude Vamp and time-modulated.
%
% Ion: 100 amu, +1 charge, released near-axis with ~0 initial velocity
% (scattered mesh-node positions provide the small initial displacement).
%
% NOTE: strict Mathieu-equation stability theory (q parameter, sharp
% stability/instability boundary at q_boundary~0.908) applies rigorously
% ONLY to the quadrupole (N=4) -- its restoring force is exactly linear
% in displacement. Hexapole (N=6) and octupole (N=8) have a NONLINEAR
% restoring force (~r^(N/2-1)), so they don't have the same clean
% textbook stability diagram; in practice they're used as ion GUIDES
% (looser, broader-band confinement/transmission) rather than precision
% mass filters. This test therefore checks the more general, qualitative
% property relevant to any N: does a near-axis ion stay BOUNDED within r0
% over several RF cycles, rather than claiming a precise Mathieu q value.
% For N=4 specifically: q = 4*e*Vamp/(m*Omega^2*r0^2); at Omega=2*pi*1MHz,
% r0=4mm, m=100amu: Vamp(q=0.5)=~82V (stable), Vamp(q=1.2)=~196V (unstable).

addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
mphstart(2036);
import com.comsol.model.*
import com.comsol.model.util.*

tag = sprintf('ModelPole%d', Npoles);
modelPath = sprintf('C:\\Users\\Liao\\PycharmProjects\\PythonProject\\comsol_models\\common\\Multipole%d.mph', Npoles);
if any(strcmp(cell(ModelUtil.tags()), tag))
    ModelUtil.remove(tag);
end
model = ModelUtil.load(tag, modelPath);
comp1 = model.component('comp1');

cpt = comp1.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
cpt.label(sprintf('Charged Particle Tracing: %d-pole %s', Npoles, label));
cpt.selection.named('sel_vac');

pp1 = cpt.feature('pp1');
pp1.label('Particle properties: 100amu +1 ion');
pp1.set('mp', '100*1.66054e-27[kg]');  % 100 amu
pp1.set('Z', '1');                      % singly-charged positive ion

rel1 = cpt.create('rel1', 'Release', 3);
rel1.label('Release: near-axis, ~0 initial velocity');
% Release ONLY from the small dedicated 'relvol' sub-domain (r<0.2*r0,
% short central segment) added in test_multipole_geometry.m -- restricts
% WHICH particles get solved/tracked to the near-axis region relevant to
% RF confinement, giving a clean native trajectory plot with no post-hoc
% filtering needed (ElectricForce below still covers the FULL vacuum
% 'sel_vac' so released particles remain free to move anywhere, including
% diverging past r0 in the unstable case).
rel1.selection.named('geom1_relvol_dom');
rel1.set('v0', {'0' '0' '0'});   % near-zero initial velocity; scattered
                                   % mesh-node start positions supply the
                                   % small perturbation

f_rf = 1e6; % Hz
ef1 = cpt.create('ef1', 'ElectricForce', 3);
ef1.label(sprintf('Electric Force: RF %gV@%.0fMHz', Vamp, f_rf/1e6));
ef1.selection.named('sel_vac');
ef1.set('E_src', 'userdef');
scale = sprintf('(%g/100)', Vamp);
ef1.set('E', { ...
    sprintf('%s*es.Ex*cos(2*pi*%g*t)', scale, f_rf), ...
    sprintf('%s*es.Ey*cos(2*pi*%g*t)', scale, f_rf), ...
    sprintf('%s*es.Ez*cos(2*pi*%g*t)', scale, f_rf) });

Tper = 1/f_rf;
nCycles = 20;
dtstep = Tper/20;
tmax = nCycles*Tper;

soltags = cell(model.sol.tags());
fprintf('Existing sol tags before CPT solve: %s\n', strjoin(soltags, ', '));
es_sol_tag = soltags{1};

std2 = model.study.create('std2');
std2.label(sprintf('Time-dependent: %d-pole %s', Npoles, label));
tstep = std2.create('time1', 'Transient');
tstep.label('Transient solver (20 RF cycles)');
tstep.set('tlist', sprintf('range(0,%g,%g)', dtstep, tmax));
tstep.setEntry('activate', 'es', false);
tstep.setEntry('activate', 'cpt', true);

model.sol.create('sol2');
model.sol('sol2').label(sprintf('Solution: %d-pole CPT %s', Npoles, label));
model.sol('sol2').study('std2');
model.sol('sol2').createAutoSequence('std2');
model.sol('sol2').feature('v1').set('notsolmethod', 'sol');
model.sol('sol2').feature('v1').set('notsol', es_sol_tag);
model.sol('sol2').runAll;
fprintf('SUCCESS: %d-pole CPT (%s) solved.\n', Npoles, label);

pdset1 = model.result.dataset.create('pdset1', 'Particle');
pdset1.label(sprintf('Particle dataset: %d-pole %s', Npoles, label));
pdset1.set('solution', 'sol2');
pd = mphparticle(model, 'dataset', 'pdset1');
nP = size(pd.p, 2);

x = pd.p(:,:,1); y = pd.p(:,:,2);
r = sqrt(x.^2 + y.^2); % [nTimes x nParticles], mm
r0 = 4; % mm, field radius

fprintf('particles released (all within relvol near-axis region): %d\n', nP);
maxr_frac = max(r,[],1) / r0; % each particle's max radial excursion
survived = ~isnan(r(end,:));

fprintf('\n=== %d-pole, %s (Vamp=%.1fV) ===\n', Npoles, label, Vamp);
fprintf('n_particles = %d\n', nP);
fprintf('survived to t_end (non-NaN): %d (%.1f%%)\n', sum(survived), 100*sum(survived)/numel(survived));
fprintf('max radial excursion / r0: median=%.3f  90th pct=%.3f  max=%.3f\n', ...
    median(maxr_frac), prctile(maxr_frac,90), max(maxr_frac));
fprintf('fraction with max r > 1.0*r0 (would have hit inscribed circle): %.1f%%\n', ...
    100*sum(maxr_frac>1.0)/numel(maxr_frac));

resultsDir = 'C:\Users\Liao\PycharmProjects\PythonProject\comsol_results';
if ~exist(resultsDir, 'dir'), mkdir(resultsDir); end
fh = figure('Visible','off');
idxPlot = 1:min(15,nP);
hold on;
for i = idxPlot
    plot(x(:,i), y(:,i), '-');
end
theta = linspace(0,2*pi,100);
plot(r0*cos(theta), r0*sin(theta), 'k--', 'LineWidth', 1.5);
xlabel('x [mm]'); ylabel('y [mm]'); axis equal; grid on;
title({sprintf('%d-pole RF confinement: %s, near-axis ions', Npoles, label), ...
    sprintf('particle: 100amu +1 ion, RF: %gV @ %.0fMHz peak, r0=%gmm', Vamp, f_rf/1e6, r0)}, 'Interpreter', 'none');
legend([repmat({''},1,numel(idxPlot)) {'r0 boundary'}], 'Location','best');
print(fh, fullfile(resultsDir, sprintf('multipole%d_stability_%s.png', Npoles, strrep(label,' ','_'))), '-dpng', '-r150');
fprintf('SUCCESS: trajectory plot saved.\n');

% Native COMSOL result plot so the trajectories are visible when the
% .mph is reopened directly in COMSOL Desktop.
pg1 = model.result.create('pg_traj', 'PlotGroup3D');
pg1.label(sprintf('%d-pole: %s trajectory plot', Npoles, label));
pg1.set('data', 'pdset1');
pg1.set('titletype', 'manual');
pg1.set('title', sprintf('%d-pole: 100amu +1 ion, RF %gV@%.0fMHz, %s', Npoles, Vamp, f_rf/1e6, label));
trj1 = pg1.create('trj1', 'ParticleTrajectories');
trj1.label(sprintf('Near-axis ions (%s)', label));
pg1.run;
fprintf('SUCCESS: native particle trajectory plot created.\n');

% Save to a label-specific file, NOT back to Multipole{N}.mph itself --
% this function runs once per stability case (stable/unstable), and both
% share the same on-disk source model, so saving to the shared path would
% let the second run silently overwrite the first run's CPT results.
savePath = sprintf('C:\\Users\\Liao\\PycharmProjects\\PythonProject\\comsol_models\\common\\Multipole%d_CPT_%s.mph', Npoles, strrep(label,' ','_'));
model.save(savePath);
fprintf('SUCCESS: model (incl. CPT physics/solution/plot) saved to %s\n', savePath);
end
