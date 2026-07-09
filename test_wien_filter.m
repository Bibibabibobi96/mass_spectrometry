function result = test_wien_filter(mass_amu, KE_eV, label)
% Wien filter (velocity selector): crossed uniform E and B fields,
% E perpendicular to B, both perpendicular to the beam axis (z). For a
% charged particle moving along z at speed v, force balance requires
%   q*E = q*v*B  =>  v = E/B
% independent of BOTH mass and charge -- the defining property of a Wien
% filter, distinct from ESA (energy-selective, mass-independent) and
% magnetic sector (mass-selective for fixed energy). Ions at the design
% velocity pass through essentially undeflected; ions faster or slower
% get deflected in opposite transverse directions since one force then
% dominates the other.
%
% Design point: 100amu +1 ion at KE=1000eV (v_resonant~4.39e4 m/s),
% B0=0.01T (matches the already-validated cyclotron/mag-sector tests),
% E0 = v_resonant*B0.

addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
mphstart(2036);
import com.comsol.model.*
import com.comsol.model.util.*

if nargin < 3, label = sprintf('%gamu_%geV', mass_amu, KE_eV); end

if any(strcmp(cell(ModelUtil.tags()), 'ModelWien'))
    ModelUtil.remove('ModelWien');
end
model = ModelUtil.create('ModelWien');
comp1 = model.component.create('comp1', true);
geom1 = comp1.geom.create('geom1', 3);
geom1.label('Wien filter geometry');
geom1.lengthUnit('mm');
geom1.feature.create('cyl1', 'Cylinder');
geom1.feature('cyl1').label('Field region (r=10mm, L=50mm)');
geom1.feature('cyl1').set('r', '10[mm]');
geom1.feature('cyl1').set('h', '50[mm]');
geom1.feature('cyl1').set('pos', {'0' '0' '0'});

% Small dedicated release volume at the entrance (z~1mm, on-axis) --
% same technique validated throughout this session.
geom1.feature.create('relvol', 'Cylinder');
geom1.feature('relvol').label('Release volume (entrance, on-axis)');
geom1.feature('relvol').set('r', '0.5[mm]');
geom1.feature('relvol').set('h', '1[mm]');
geom1.feature('relvol').set('pos', {'0' '0' '0.5[mm]'});
geom1.feature('relvol').set('selresult', 'on');
geom1.run;

mesh1 = comp1.mesh.create('mesh1');
mesh1.label('Coarse mesh (few release points)');
mesh1.feature('size').set('hauto', 8);
mesh1.feature.create('ftet1', 'FreeTet');
mesh1.run;

cpt = comp1.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
cpt.label(sprintf('Charged Particle Tracing: Wien filter %s', label));
cpt.selection.all;

m_design = 100*1.66054e-27; KE_design_eV = 1000;
v_design = sqrt(2*KE_design_eV*1.602176e-19/m_design);
B0 = 0.01; % T
E0 = v_design*B0; % V/m, design condition v=E/B
fprintf('Design: v_resonant=%.4e m/s (100amu, 1000eV), B0=%gT, E0=%.4f V/m\n', v_design, B0, E0);

m_kg = mass_amu*1.66054e-27;
pp1 = cpt.feature('pp1');
pp1.label(sprintf('Particle properties: %gamu +1 ion', mass_amu));
pp1.set('mp', sprintf('%.6e[kg]', m_kg));
pp1.set('Z', '1');

v_beam = sqrt(2*KE_eV*1.602176e-19/m_kg);
fprintf('[%s] beam speed = %.4e m/s (KE=%g eV, mass=%g amu, ratio to v_resonant=%.3f)\n', ...
    label, v_beam, KE_eV, mass_amu, v_beam/v_design);

rel1 = cpt.create('rel1', 'Release', 3);
rel1.label(sprintf('Release: on-axis, v=%.3e m/s', v_beam));
rel1.selection.named('geom1_relvol_dom');
rel1.set('v0', {'0' '0' sprintf('%.6e[m/s]', v_beam)});

ef1 = cpt.create('ef1', 'ElectricForce', 3);
ef1.label(sprintf('Electric Force: uniform Ex=%.3f V/m', E0));
ef1.selection.all;
ef1.set('E_src', 'userdef');
ef1.set('E', {sprintf('%.6f[V/m]', E0), '0', '0'});

mf1 = cpt.create('mf1', 'MagneticForce', 3);
mf1.label(sprintf('Magnetic Force: uniform By=%gT', B0));
mf1.selection.all;
mf1.set('B_src', 'userdef');
mf1.set('B', {'0', sprintf('%g[T]', B0), '0'});

Tsim = 1.5*(50e-3/v_design); % comfortably covers transit at/near the design velocity
dtstep = Tsim/100;
std1 = model.study.create('std1');
std1.label(sprintf('Time-dependent: Wien filter %s', label));
tstep = std1.create('time1', 'Transient');
tstep.label('Transient solver');
tstep.set('tlist', sprintf('range(0,%g,%g)', dtstep, Tsim));
model.sol.create('sol1');
model.sol('sol1').label(sprintf('Solution: Wien filter %s', label));
model.sol('sol1').study('std1');
model.sol('sol1').createAutoSequence('std1');
model.sol('sol1').runAll;
fprintf('[%s] SUCCESS: solved.\n', label);

pdset1 = model.result.dataset.create('pdset1', 'Particle');
pdset1.label(sprintf('Particle dataset: Wien filter %s', label));
pdset1.set('solution', 'sol1');
pd = mphparticle(model, 'dataset', 'pdset1');
x = squeeze(pd.p(:,:,1)); y = squeeze(pd.p(:,:,2)); z = squeeze(pd.p(:,:,3));
nP = size(x,2);
fprintf('[%s] particles released: %d\n', label, nP);

% All particles from a tiny on-axis release volume behave essentially
% identically (uniform field, no spatial dependence) -- just take particle 1.
% IMPORTANT: report deflection RELATIVE to the starting x-position, not
% raw x_end -- MeshBased release scatters particles up to r<0.5mm off
% axis, and since crossed uniform E/B fields provide no restoring force
% in x/y, that initial offset simply carries through unperturbed and
% would otherwise swamp the (much smaller) velocity-dependent deflection
% this test is meant to isolate.
idxUse = 1;
xTraj = x(:, idxUse); zTraj = z(:, idxUse);
zEnd = zTraj(end); xStart = xTraj(1); xEnd = xTraj(end);
xDeflect = xEnd - xStart;
fprintf('[%s] at z_end=%.3fmm: x_start=%.4fmm x_end=%.4fmm, deflection=%.4fmm (zero = perfectly undeflected)\n', ...
    label, zEnd, xStart, xEnd, xDeflect);

result = struct('label', label, 'mass_amu', mass_amu, 'KE_eV', KE_eV, ...
    'v_over_vresonant', v_beam/v_design, 'x_deflect_mm', xDeflect, 'z_end_mm', zEnd);

resultsDir = 'C:\Users\Liao\PycharmProjects\PythonProject\comsol_results';
if ~exist(resultsDir,'dir'), mkdir(resultsDir); end
fh = figure('Visible','off');
plot(zTraj, xTraj, '-o', 'MarkerSize', 2);
xlabel('z [mm]'); ylabel('x [mm] (deflection)'); grid on;
title({sprintf('Wien filter: %s', label), ...
    sprintf('particle: %gamu +1 ion, v/v_{resonant}=%.3f, E0=%.3fV/m, B0=%gT', mass_amu, v_beam/v_design, E0, B0)}, 'Interpreter', 'none');
print(fh, fullfile(resultsDir, sprintf('wien_filter_%s.png', strrep(label,' ','_'))), '-dpng', '-r150');
fprintf('[%s] SUCCESS: trajectory plot saved.\n', label);

pg1 = model.result.create('pg_traj', 'PlotGroup3D');
pg1.label(sprintf('Wien filter: %s trajectory plot', label));
pg1.set('data', 'pdset1');
pg1.set('titletype', 'manual');
pg1.set('title', sprintf('Wien filter: %gamu +1 ion, v/v_resonant=%.3f', mass_amu, v_beam/v_design));
trj1 = pg1.create('trj1', 'ParticleTrajectories');
trj1.label(sprintf('Ion trajectory (%s)', label));
pg1.run;

modelsDir = 'C:\Users\Liao\PycharmProjects\PythonProject\comsol_models';
if ~exist(modelsDir, 'dir'), mkdir(modelsDir); end
model.save(fullfile(modelsDir, sprintf('WienFilter_%s.mph', strrep(label,' ','_'))));
fprintf('[%s] SUCCESS: native trajectory plot created and model saved.\n', label);
end
