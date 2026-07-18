function result = ms_rf_quadrupole_collision_cooling(Nd_val, E_push, label)
% RF quadrupole collision-cooling ion guide --
% demonstrates the real physical mechanism (used in essentially all
% commercial oa-TOF/Q-TOF instruments) by which a continuous ion beam
% arriving with some initial injection energy (~10-30eV from an upstream
% source/extraction) is "cooled" down to a small, well-controlled residual
% forward kinetic energy (a few eV) before entering the orthogonal
% accelerator:
%   1. RF (quadrupole, r0=4mm) provides radial confinement so the ion
%      isn't lost to the rods while this takes many RF cycles / a long
%      residence time.
%   2. A light buffer gas (few mTorr scale, Nd~1e20-1e21/m^3) fills the
%      guide -- the CPT `Collisions`+`Elastic` mechanism (validated in
%      COMSOL_API.md under Wall, termination, and collisions) makes the ion undergo MANY
%      momentum-exchange collisions with the (implicitly near-stationary,
%      "cold gas approximation") background gas over the guide length,
%      damping its kinetic energy down from the initial value.
%   3. A weak, deliberate axial DC bias field (E_push, V/m scale) keeps
%      the ion moving forward and sets the FINAL, STABILIZED residual
%      energy (once the accelerating push and the collisional drag roughly
%      balance) -- collisional cooling ALONE would just asymptote the ion
%      toward zero net forward velocity; the small bias is what gives the
%      real, controlled "few eV" residual energy fed into the downstream
%      orthogonal accelerator.
%
% Realistic commercial-scale guide dimensions: r0=4mm (field radius),
% rod length=150mm (typical RF-only ion guide length).

componentRoot = fileparts(fileparts(mfilename('fullpath')));
addpath(componentRoot);
paths = rf_quadrupole_paths();
addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
try
    mphstart(2036);
catch ME
    if ~contains(ME.message, 'Already connected'), rethrow(ME); end
end
import com.comsol.model.*
import com.comsol.model.util.*

if nargin<1, Nd_val = 3e20; end
if nargin<2, E_push = 20; end % V/m, weak axial bias
if nargin<3, label = sprintf('Nd%.0e_Epush%g', Nd_val, E_push); end

if any(strcmp(cell(ModelUtil.tags()), 'ModelCoolQuad'))
    ModelUtil.remove('ModelCoolQuad');
end
model = ModelUtil.create('ModelCoolQuad');
comp1 = model.component.create('comp1', true);
geom1 = comp1.geom.create('geom1', 3);
geom1.label('RF quadrupole cooling guide geometry');
geom1.lengthUnit('mm');

p = model.param;
p.set('r0', '4[mm]', 'Field radius');
p.set('rod_ratio', '1.1468', 'Ideal quadrupole rod-radius ratio');
p.set('r_rod', 'rod_ratio*r0');
p.set('R_center', 'r0+r_rod');
p.set('L_guide', '150[mm]', 'Guide length (realistic commercial RF-only ion-guide scale)');
p.set('V_rf', '82[V]', 'RF amplitude from the validated quadrupole stability test');
p.set('f_rf', '1[MHz]');

rodtags = {};
for k = 1:4
    theta_deg = (k-1)*360/4;
    tagk = sprintf('rod%d', k);
    xk = sprintf('R_center*cos(%g[deg])', theta_deg);
    yk = sprintf('R_center*sin(%g[deg])', theta_deg);
    geom1.feature.create(tagk, 'Cylinder');
    geom1.feature(tagk).label(sprintf('Quadrupole rod %d (theta=%g deg)', k, theta_deg));
    geom1.feature(tagk).set('r', 'r_rod');
    geom1.feature(tagk).set('h', 'L_guide');
    geom1.feature(tagk).set('pos', {xk yk '0'});
    geom1.feature(tagk).set('axis', [0 0 1]);
    rodtags{end+1} = tagk; %#ok<AGROW>
end

geom1.feature.create('cylv', 'Cylinder');
geom1.feature('cylv').label('Vacuum envelope (bounding cylinder)');
geom1.feature('cylv').set('r', 'R_center+r_rod+2[mm]');
geom1.feature('cylv').set('h', 'L_guide');
geom1.feature('cylv').set('pos', {'0' '0' '0'});

geom1.feature.create('relvol', 'Cylinder');
geom1.feature('relvol').label('Release volume (near-axis, entrance)');
geom1.feature('relvol').set('r', '0.2*r0');
geom1.feature('relvol').set('h', '4[mm]');
geom1.feature('relvol').set('pos', {'0' '0' '1[mm]'});
geom1.feature('relvol').set('selresult', 'on');

for k = 1:4, geom1.feature(rodtags{k}).set('selresult', 'on'); end
geom1.feature('cylv').set('selresult', 'on');
geom1.run;
gi = mphgeominfo(model, 'geom1');
fprintf('Geometry built. Ndomains=%d\n', gi.Ndomains);

rodomtags = cellfun(@(t) sprintf('geom1_%s_dom', t), rodtags, 'UniformOutput', false);
comp1.selection.create('sel_vac', 'Complement');
comp1.selection('sel_vac').label('Guide vacuum/gas (all domains except rods)');
comp1.selection('sel_vac').set('input', rodomtags);
vac_n = numel(comp1.selection('sel_vac').entities());
fprintf('sel_vac resolves to %d domain(s)\n', vac_n);
if vac_n ~= 2, error('Expected 2 domains (rest-of-guide + relvol), got %d', vac_n); end

mat_vac = model.material.create('mat_vac', 'Common');
mat_vac.label('Buffer gas (relpermittivity=1)');
mat_vac.selection.named('sel_vac');
mat_vac.propertyGroup('def').set('relpermittivity', {'1'});
for k = 1:4
    matk = model.material.create(sprintf('mat_rod%d', k), 'Common');
    matk.label(sprintf('rod%d material', k));
    matk.selection.named(sprintf('geom1_rod%d_dom', k));
    matk.propertyGroup('def').set('relpermittivity', {'1'});
end

es2 = comp1.physics.create('es2', 'Electrostatics', 'geom1');
es2.label('Electrostatics: quadrupole RF unit pattern (100V)');
es2.selection.named('sel_vac');
for k = 1:4
    tagb = sprintf('selb_rod%d', k);
    comp1.selection.create(tagb, 'Adjacent');
    comp1.selection(tagb).label(sprintf('rod%d boundary', k));
    comp1.selection(tagb).set('input', {sprintf('geom1_rod%d_dom', k)});
    v0 = 100*(-1)^(k+1);
    potk = es2.create(sprintf('pot_rod%d', k), 'ElectricPotential', 2);
    potk.label(sprintf('rod%d RF unit potential (%dV)', k, v0));
    potk.selection.named(tagb);
    potk.set('V0', sprintf('%d', v0));
end

mesh1 = comp1.mesh.create('mesh1');
mesh1.label('Mesh (hauto=4)');
mesh1.feature('size').set('hauto', 4);
mesh1.feature.create('ftet1', 'FreeTet');
mesh1.run;
mi = mphmeshstats(model, 'mesh1');
fprintf('mesh: isempty=%d iscomplete=%d\n', mi.isempty, mi.iscomplete);
if mi.isempty || ~mi.iscomplete, error('mesh failed'); end

std1 = model.study.create('std1');
std1.label('Stationary: RF unit field');
std1.create('stat1', 'Stationary');
model.sol.create('sol1');
model.sol('sol1').label('Solution: RF unit field');
model.sol('sol1').study('std1');
model.sol('sol1').createAutoSequence('std1');
model.sol('sol1').runAll;
fprintf('SUCCESS: electrostatics (RF unit field) solved.\n');

m_kg = 100*1.66054e-27;
cpt = comp1.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
cpt.label(sprintf('Charged Particle Tracing: cooling guide %s', label));
cpt.selection.named('sel_vac');
cpt.feature('pp1').set('mp', sprintf('%.6e[kg]', m_kg));
cpt.feature('pp1').set('Z', '1');

KE0_eV = 20;
v0 = sqrt(2*KE0_eV*1.602176e-19/m_kg);
fprintf('injection speed at %geV: %.4e m/s\n', KE0_eV, v0);
rel1 = cpt.create('rel1', 'Release', 3);
rel1.label(sprintf('Release: injection KE=%geV', KE0_eV));
rel1.selection.named('geom1_relvol_dom');
rel1.set('v0', {'0' '0' sprintf('%.6e[m/s]', v0)});

ef1 = cpt.create('ef1', 'ElectricForce', 3);
ef1.label('Electric Force: RF confinement + weak axial DC bias');
ef1.selection.named('sel_vac');
ef1.set('E_src', 'userdef');
ef1.set('E', { ...
    '(V_rf/100)*es.Ex*cos(2*pi*f_rf*t)', ...
    '(V_rf/100)*es.Ey*cos(2*pi*f_rf*t)', ...
    sprintf('(V_rf/100)*es.Ez*cos(2*pi*f_rf*t)+%g[V/m]', E_push) });
% NOTE: only one Electrostatics interface exists in this model (tagged
% 'es2' at the API level), so per COMSOL's type+creation-order namespace
% rule documented in COMSOL_API.md, it's actually namespaced 'es' (the first/only interface of
% its type), not 'es2' -- the API tag and the expression namespace are
% independent.

coll1 = cpt.create('coll1', 'Collisions', 3);
coll1.label(sprintf('Collisions: buffer gas Nd=%.2g /m^3', Nd_val));
coll1.selection.named('sel_vac');
coll1.set('Nd', sprintf('%.6e[1/m^3]', Nd_val));
coll1.set('CollisionDetection', 'NullCollisionMethodColdGasApproximation');
coll1.set('CountAllCollisions', true);
elastic1 = coll1.create('elastic1', 'Elastic');
elastic1.label('Elastic collisions (default N2/Ar-like cross section)');
elastic1.set('CountCollisions', true);

Tsim = 150e-6; dtstep = 0.5e-6;
std2 = model.study.create('std2');
std2.label(sprintf('Time-dependent: cooling guide %s', label));
tstep = std2.create('time1', 'Transient');
tstep.label('Transient solver (0-150us)');
tstep.set('tlist', sprintf('range(0,%g,%g)', dtstep, Tsim));
tstep.setEntry('activate', 'es2', false);
tstep.setEntry('activate', 'cpt', true);
cpt.feature('pp1').set('StudyStep', 'std2/time1');
rel1.set('StudyStep', 'std2/time1');
coll1.set('StudyStep', 'std2/time1');
elastic1.set('StudyStep', 'std2/time1');

soltags = cell(model.sol.tags());
es_sol_tag = soltags{1};
model.sol.create('sol2');
model.sol('sol2').label(sprintf('Solution: cooling guide CPT %s', label));
model.sol('sol2').study('std2');
model.sol('sol2').createAutoSequence('std2');
model.sol('sol2').feature('v1').set('notsolmethod', 'sol');
model.sol('sol2').feature('v1').set('notsol', es_sol_tag);
model.sol('sol2').feature('t1').set('tstepsbdf', 'strict');
model.sol('sol2').runAll;
fprintf('[%s] SUCCESS: cooling guide CPT solved.\n', label);

pdset1 = model.result.dataset.create('pdset1', 'Particle');
pdset1.label(sprintf('Particle dataset: cooling guide %s', label));
pdset1.set('solution', 'sol2');
pd = mphparticle(model, 'dataset', 'pdset1', 'expr', {'cpt.coll1.elastic1.Nc'});
nP = size(pd.p,2);
fprintf('[%s] ions released: %d\n', label, nP);

z = squeeze(pd.p(:,:,3));
vx = squeeze(pd.v(:,:,1)); vy = squeeze(pd.v(:,:,2)); vz = squeeze(pd.v(:,:,3));
speed = sqrt(vx.^2+vy.^2+vz.^2);
KE_eV = 0.5*m_kg*speed.^2/1.602176e-19;
t = pd.t;
Nc_end = pd.d1(end,:);

zEnd = z(end,:);
exited = zEnd > 148; % reached near the guide exit
KE_end = KE_eV(end,:);
fprintf('[%s] ions reaching guide exit (z>148mm): %d / %d (%.1f%%)\n', label, sum(exited), nP, 100*sum(exited)/nP);
fprintf('[%s] mean KE at t_end: %.3f eV (started at %g eV)\n', label, mean(KE_eV(end,:),'omitnan'), KE0_eV);
fprintf('[%s] mean elastic collisions experienced: %.2f\n', label, mean(Nc_end,'omitnan'));

result = struct('label', label, 'Nd', Nd_val, 'E_push', E_push, 'nP', nP, ...
    'frac_exited', sum(exited)/nP, 'meanKE_end', mean(KE_eV(end,:),'omitnan'), ...
    'meanNc', mean(Nc_end,'omitnan'));

resultsDir = paths.resultsDir;
if ~exist(resultsDir,'dir'), mkdir(resultsDir); end
fh = figure('Visible','off');
subplot(1,2,1);
hold on;
for i = 1:min(30,nP)
    plot(z(:,i), KE_eV(:,i), '-');
end
xlabel('z [mm]'); ylabel('kinetic energy [eV]'); grid on;
title('ion KE vs axial position (cooling trend)');
subplot(1,2,2);
hold on;
for i = 1:min(30,nP)
    plot(t*1e6, KE_eV(:,i), '-');
end
xlabel('t [\mus]'); ylabel('kinetic energy [eV]'); grid on;
title('ion KE vs time');
sgtitle({sprintf('RF quadrupole collision cooling, %s', label), ...
    sprintf('100amu +1 ion, KE0=%geV, Nd=%.2g/m^3, E_{push}=%gV/m, mean KE_{end}=%.2feV', ...
    KE0_eV, Nd_val, E_push, result.meanKE_end)}, 'Interpreter','none');
print(fh, fullfile(resultsDir, sprintf('ms_rf_quadrupole_collision_cooling_%s.png', strrep(label,' ','_'))), '-dpng', '-r150');
fprintf('[%s] SUCCESS: cooling trend plot saved.\n', label);

pg1 = model.result.create('pg_traj', 'PlotGroup3D');
pg1.label(sprintf('Cooling guide: %s trajectories', label));
pg1.set('data', 'pdset1');
pg1.set('titletype', 'manual');
pg1.set('title', sprintf('Collisional cooling: %s, mean KE_end=%.2feV', label, result.meanKE_end));
trj1 = pg1.create('trj1', 'ParticleTrajectories');
trj1.label('Ion trajectories (cooling guide)');
pg1.run;

modelsDir = paths.modelsDir;
if ~exist(modelsDir, 'dir'), mkdir(modelsDir); end
model.save(fullfile(modelsDir, sprintf('MS_RFQuadrupoleCollisionCooling_%s.mph', strrep(label,' ','_'))));
fprintf('[%s] SUCCESS: native trajectory plot created and model saved.\n', label);
end
