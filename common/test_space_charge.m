function result = test_space_charge(useInteraction, label)
% Space charge / Coulomb repulsion test: a tight cluster of identical
% ions (100amu, +1, released from a small on-axis sub-volume with the
% SAME initial velocity) drifts down a field-free tube. With
% 'ParticleParticleInteraction' (InteractionForce='Coulomb') active, the
% mutual Coulomb repulsion between the simulated ions should measurably
% widen the beam's radial spread relative to the no-interaction baseline
% (pure ballistic motion, spread only reflects the tiny initial release
% scatter). Uses a LOW kinetic energy (1eV) for a long transit time
% (~72us over 100mm) so the (otherwise weak, at realistic mass-spec
% densities/timescales) Coulomb force has time to integrate into a
% clearly visible displacement -- deliberately chosen to make the effect
% observable, not meant to represent a specific real instrument's beam
% density.

commonDir = fileparts(mfilename('fullpath'));
addpath(commonDir);
paths = common_artifact_paths();
addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
mphstart(2036);
import com.comsol.model.*
import com.comsol.model.util.*

if nargin < 1, useInteraction = true; end
if nargin < 2, label = sprintf('interaction_%d', useInteraction); end

if any(strcmp(cell(ModelUtil.tags()), 'ModelSpaceCharge'))
    ModelUtil.remove('ModelSpaceCharge');
end
model = ModelUtil.create('ModelSpaceCharge');
comp1 = model.component.create('comp1', true);
geom1 = comp1.geom.create('geom1', 3);
geom1.label('Space charge test geometry');
geom1.lengthUnit('mm');
geom1.feature.create('cyl1', 'Cylinder');
geom1.feature('cyl1').label('Field-free drift tube (r=5mm, L=100mm)');
geom1.feature('cyl1').set('r', '5[mm]');
geom1.feature('cyl1').set('h', '100[mm]');
geom1.feature('cyl1').set('pos', {'0' '0' '0'});

geom1.feature.create('relvol', 'Cylinder');
geom1.feature('relvol').label('Release volume (tight on-axis cluster)');
geom1.feature('relvol').set('r', '0.05[mm]');
geom1.feature('relvol').set('h', '0.1[mm]');
geom1.feature('relvol').set('pos', {'0' '0' '0.5[mm]'});
geom1.feature('relvol').set('selresult', 'on');
geom1.run;

mesh1 = comp1.mesh.create('mesh1');
mesh1.label('Mesh (finer near relvol for enough particles)');
mesh1.feature('size').set('hauto', 6);
mesh1.feature.create('ftet1', 'FreeTet');
mesh1.run;

cpt = comp1.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
cpt.label(sprintf('Charged Particle Tracing: space charge %s', label));
cpt.selection.all;

m_kg = 100*1.66054e-27;
pp1 = cpt.feature('pp1');
pp1.label('Particle properties: 100amu +1 ion');
pp1.set('mp', sprintf('%.6e[kg]', m_kg));
pp1.set('Z', '1');

KE_eV = 1;
v_beam = sqrt(2*KE_eV*1.602176e-19/m_kg);
fprintf('beam speed = %.4e m/s (KE=%g eV, 100amu)\n', v_beam, KE_eV);

rel1 = cpt.create('rel1', 'Release', 3);
rel1.label('Release: tight cluster, KE=1eV');
rel1.selection.named('geom1_relvol_dom');
rel1.set('v0', {'0' '0' sprintf('%.6e[m/s]', v_beam)});

if useInteraction
    ppi1 = cpt.create('ppi1', 'ParticleParticleInteraction', 3);
    ppi1.label('Particle-particle interaction: Coulomb repulsion');
    ppi1.selection.all;
    ppi1.set('InteractionForce', 'Coulomb');
    fprintf('ParticleParticleInteraction (Coulomb) ENABLED\n');
else
    fprintf('ParticleParticleInteraction DISABLED (baseline)\n');
end

Tsim = 1.5*(100e-3/v_beam); % comfortably covers the full 100mm transit
dtstep = Tsim/150;
std1 = model.study.create('std1');
std1.label(sprintf('Time-dependent: space charge %s', label));
tstep = std1.create('time1', 'Transient');
tstep.label('Transient solver');
tstep.set('tlist', sprintf('range(0,%g,%g)', dtstep, Tsim));
model.sol.create('sol1');
model.sol('sol1').label(sprintf('Solution: space charge %s', label));
model.sol('sol1').study('std1');
model.sol('sol1').createAutoSequence('std1');
model.sol('sol1').runAll;
fprintf('[%s] SUCCESS: solved.\n', label);

pdset1 = model.result.dataset.create('pdset1', 'Particle');
pdset1.label(sprintf('Particle dataset: space charge %s', label));
pdset1.set('solution', 'sol1');
pd = mphparticle(model, 'dataset', 'pdset1');
x = squeeze(pd.p(:,:,1)); y = squeeze(pd.p(:,:,2)); z = squeeze(pd.p(:,:,3));
r = sqrt(x.^2+y.^2);
nP = size(x,2);
fprintf('[%s] particles released: %d\n', label, nP);

r0 = r(1,:); rEnd = r(end,:);
fprintf('[%s] initial radial spread: mean=%.5fmm, std=%.5fmm, max=%.5fmm\n', label, mean(r0), std(r0), max(r0));
fprintf('[%s] final radial spread (z~100mm): mean=%.5fmm, std=%.5fmm, max=%.5fmm\n', label, mean(rEnd), std(rEnd), max(rEnd));

result = struct('label', label, 'useInteraction', useInteraction, 'nP', nP, ...
    'r0_std', std(r0), 'rEnd_std', std(rEnd), 'rEnd_max', max(rEnd));

resultsDir = paths.resultsDir;
if ~exist(resultsDir,'dir'), mkdir(resultsDir); end
fh = figure('Visible','off');
hold on;
for i = 1:nP
    plot(z(:,i), r(:,i), '-');
end
xlabel('z [mm]'); ylabel('r [mm]'); grid on;
title({sprintf('Space charge test: %s', label), ...
    sprintf('100amu +1 ion cluster, KE=1eV, N=%d, Coulomb interaction=%d', nP, useInteraction)}, 'Interpreter', 'none');
print(fh, fullfile(resultsDir, sprintf('space_charge_%s.png', strrep(label,' ','_'))), '-dpng', '-r150');
fprintf('[%s] SUCCESS: trajectory plot saved.\n', label);

pg1 = model.result.create('pg_traj', 'PlotGroup3D');
pg1.label(sprintf('Space charge: %s trajectory plot', label));
pg1.set('data', 'pdset1');
pg1.set('titletype', 'manual');
pg1.set('title', sprintf('Space charge: %s, N=%d ions, Coulomb=%d', label, nP, useInteraction));
trj1 = pg1.create('trj1', 'ParticleTrajectories');
trj1.label(sprintf('Ion cluster trajectories (%s)', label));
pg1.run;

modelsDir = paths.modelsDir;
if ~exist(modelsDir, 'dir'), mkdir(modelsDir); end
model.save(fullfile(modelsDir, sprintf('SpaceCharge_%s.mph', strrep(label,' ','_'))));
fprintf('[%s] SUCCESS: native trajectory plot created and model saved.\n', label);
end
