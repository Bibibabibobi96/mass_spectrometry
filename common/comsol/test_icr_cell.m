function test_icr_cell()
% FTICR/ICR trap: combines a uniform axial magnetic field (radial
% confinement via cyclotron motion, same mechanism as
% test_cpt_magnetic_force.m/test_magnetic_sector.m) with DC trapping
% end-cap electrodes (axial confinement, same mechanism as the Linear Ion
% Trap's end caps in test_lit_cpt.m) -- the two basic confinement
% mechanisms of a real Fourier Transform Ion Cyclotron Resonance cell,
% here validated TOGETHER for the first time rather than separately.
% End caps are SOLID disks (no aperture) since ions are released directly
% inside the trap and never need to physically pass through an electrode.

commonDir = fileparts(mfilename('fullpath'));
addpath(commonDir);
paths = common_artifact_paths();
addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
mphstart(2036);
import com.comsol.model.*
import com.comsol.model.util.*

if any(strcmp(cell(ModelUtil.tags()), 'ModelICR'))
    ModelUtil.remove('ModelICR');
end
model = ModelUtil.create('ModelICR');
comp1 = model.component.create('comp1', true);
geom1 = comp1.geom.create('geom1', 3);
geom1.label('ICR cell geometry');
geom1.lengthUnit('mm');

p = model.param;
p.set('R_cell', '20[mm]', 'Cell bore radius');
p.set('L_cell', '40[mm]', 'Cell length (between end caps)');
p.set('t_cap', '1[mm]');
p.set('V_trap', '5[V]', 'End-cap trapping voltage (both ends, symmetric)');

geom1.feature.create('cap1', 'Cylinder');
geom1.feature('cap1').label('End cap 1 (z=0, +V_trap)');
geom1.feature('cap1').set('r', 'R_cell');
geom1.feature('cap1').set('h', 't_cap');
geom1.feature('cap1').set('pos', {'0' '0' '-t_cap'});

geom1.feature.create('cap2', 'Cylinder');
geom1.feature('cap2').label('End cap 2 (z=L_cell, +V_trap)');
geom1.feature('cap2').set('r', 'R_cell');
geom1.feature('cap2').set('h', 't_cap');
geom1.feature('cap2').set('pos', {'0' '0' 'L_cell'});

geom1.feature.create('cylv', 'Cylinder');
geom1.feature('cylv').label('ICR cell body (bounding cylinder)');
geom1.feature('cylv').set('r', 'R_cell');
geom1.feature('cylv').set('h', 'L_cell+2*t_cap');
geom1.feature('cylv').set('pos', {'0' '0' '-t_cap'});

geom1.feature.create('relvol', 'Cylinder');
geom1.feature('relvol').label('Release volume (trap center)');
geom1.feature('relvol').set('r', '1[mm]');
geom1.feature('relvol').set('h', '4[mm]');
geom1.feature('relvol').set('pos', {'0' '0' 'L_cell/2-2[mm]'});
geom1.feature('relvol').set('selresult', 'on');

for t = {'cap1','cap2'}
    geom1.feature(t{1}).set('selresult', 'on');
end
geom1.run;
gi = mphgeominfo(model, 'geom1');
fprintf('Geometry built. Ndomains=%d\n', gi.Ndomains);

comp1.selection.create('sel_vac', 'Complement');
comp1.selection('sel_vac').label('Vacuum (all domains except end caps)');
comp1.selection('sel_vac').set('input', {'geom1_cap1_dom','geom1_cap2_dom'});
vac_n = numel(comp1.selection('sel_vac').entities());
fprintf('sel_vac resolves to %d domain(s)\n', vac_n);
if vac_n ~= 2, error('Expected 2 vacuum domains (rest-of-cell + relvol), got %d', vac_n); end

mat_vac = model.material.create('mat_vac', 'Common');
mat_vac.label('Vacuum (relpermittivity=1)');
mat_vac.selection.named('sel_vac');
mat_vac.propertyGroup('def').set('relpermittivity', {'1'});
for t = {'cap1','cap2'}
    matk = model.material.create(sprintf('mat_%s', t{1}), 'Common');
    matk.label(sprintf('%s material', t{1}));
    matk.selection.named(sprintf('geom1_%s_dom', t{1}));
    matk.propertyGroup('def').set('relpermittivity', {'1'});
end

es = comp1.physics.create('es', 'Electrostatics', 'geom1');
es.label('Electrostatics: ICR trapping end caps');
es.selection.named('sel_vac');
for t = {'cap1','cap2'}
    tagb = sprintf('selb_%s', t{1});
    comp1.selection.create(tagb, 'Adjacent');
    comp1.selection(tagb).label(sprintf('%s boundary', t{1}));
    comp1.selection(tagb).set('input', {sprintf('geom1_%s_dom', t{1})});
    potk = es.create(sprintf('pot_%s', t{1}), 'ElectricPotential', 2);
    potk.label(sprintf('%s potential (+V_trap)', t{1}));
    potk.selection.named(tagb);
    potk.set('V0', 'V_trap');
end

% !!! Both end caps are at the SAME +V_trap with no grounded reference
% anywhere -- Laplace's equation with two boundaries at identical
% potential and nothing else specified just gives V=V_trap EVERYWHERE
% (confirmed: on-axis potential was a flat 5.0000V at every z, meaning
% ZERO axial field and NO actual trapping at all). A real ICR cell's
% cylindrical bore wall is grounded, creating the potential gradient that
% makes the end caps into a genuine trapping barrier. Same fix pattern as
% the validated TOF drift-tube pattern: compute "all vacuum boundaries MINUS
% the cap boundaries MINUS relvol's own internal boundary" via MATLAB
% setdiff, then ground it explicitly.
comp1.selection.create('sel_vac_allbnd', 'Adjacent');
comp1.selection('sel_vac_allbnd').label('All vacuum boundaries (before exclusion)');
comp1.selection('sel_vac_allbnd').set('input', {'sel_vac'});
allbnd_ents = comp1.selection('sel_vac_allbnd').entities();
capbnd_ents = unique([comp1.selection('selb_cap1').entities(); comp1.selection('selb_cap2').entities()]);
comp1.selection.create('sel_relvol_allbnd', 'Adjacent');
comp1.selection('sel_relvol_allbnd').label('Release volume boundary (excluded from grounding)');
comp1.selection('sel_relvol_allbnd').set('input', {'geom1_relvol_dom'});
relvolbnd_ents = comp1.selection('sel_relvol_allbnd').entities();
sidewall_ents = setdiff(allbnd_ents, [capbnd_ents; relvolbnd_ents]);
fprintf('ICR cell side wall: %d boundary/boundaries found\n', numel(sidewall_ents));
comp1.selection.create('selb_sidewall', 'Explicit');
comp1.selection('selb_sidewall').label('ICR cell bore wall (grounded)');
comp1.selection('selb_sidewall').geom('geom1', 2);
comp1.selection('selb_sidewall').set(sidewall_ents);
pot_wall = es.create('pot_wall', 'ElectricPotential', 2);
pot_wall.label('Cell bore wall potential (grounded)');
pot_wall.selection.named('selb_sidewall');
pot_wall.set('V0', '0');

mesh1 = comp1.mesh.create('mesh1');
mesh1.label('Mesh (hauto=4)');
mesh1.feature('size').set('hauto', 4);
mesh1.feature.create('ftet1', 'FreeTet');
mesh1.run;
mi = mphmeshstats(model, 'mesh1');
fprintf('mesh: isempty=%d iscomplete=%d\n', mi.isempty, mi.iscomplete);
if mi.isempty || ~mi.iscomplete, error('mesh failed'); end

std1 = model.study.create('std1');
std1.label('Stationary: ICR trapping field');
std1.create('stat1', 'Stationary');
model.sol.create('sol1');
model.sol('sol1').label('Solution: ICR ES');
model.sol('sol1').study('std1');
model.sol('sol1').createAutoSequence('std1');
model.sol('sol1').runAll;
fprintf('SUCCESS: electrostatics solved.\n');

zvals = [0.5 5 10 20 30 35 39.5];
coords = [zeros(1,numel(zvals)); zeros(1,numel(zvals)); zvals];
Vq = mphinterp(model, 'V', 'coord', coords, 'dataset', 'dset1', 'matherr', 'off');
fprintf('\nOn-axis trapping potential (should show barrier near each end, minimum at center):\n');
for i=1:numel(zvals)
    fprintf('  z=%6.1fmm  V=%9.4fV\n', zvals(i), Vq(i));
end

%% CPT: combined cyclotron (radial) + axial bounce (DC trap)
m_kg = 100*1.66054e-27;
cpt = comp1.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
cpt.label('Charged Particle Tracing: ICR trapped ion');
cpt.selection.named('sel_vac');
pp1 = cpt.feature('pp1');
pp1.label('Particle properties: 100amu +1 ion');
pp1.set('mp', sprintf('%.6e[kg]', m_kg));
pp1.set('Z', '1');

KE_radial_eV = 1; KE_axial_eV = 0.5;
v_perp = sqrt(2*KE_radial_eV*1.602176e-19/m_kg);
v_axial = sqrt(2*KE_axial_eV*1.602176e-19/m_kg);
fprintf('\nv_perp=%.4e m/s (KE_radial=%.1feV), v_axial=%.4e m/s (KE_axial=%.1feV)\n', ...
    v_perp, KE_radial_eV, v_axial, KE_axial_eV);

rel1 = cpt.create('rel1', 'Release', 3);
rel1.label('Release: trap center, combined radial+axial velocity');
rel1.selection.named('geom1_relvol_dom');
rel1.set('v0', {sprintf('%.6e[m/s]', v_perp), '0', sprintf('%.6e[m/s]', v_axial)});

ef1 = cpt.create('ef1', 'ElectricForce', 3);
ef1.label('Electric Force: from ICR trapping field');
ef1.selection.named('sel_vac');
ef1.set('E_src', 'root.comp1.es.Ex');

B0 = 0.3; % T -- chosen so the cyclotron radius (~4.8mm) fits comfortably in the 20mm cell
mf1 = cpt.create('mf1', 'MagneticForce', 3);
mf1.label(sprintf('Magnetic Force: uniform Bz=%gT', B0));
mf1.selection.named('sel_vac');
mf1.set('B_src', 'userdef');
mf1.set('B', {'0', '0', sprintf('%g[T]', B0)});

r_gyro_theory = m_kg*v_perp/(1.602176e-19*B0);
T_cyc_theory = 2*pi*m_kg/(1.602176e-19*B0);
fprintf('theory: cyclotron radius=%.4fmm, cyclotron period=%.4fus\n', r_gyro_theory*1e3, T_cyc_theory*1e6);

Tsim = 100e-6; % 100us -- several cyclotron periods + should show axial bounce
dtstep = T_cyc_theory/100; % fine sampling within one period for a clean gyroradius check
std2 = model.study.create('std2');
std2.label('Time-dependent: ICR trapped motion');
tstep = std2.create('time1', 'Transient');
tstep.label('Transient solver (0-100us)');
tstep.set('tlist', sprintf('range(0,%g,%g)', dtstep, Tsim));
tstep.setEntry('activate', 'es', false);
tstep.setEntry('activate', 'cpt', true);

soltags = cell(model.sol.tags());
es_sol_tag = soltags{1};
model.sol.create('sol2');
model.sol('sol2').label('Solution: ICR CPT');
model.sol('sol2').study('std2');
model.sol('sol2').createAutoSequence('std2');
model.sol('sol2').feature('v1').set('notsolmethod', 'sol');
model.sol('sol2').feature('v1').set('notsol', es_sol_tag);
model.sol('sol2').runAll;
fprintf('SUCCESS: ICR CPT solved.\n');

pdset1 = model.result.dataset.create('pdset1', 'Particle');
pdset1.label('Particle dataset: ICR trapped ion');
pdset1.set('solution', 'sol2');
pd = mphparticle(model, 'dataset', 'pdset1');
nP = size(pd.p,2);
fprintf('particles released: %d\n', nP);

x = squeeze(pd.p(:,:,1)); y = squeeze(pd.p(:,:,2)); z = squeeze(pd.p(:,:,3));
r = sqrt(x.^2+y.^2);
t = pd.t;

idxUse = 1;
xTraj = x(:,idxUse); yTraj = y(:,idxUse); zTraj = z(:,idxUse); rTraj = r(:,idxUse);
% Report gyroradius from just the FIRST cyclotron period, not the full
% simulation: the trapping field has a radial E-component (not purely
% axial), producing a slow E x B "magnetron drift" of the orbit's guiding
% center -- a real, well-known effect in ICR/Penning traps, superimposed
% on top of (and much slower than) the fast cyclotron motion. Measuring
% x-extent over MANY cyclotron periods conflates the two, inflating the
% apparent "gyroradius" as successive drifted orbits get included.
idxFirstOrbit = t <= 1.05*T_cyc_theory;
xFirst = xTraj(idxFirstOrbit);
r_gyro_measured = (max(xFirst)-min(xFirst))/2;
fprintf('measured gyroradius (x-extent/2, first cyclotron period only): %.4fmm (theory %.4fmm)\n', ...
    r_gyro_measured, r_gyro_theory*1e3);
r_gyro_fullsim = (max(xTraj)-min(xTraj))/2;
fprintf('x-extent/2 over the FULL %gus simulation: %.4fmm (larger than one orbit -- magnetron-like guiding-center drift, not an error)\n', ...
    Tsim*1e6, r_gyro_fullsim);
fprintf('axial z range over full sim: min=%.3fmm max=%.3fmm (end caps at 0/%gmm)\n', ...
    min(zTraj), max(zTraj), 40);
escaped = any(zTraj < -0.5 | zTraj > 40.5);
fprintf('escaped past end caps: %d\n', escaped);

resultsDir = paths.resultsDir;
if ~exist(resultsDir,'dir'), mkdir(resultsDir); end
fh = figure('Visible','off');
subplot(1,3,1);
plot(xTraj, yTraj, '-'); axis equal; grid on;
xlabel('x [mm]'); ylabel('y [mm]'); title('cyclotron motion (top view)');
subplot(1,3,2);
plot(t*1e6, zTraj, '-'); grid on;
yline(0,'k--'); yline(40,'k--');
xlabel('t [\mus]'); ylabel('z [mm]'); title('axial bounce vs time');
subplot(1,3,3);
plot3(xTraj, yTraj, zTraj, '-'); grid on;
xlabel('x [mm]'); ylabel('y [mm]'); zlabel('z [mm]'); title('3D trapped trajectory');
sgtitle({'ICR cell: combined cyclotron + axial trapping', ...
    sprintf('100amu +1 ion, KE_{radial}=%.1feV, KE_{axial}=%.1feV, Bz=%gT, V_{trap}=5V', ...
    KE_radial_eV, KE_axial_eV, B0)}, 'Interpreter', 'none');
print(fh, fullfile(resultsDir, 'icr_cell_trajectory.png'), '-dpng', '-r150');
fprintf('SUCCESS: trajectory plot saved.\n');

pg1 = model.result.create('pg_traj', 'PlotGroup3D');
pg1.label('ICR cell: trapped ion trajectory plot');
pg1.set('data', 'pdset1');
pg1.set('titletype', 'manual');
pg1.set('title', sprintf('ICR cell: 100amu +1 ion, Bz=%gT, V_trap=5V', B0));
trj1 = pg1.create('trj1', 'ParticleTrajectories');
trj1.label('Trapped ion trajectory');
pg1.run;

model.save(fullfile(paths.modelsDir, 'ICRCell.mph'));
fprintf('SUCCESS: native trajectory plot created and model saved.\n');
end
