function test_cpt_magnetic_force()
% Reference/validation script: charged particle tracing under a uniform
% user-defined magnetic field via the CPT 'MagneticForce' feature.
% Releases an electron with pure transverse velocity into a uniform Bz
% and checks the resulting circular (cyclotron) motion against theory
% (r = m*v_perp/(q*B), T = 2*pi*m/(q*B)). See COMSOL_自动化建模经验总结.md
% §9 for the full narrative -- the one bug that took real debugging was
% forgetting to call `.selection` on the MagneticForce feature at all:
% it does NOT error at compile time the way Release/Inlet with no
% selection does, it just silently applies zero force everywhere,
% producing a perfectly straight-line trajectory that looks like "no
% error, but no curving" instead of a hard failure.

commonDir = fileparts(mfilename('fullpath'));
addpath(commonDir);
paths = common_artifact_paths();
addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
mphstart(2036);
import com.comsol.model.*
import com.comsol.model.util.*

if any(strcmp(cell(ModelUtil.tags()), 'ModelCPTMag'))
    ModelUtil.remove('ModelCPTMag');
end
model = ModelUtil.create('ModelCPTMag');
comp1 = model.component.create('comp1', true);
geom1 = comp1.geom.create('geom1', 3);
geom1.label('Cyclotron test geometry');
geom1.lengthUnit('mm');
geom1.feature.create('cyl1', 'Cylinder');
geom1.feature('cyl1').label('Confinement domain (r=5mm)');
geom1.feature('cyl1').set('r', '5[mm]');
geom1.feature('cyl1').set('h', '2[mm]');
geom1.feature('cyl1').set('pos', {'0' '0' '-1[mm]'});
geom1.run;

mesh1 = comp1.mesh.create('mesh1');
mesh1.label('Coarse mesh (few release points)');
mesh1.feature('size').set('hauto', 9); % coarsest -> few release points, fast test
mesh1.feature.create('ftet1', 'FreeTet');
mesh1.run;

cpt = comp1.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
cpt.label('Charged Particle Tracing: electron cyclotron motion');

% 'Release' (domain-level, edim=3) instead of 'Inlet' (boundary-level) --
% releases particles from mesh nodes inside the domain. NOTE: Release has
% no "exact single point" option; 'InitialPosition' only takes
% "MeshBased"/"Density"/"RandomPosition" (tried 'Manual' and edim=0 point
% release, both invalid). Fine here since cyclotron radius/period don't
% depend on starting position in a uniform field.
rel1 = cpt.create('rel1', 'Release', 3);
rel1.label('Release: electron, v0=1e6 m/s transverse');
rel1.selection.all;
rel1.set('v0', {'1e6[m/s]' '0' '0'});   % pure transverse velocity -> planar circle, no axial drift

% MagneticForce: B_src valid values are "EarthsMagneticField"/"userdef"/
% "fromCommonDef" (plus "root.comp1.mf.Bx"-style options once a solved
% Magnetic Fields ('InductionCurrents') physics exists in the model, same
% pattern as ElectricForce's E_src). 'userdef' + explicit 'B' vector is
% the simplest way to test with an idealized/analytical field.
mf1 = cpt.create('mf1', 'MagneticForce', 3);
mf1.label('Magnetic Force: uniform Bz=0.01T');
mf1.selection.all;   % !!! do not skip -- see file header note
mf1.set('B_src', 'userdef');
mf1.set('B', {'0' '0' '0.01[T]'});

std1 = model.study.create('std1');
std1.label('Time-dependent: cyclotron motion');
tstep = std1.create('time1', 'Transient');
tstep.label('Transient solver (0-20ns)');
tstep.set('tlist', 'range(0,0.05[ns],20[ns])');
model.sol.create('sol1');
model.sol('sol1').label('Solution: cyclotron motion');
model.sol('sol1').study('std1');
model.sol('sol1').createAutoSequence('std1');
model.sol('sol1').runAll;
fprintf('SUCCESS: solved cyclotron-motion test.\n');

pdset1 = model.result.dataset.create('pdset1', 'Particle');
pdset1.label('Particle dataset: electron trajectories');
pdset1.set('solution', 'sol1');
pd = mphparticle(model, 'dataset', 'pdset1');
fprintf('n particles = %d\n', size(pd.p,2));

% pd.p is in the model's length unit (mm here); pd.v is always SI (m/s).
px = squeeze(pd.p(:,1,1)); py = squeeze(pd.p(:,1,2)); pz = squeeze(pd.p(:,1,3));
vx = squeeze(pd.v(:,1,1)); vy = squeeze(pd.v(:,1,2)); vz = squeeze(pd.v(:,1,3));
speed = sqrt(vx.^2+vy.^2+vz.^2);
fprintf('Particle 1 |v|: min=%.4e max=%.4e m/s (should stay ~1e6 -- magnetic force does no work)\n', min(speed), max(speed));
fprintf('Particle 1 z motion (should be ~0, pure planar for v0 perp to B): min=%.6f max=%.6f mm\n', min(pz), max(pz));
r_num = (max(px)-min(px))/2;
fprintf('Particle 1 gyroradius (from x-extent/2): %.4f mm\n', r_num);

me_ = 9.10938e-31; qe = 1.602176e-19; B0 = 0.01; vperp = 1e6;
r_theory = me_*vperp/(qe*B0);
T_theory = 2*pi*me_/(qe*B0);
fprintf('Theory: gyroradius = %.4f mm, cyclotron period = %.4f ns\n', r_theory*1e3, T_theory*1e9);

resultsDir = paths.resultsDir;
if ~exist(resultsDir, 'dir'), mkdir(resultsDir); end
f = figure('Visible','off');
plot(px, py, '-o', 'MarkerSize',2);
xlabel('x [mm]'); ylabel('y [mm]'); grid on; axis equal;
title({'Cyclotron motion test: uniform B_z field (top view, x-y plane)', ...
    sprintf('particle: electron (m=9.109e-31kg, q=-1.602e-19C), v_{perp}=%.2g m/s, B_z=%.3gT', vperp, B0)});
print(f, fullfile(resultsDir, 'cyclotron_trajectory.png'), '-dpng', '-r150');
fprintf('SUCCESS: plot saved.\n');

% Native COMSOL result plot + save to disk, so the trajectory is visible
% when the .mph is reopened directly in COMSOL Desktop (this script
% previously never called model.save() at all).
pg1 = model.result.create('pg_traj', 'PlotGroup3D');
pg1.label('Cyclotron trajectory plot');
pg1.set('data', 'pdset1');
pg1.set('titletype', 'manual');
pg1.set('title', sprintf('Cyclotron motion: electron, v_{perp}=%.2g m/s, B_z=%.3gT', vperp, B0));
trj1 = pg1.create('trj1', 'ParticleTrajectories');
trj1.label('Electron trajectories (uniform Bz)');
pg1.run;
modelsDir = paths.modelsDir;
if ~exist(modelsDir, 'dir'), mkdir(modelsDir); end
model.save(fullfile(modelsDir, 'CyclotronMotion.mph'));
fprintf('SUCCESS: native trajectory plot created and model saved.\n');
end
