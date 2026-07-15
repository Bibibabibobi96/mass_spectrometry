function test_quadrupole_stability(Vamp, label)
% Runs a CPT stability test in the quadrupole rod array (Multipole4.mph,
% already ES-solved with rod potentials at +/-100V, see
% test_multipole_es.m). The RF electric force is built manually as
%   E(t) = (Vamp/100) * E_static * cos(2*pi*f_rf*t)
% i.e. the statically-solved unit field (from the 100V ES solve) rescaled
% to the desired peak RF amplitude Vamp and time-modulated -- an
% alternative to ElectricForce's native 'TimeHarmonic' mode (also
% available: TimeDependenceOfField='TimeHarmonic' + FrequencySpecification
% + omega, see COMSOL_API.md §7.15), chosen here for
% direct control over Vamp without re-solving electrostatics per case.
%
% Ion: 100 amu, +1 charge, released near-center with ~0 initial velocity
% (scattered mesh-node positions provide the small initial displacement
% that Mathieu-equation stability theory concerns itself with).
%
% Mathieu q parameter: q = 4*e*Vamp/(m*Omega^2*r0^2). At Omega=2*pi*1MHz,
% r0=4mm, m=100amu: Vamp(q=0.5)=~82V (stable, first stability region),
% Vamp(q=1.2)=~196V (unstable, beyond q_boundary=0.908).

commonDir = fileparts(mfilename('fullpath'));
addpath(commonDir);
paths = common_artifact_paths();
addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
mphstart(2036);
import com.comsol.model.*
import com.comsol.model.util.*

tag = 'ModelPole4';
modelPath = fullfile(paths.modelsDir, 'Multipole4.mph');
if any(strcmp(cell(ModelUtil.tags()), tag))
    ModelUtil.remove(tag);
end
model = ModelUtil.load(tag, modelPath);
comp1 = model.component('comp1');

cpt = comp1.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
cpt.selection.named('sel_vac');

pp1 = cpt.feature('pp1');
pp1.set('mp', '100*1.66054e-27[kg]');  % 100 amu
pp1.set('Z', '1');                      % singly-charged positive ion

rel1 = cpt.create('rel1', 'Release', 3);
% Release ONLY from the small dedicated 'relvol' sub-domain (r<0.3*r0,
% full rod length) added in test_multipole_geometry.m -- this actually
% restricts WHICH particles get solved/tracked to the near-axis region
% relevant to Mathieu stability, giving a clean native trajectory plot
% with no post-hoc filtering needed (ElectricForce below still covers
% the FULL vacuum 'sel_vac' so released particles remain free to move
% anywhere, including diverging past r0 in the unstable case).
rel1.selection.named('geom1_relvol_dom');
rel1.set('v0', {'0' '0' '0'});   % near-zero initial velocity; scattered
                                   % mesh-node start positions supply the
                                   % small perturbation

f_rf = 1e6; % Hz
ef1 = cpt.create('ef1', 'ElectricForce', 3);
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

% The electrostatics stationary solve (from test_multipole_es.m) already
% exists in this loaded model as some 'solN' tag -- find it before
% creating our own CPT solution, per the notsolmethod/notsol reuse
% pattern (see COMSOL_API.md §2.4/§7.8).
soltags = cell(model.sol.tags());
fprintf('Existing sol tags before CPT solve: %s\n', strjoin(soltags, ', '));
es_sol_tag = soltags{1};

std2 = model.study.create('std2');
tstep = std2.create('time1', 'Transient');
tstep.set('tlist', sprintf('range(0,%g,%g)', dtstep, tmax));
tstep.setEntry('activate', 'es', false);
tstep.setEntry('activate', 'cpt', true);

model.sol.create('sol2');
model.sol('sol2').study('std2');
model.sol('sol2').createAutoSequence('std2');
model.sol('sol2').feature('v1').set('notsolmethod', 'sol');
model.sol('sol2').feature('v1').set('notsol', es_sol_tag);
model.sol('sol2').runAll;
fprintf('SUCCESS: quadrupole CPT (%s) solved.\n', label);

pdset1 = model.result.dataset.create('pdset1', 'Particle');
pdset1.set('solution', 'sol2');
pd = mphparticle(model, 'dataset', 'pdset1');
nP = size(pd.p, 2);

x = pd.p(:,:,1); y = pd.p(:,:,2);
r = sqrt(x.^2 + y.^2); % [nTimes x nParticles], mm
r0 = 4; % mm, field radius

% 'Release' (MeshBased, whole vacuum domain) scatters particles across
% the ENTIRE domain, heavily weighted toward mesh nodes near the curved
% rod surfaces (not concentrated near the axis) -- there is no "release
% from a sub-region" option (see COMSOL_API.md §7.15), so
% filter in post-processing to only particles that STARTED near the axis
% (within the region where the ideal quadrupole approximation and the
% Mathieu-stability comparison are actually meaningful).
r_init = r(1,:);
nearAxis = r_init < 0.3*r0;
fprintf('particles starting within 0.3*r0 of axis: %d / %d\n', sum(nearAxis), nP);

maxr_frac = max(r(:,nearAxis),[],1) / r0; % each near-axis particle's max radial excursion
survived = ~isnan(r(end,nearAxis));

fprintf('\n=== %s (Vamp=%.1fV) ===\n', label, Vamp);
fprintf('n_particles (all released) = %d, analyzed (near-axis subset) = %d\n', nP, sum(nearAxis));
fprintf('survived to t_end (non-NaN): %d (%.1f%%)\n', sum(survived), 100*sum(survived)/numel(survived));
fprintf('max radial excursion / r0: median=%.3f  90th pct=%.3f  max=%.3f\n', ...
    median(maxr_frac), prctile(maxr_frac,90), max(maxr_frac));
fprintf('fraction with max r > 1.0*r0 (would have hit inscribed circle): %.1f%%\n', ...
    100*sum(maxr_frac>1.0)/numel(maxr_frac));

resultsDir = paths.resultsDir;
if ~exist(resultsDir, 'dir'), mkdir(resultsDir); end
fh = figure('Visible','off');
idxPlot = find(nearAxis);
idxPlot = idxPlot(1:min(15,numel(idxPlot)));
hold on;
for i = idxPlot
    plot(x(:,i), y(:,i), '-');
end
theta = linspace(0,2*pi,100);
plot(r0*cos(theta), r0*sin(theta), 'k--', 'LineWidth', 1.5);
xlabel('x [mm]'); ylabel('y [mm]'); axis equal; grid on;
title(sprintf('%s (Vamp=%.0fV) - sample near-axis trajectories', label, Vamp));
legend({'','','','','','','','','','','','','','','','r0 boundary'}, 'Location','best');
print(fh, fullfile(resultsDir, sprintf('quad_stability_%s.png', strrep(label,' ','_'))), '-dpng', '-r150');
fprintf('SUCCESS: trajectory plot saved.\n');

% Native COMSOL result plot so the trajectories are visible when the
% .mph is reopened directly in COMSOL Desktop (previously this script
% never called model.save() after adding CPT, so none of the CPT
% physics/study/solution/plot was ever persisted to disk -- opening
% Multipole4.mph only ever showed the bare ES-only state).
pg1 = model.result.create('pg_traj', 'PlotGroup3D');
pg1.set('data', 'pdset1');
trj1 = pg1.create('trj1', 'ParticleTrajectories');
pg1.run;
fprintf('SUCCESS: native particle trajectory plot created.\n');

% Save to a label-specific file, NOT back to Multipole4.mph itself --
% this function runs once per stability case (stable/unstable), and both
% share the same on-disk source model, so saving to the shared path would
% let the second run silently overwrite the first run's CPT results.
savePath = fullfile(paths.modelsDir, ...
    sprintf('Multipole4_CPT_%s.mph', strrep(label,' ','_')));
model.save(savePath);
fprintf('SUCCESS: model (incl. CPT physics/solution/plot) saved to %s\n', savePath);
end
