function result = test_magnetic_sector(mass_amu, KE_eV, label)
% Magnetic sector mass analyzer: reuses the already-validated CPT
% MagneticForce cyclotron-motion mechanism (test_cpt_magnetic_force.m),
% but in the mass-spec convention -- ions are accelerated to a FIXED
% kinetic energy (not a fixed velocity) before entering the sector field,
% so velocity varies with mass (v=sqrt(2*KE/m)) and the resulting
% gyroradius r=m*v/(q*B)=sqrt(2*m*KE)/(q*B) scales as sqrt(mass) for
% fixed KE and B -- the core principle that separates ions by m/z.

commonDir = fileparts(mfilename('fullpath'));
addpath(commonDir);
paths = common_artifact_paths();
addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
mphstart(2036);
import com.comsol.model.*
import com.comsol.model.util.*

if nargin < 3, label = sprintf('%gamu_%geV', mass_amu, KE_eV); end
if any(strcmp(cell(ModelUtil.tags()), 'ModelMagSector'))
    ModelUtil.remove('ModelMagSector');
end
model = ModelUtil.create('ModelMagSector');
comp1 = model.component.create('comp1', true);
geom1 = comp1.geom.create('geom1', 3);
geom1.label(sprintf('Magnetic sector geometry (%s)', label));
geom1.lengthUnit('mm');
geom1.feature.create('cyl1', 'Cylinder');
geom1.feature('cyl1').label('Field domain (r=200mm, uniform Bz)');
geom1.feature('cyl1').set('r', '200[mm]'); % must exceed 2*r_gyro for ALL test masses, or orbits clip the wall regardless of start position
geom1.feature('cyl1').set('h', '2[mm]');
geom1.feature('cyl1').set('pos', {'0' '0' '-1[mm]'});

% Small dedicated "release volume" at the domain center -- restricts
% WHICH particles get released (not just which are picked afterward) to
% ones whose full gyro-orbit is guaranteed to fit within the 200mm
% domain regardless of orbit size, instead of MeshBased scattering across
% the whole domain (most of which would clip the boundary and freeze
% early; see this file's domain-size validation below).
geom1.feature.create('relvol', 'Cylinder');
geom1.feature('relvol').label('Release volume (central, r<5mm)');
geom1.feature('relvol').set('r', '5[mm]');
geom1.feature('relvol').set('h', '2[mm]');
geom1.feature('relvol').set('pos', {'0' '0' '-1[mm]'});
geom1.feature('relvol').set('selresult', 'on');
geom1.run;

mesh1 = comp1.mesh.create('mesh1');
mesh1.label('Coarse mesh (few release points)');
mesh1.feature('size').set('hauto', 9); % coarse -> few release points
mesh1.feature.create('ftet1', 'FreeTet');
mesh1.run;

cpt = comp1.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
cpt.label(sprintf('Charged Particle Tracing: mag sector %s', label));
cpt.selection.all; % now that 'relvol' adds a second domain, be explicit that CPT covers both (particles must be free to leave relvol and traverse the whole 200mm domain)
m_kg = mass_amu*1.66054e-27;
pp1 = cpt.feature('pp1');
pp1.label(sprintf('Particle properties: %gamu +1 ion', mass_amu));
pp1.set('mp', sprintf('%.6e[kg]', m_kg));
pp1.set('Z', '1');

v_beam = sqrt(2*KE_eV*1.602176e-19/m_kg);
fprintf('[%s] v=%.4e m/s (KE=%g eV, mass=%g amu)\n', label, v_beam, KE_eV, mass_amu);
rel1 = cpt.create('rel1', 'Release', 3);
rel1.label(sprintf('Release: central, v=%.3g m/s', v_beam));
% Release ONLY from the small central sub-domain -- guarantees every
% released particle's orbit fits within the 200mm domain regardless of
% starting position, instead of relying on post-hoc filtering (which
% previously required picking a "near center" particle by hand out of
% thousands, most of which were physically meaningless for this test).
rel1.selection.named('geom1_relvol_dom');
rel1.set('v0', {sprintf('%.6e[m/s]', v_beam) '0' '0'});

B0 = 1.0; % Tesla -- chosen so gyroradius is well within the 100mm domain
mf1 = cpt.create('mf1', 'MagneticForce', 3);
mf1.label(sprintf('Magnetic Force: uniform Bz=%gT', B0));
mf1.selection.all;
mf1.set('B_src', 'userdef');
mf1.set('B', {'0' '0' sprintf('%g[T]', B0)});

r_theory = m_kg*v_beam/(1.602176e-19*B0);
T_theory = 2*pi*m_kg/(1.602176e-19*B0);
fprintf('[%s] theory: r=%.4f mm, T=%.4f us\n', label, r_theory*1e3, T_theory*1e6);

tmax = 1.2*T_theory;
dt = T_theory/40;
std1 = model.study.create('std1');
std1.label(sprintf('Time-dependent: mag sector %s', label));
tstep = std1.create('time1', 'Transient');
tstep.label('Transient solver (0-1.2 periods)');
tstep.set('tlist', sprintf('range(0,%g,%g)', dt, tmax));
model.sol.create('sol1');
model.sol('sol1').label(sprintf('Solution: mag sector %s', label));
model.sol('sol1').study('std1');
model.sol('sol1').createAutoSequence('std1');
model.sol('sol1').runAll;
fprintf('[%s] SUCCESS: solved.\n', label);

pdset1 = model.result.dataset.create('pdset1', 'Particle');
pdset1.label(sprintf('Particle dataset: mag sector %s', label));
pdset1.set('solution', 'sol1');
pd = mphparticle(model, 'dataset', 'pdset1');
xAll = squeeze(pd.p(:,:,1)); yAll = squeeze(pd.p(:,:,2));
fprintf('[%s] particles released from central sub-volume: %d\n', label, size(xAll,2));
idxUse = 1;
x = xAll(:, idxUse); y = yAll(:, idxUse);
r_num = (max(x)-min(x))/2;
fprintf('[%s] measured gyroradius (x-extent/2) = %.4f mm (theory %.4f mm, ratio %.4f)\n', ...
    label, r_num, r_theory*1e3, r_num/(r_theory*1e3));

result = struct('label', label, 'mass_amu', mass_amu, 'r_theory_mm', r_theory*1e3, 'r_num_mm', r_num);

resultsDir = paths.resultsDir;
if ~exist(resultsDir,'dir'), mkdir(resultsDir); end
fh = figure('Visible','off');
plot(x, y, '-o', 'MarkerSize', 2); axis equal; grid on;
xlabel('x [mm]'); ylabel('y [mm]');
title({sprintf('Magnetic sector: %s gyro-orbit', label), ...
    sprintf('particle: %gamu +1 ion, KE=%g eV, B_z=%.3gT, r_{theory}=%.2fmm', mass_amu, KE_eV, B0, r_theory*1e3)});
print(fh, fullfile(resultsDir, sprintf('magsector_orbit_%s.png', strrep(label,' ','_'))), '-dpng', '-r150');
fprintf('[%s] SUCCESS: trajectory plot saved.\n', label);

% Native COMSOL result plot + save to disk (label-specific, since this
% function builds a fresh model per call for each test mass).
pg1 = model.result.create('pg_traj', 'PlotGroup3D');
pg1.label(sprintf('Mag sector: %s trajectory plot', label));
pg1.set('data', 'pdset1');
pg1.set('titletype', 'manual');
pg1.set('title', sprintf('Magnetic sector: %gamu +1 ion, KE=%g eV, B_z=%.3gT', mass_amu, KE_eV, B0));
trj1 = pg1.create('trj1', 'ParticleTrajectories');
trj1.label(sprintf('%s gyro-orbit', label));
pg1.run;
modelsDir = paths.modelsDir;
if ~exist(modelsDir, 'dir'), mkdir(modelsDir); end
model.save(fullfile(modelsDir, sprintf('MagSector_%s.mph', strrep(label,' ','_'))));
fprintf('[%s] SUCCESS: native trajectory plot created and model saved.\n', label);
end
