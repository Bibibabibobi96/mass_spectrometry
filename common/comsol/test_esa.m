function result = test_esa(KE_eV, label)
% Electrostatic Sector Analyzer (ESA): concentric cylindrical capacitor.
% An ion moving tangentially at the mean radius R0 needs centripetal
% force m*v^2/R0 = q*E(R0); for a coaxial cylindrical capacitor,
% E(r) = V0/(r*ln(R2/R1)). The design KE (here 1000eV, 100amu) is chosen
% so V0 gives exactly the right E(R0) -- ions AT that energy should
% follow a near-circular arc and stay within the annular gap; ions with
% a different KE should drift toward one electrode (energy filtering,
% independent of mass -- the defining property of an ESA vs a magnetic
% sector).

commonDir = fileparts(mfilename('fullpath'));
addpath(commonDir);
paths = common_artifact_paths();
addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
mphstart(2036);
import com.comsol.model.*
import com.comsol.model.util.*

if nargin < 2, label = sprintf('KE%geV', KE_eV); end

if any(strcmp(cell(ModelUtil.tags()), 'ModelESA'))
    ModelUtil.remove('ModelESA');
end
model = ModelUtil.create('ModelESA');
comp1 = model.component.create('comp1', true);
geom1 = comp1.geom.create('geom1', 3);
geom1.label('ESA geometry (coaxial cylinder capacitor)');
geom1.lengthUnit('mm');

p = model.param;
p.set('R1', '40[mm]'); p.set('R2', '50[mm]'); p.set('R2o', '52[mm]');
p.set('h_cyl', '10[mm]');  % 'h' collides with a reserved COMSOL global variable name
p.set('R0', '(R1+R2)/2');
% Design: 100amu, +1, 1000eV ion at R0 -> exact coaxial-cylinder voltage
m_design = 100*1.66054e-27; KE_design_eV = 1000;
v_design = sqrt(2*KE_design_eV*1.602176e-19/m_design);
E_needed = m_design*v_design^2/(1.602176e-19*0.045); % at R0=45mm
V0_design = E_needed*0.045*log(50/40); % V0 = E*r*ln(R2/R1)
fprintf('Design: v=%.4e m/s, E_needed=%.4e V/m, V0=%.2f V\n', v_design, E_needed, V0_design);
p.set('V_inner', '0[V]');
p.set('V_outer', sprintf('%.4f[V]', V0_design));

geom1.feature.create('cinner', 'Cylinder');
geom1.feature('cinner').label('Inner electrode (R1=40mm, grounded)');
geom1.feature('cinner').set('r', 'R1'); geom1.feature('cinner').set('h', 'h_cyl');
geom1.feature('cinner').set('pos', {'0' '0' '0'});
geom1.feature.create('couterO', 'Cylinder');
geom1.feature('couterO').label('Outer electrode outer solid');
geom1.feature('couterO').set('r', 'R2o'); geom1.feature('couterO').set('h', 'h_cyl');
geom1.feature('couterO').set('pos', {'0' '0' '0'});
geom1.feature.create('couterI', 'Cylinder');
geom1.feature('couterI').label('Outer electrode inner bore (R2=50mm)');
geom1.feature('couterI').set('r', 'R2'); geom1.feature('couterI').set('h', 'h_cyl+0.4[mm]');
geom1.feature('couterI').set('pos', {'0' '0' '-0.2[mm]'});
geom1.feature.create('couter', 'Difference');
geom1.feature('couter').label('Outer electrode (R2=50mm, V_outer)');
geom1.feature('couter').selection('input').set({'couterO'});
geom1.feature('couter').selection('input2').set({'couterI'});

% Overall bounding vacuum cylinder -- without this, the gap between R1
% and R2 is simply EMPTY (not part of ANY domain), so Complement(cinner,
% couter) has nothing to complement against (0 domains, not the vacuum
% annulus). Must span at least out to R2o so the automatic union/imprint
% creates the annular gap as its own domain.
geom1.feature.create('cylv', 'Cylinder');
geom1.feature('cylv').label('Vacuum envelope (bounding cylinder)');
geom1.feature('cylv').set('r', 'R2o');
geom1.feature('cylv').set('h', 'h_cyl');
geom1.feature('cylv').set('pos', {'0' '0' '0'});

% Small dedicated "release volume" at the design injection point
% (R0,0,z=5), well inside the annular gap (40<r<50mm) -- represents a
% physically meaningful entry point instead of releasing across the
% WHOLE annulus (most of which starts at the wrong angular position for
% the fixed tangential v0 direction used below, and never represents a
% real injected beam).
geom1.feature.create('relvol', 'Cylinder');
geom1.feature('relvol').label('Release volume (design injection point R0,0,5mm)');
geom1.feature('relvol').set('r', '0.5[mm]');
geom1.feature('relvol').set('h', '1[mm]');
geom1.feature('relvol').set('pos', {'R0' '0' '4.5[mm]'});
geom1.feature('relvol').set('selresult', 'on');

for t = {'cinner','couter'}
    geom1.feature(t{1}).set('selresult','on');
end
geom1.run;
gi = mphgeominfo(model, 'geom1');
fprintf('Geometry built. Ndomains=%d\n', gi.Ndomains);

comp1.selection.create('sel_vac', 'Complement');
comp1.selection('sel_vac').label('Vacuum (annular gap + relvol)');
comp1.selection('sel_vac').set('input', {'geom1_cinner_dom','geom1_couter_dom'});
vac_n = numel(comp1.selection('sel_vac').entities());
fprintf('sel_vac resolves to %d domain(s)\n', vac_n);
if vac_n ~= 2, error('Expected 2 vacuum domains (rest-of-vacuum + relvol), got %d', vac_n); end
fprintf('geom1_relvol_dom resolves to %d domain(s)\n', numel(comp1.selection('geom1_relvol_dom').entities()));

mat_vac = model.material.create('mat_vac', 'Common');
mat_vac.label('Vacuum (relpermittivity=1)');
mat_vac.selection.named('sel_vac');
mat_vac.propertyGroup('def').set('relpermittivity', {'1'});
matLabels = struct('cinner','Inner electrode material','couter','Outer electrode material');
for t = {'cinner','couter'}
    matk = model.material.create(sprintf('mat_%s',t{1}), 'Common');
    matk.label(matLabels.(t{1}));
    matk.selection.named(sprintf('geom1_%s_dom', t{1}));
    matk.propertyGroup('def').set('relpermittivity', {'1'});
end

es = comp1.physics.create('es', 'Electrostatics', 'geom1');
es.label('Electrostatics: ESA coaxial capacitor');
es.selection.named('sel_vac');
comp1.selection.create('selb_inner', 'Adjacent');
comp1.selection('selb_inner').label('Inner electrode boundary');
comp1.selection('selb_inner').set('input', {'geom1_cinner_dom'});
comp1.selection.create('selb_outer', 'Adjacent');
comp1.selection('selb_outer').label('Outer electrode boundary');
comp1.selection('selb_outer').set('input', {'geom1_couter_dom'});
pot_i = es.create('pot_inner', 'ElectricPotential', 2);
pot_i.label('Inner electrode potential (V_inner=0)');
pot_i.selection.named('selb_inner'); pot_i.set('V0', 'V_inner');
pot_o = es.create('pot_outer', 'ElectricPotential', 2);
pot_o.label('Outer electrode potential (V_outer, design voltage)');
pot_o.selection.named('selb_outer'); pot_o.set('V0', 'V_outer');

mesh1 = comp1.mesh.create('mesh1');
mesh1.label('Mesh (hauto=4)');
mesh1.feature('size').set('hauto', 4);
mesh1.feature.create('ftet1', 'FreeTet');
mesh1.run;
mi = mphmeshstats(model, 'mesh1');
if mi.isempty || ~mi.iscomplete, error('mesh failed'); end
fprintf('mesh OK\n');

std1 = model.study.create('std1');
std1.label('Stationary: ESA electrostatics');
std1.create('stat1', 'Stationary');
model.sol.create('sol1');
model.sol('sol1').label('Solution: ESA ES');
model.sol('sol1').study('std1');
model.sol('sol1').createAutoSequence('std1');
model.sol('sol1').runAll;
fprintf('SUCCESS: electrostatics solved.\n');

% Check E(r) at a few radii on the x-axis, compare to 1/r analytic law
rvals = [41 43 45 47 49];
coords = [rvals; zeros(1,numel(rvals)); 5*ones(1,numel(rvals))];
Eq = mphinterp(model, 'es.normE', 'coord', coords, 'dataset', 'dset1', 'matherr','off');
fprintf('\nE(r) vs analytic V0/(r*ln(R2/R1)):\n');
for i=1:numel(rvals)
    Eanalytic = V0_design/(rvals(i)*1e-3*log(50/40));
    fprintf('  r=%3dmm  E_FEM=%.4e  E_analytic=%.4e  ratio=%.4f\n', rvals(i), Eq(i), Eanalytic, Eq(i)/Eanalytic);
end

%% CPT: release ion tangentially at (R0,0,z=5) with the TEST energy KE_eV
cpt = comp1.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
cpt.label(sprintf('Charged Particle Tracing: ESA %s', label));
cpt.selection.named('sel_vac');
pp1 = cpt.feature('pp1');
pp1.label('Particle properties: 100amu +1 ion');
pp1.set('mp', sprintf('%.6e[kg]', m_design));
pp1.set('Z', '1');
rel1 = cpt.create('rel1', 'Release', 3);
rel1.label(sprintf('Release: injection point, KE=%g eV', KE_eV));
% Release ONLY from the small injection-point sub-domain at (R0,0,5mm)
% added above -- restricts WHICH particles get solved to a physically
% meaningful entry point matching the fixed tangential v0 direction used
% below (particles released elsewhere in the annulus would have the
% WRONG initial direction relative to their own position anyway).
rel1.selection.named('geom1_relvol_dom');
v_test = sqrt(2*KE_eV*1.602176e-19/m_design);
rel1.set('v0', {'0' sprintf('%.6e[m/s]',v_test) '0'}); % tangential (+y) at (R0,0,z)
ef1 = cpt.create('ef1', 'ElectricForce', 3);
ef1.label('Electric Force: from ESA ES field');
ef1.selection.named('sel_vac');
ef1.set('E_src', 'root.comp1.es.Ex');

std2 = model.study.create('std2');
std2.label(sprintf('Time-dependent: ESA %s', label));
tstep = std2.create('time1', 'Transient');
tstep.label('Transient solver (0-2us)');
tstep.set('tlist', 'range(0,2[ns],2000[ns])');
tstep.setEntry('activate', 'es', false);
tstep.setEntry('activate', 'cpt', true);
soltags = cell(model.sol.tags());
model.sol.create('sol2');
model.sol('sol2').label(sprintf('Solution: ESA CPT %s', label));
model.sol('sol2').study('std2');
model.sol('sol2').createAutoSequence('std2');
model.sol('sol2').feature('v1').set('notsolmethod', 'sol');
model.sol('sol2').feature('v1').set('notsol', soltags{1});
model.sol('sol2').runAll;
fprintf('[%s] SUCCESS: CPT solved.\n', label);

pdset1 = model.result.dataset.create('pdset1', 'Particle');
pdset1.label(sprintf('Particle dataset: ESA %s', label));
pdset1.set('solution', 'sol2');
pd = mphparticle(model, 'dataset', 'pdset1');
xAll = squeeze(pd.p(:,:,1)); yAll = squeeze(pd.p(:,:,2)); zAll = squeeze(pd.p(:,:,3));
rAll = sqrt(xAll.^2+yAll.^2);
fprintf('[%s] particles released from injection-point sub-volume: %d\n', label, size(xAll,2));
idxUse = 1;
r = rAll(:, idxUse); x = xAll(:, idxUse); y = yAll(:, idxUse);
r_valid = r(~isnan(r));
result = struct();
result.label = label;
result.r_min = min(r_valid);
result.r_max = max(r_valid);
result.escaped = any(r_valid < 40.05 | r_valid > 49.95);
fprintf('[%s] r range: [%.3f, %.3f] mm (R1=40, R2=50, R0=45); hit an electrode: %d\n', ...
    label, result.r_min, result.r_max, result.escaped);

resultsDir = paths.resultsDir;
if ~exist(resultsDir,'dir'), mkdir(resultsDir); end
fh = figure('Visible','off');
theta = linspace(0,2*pi,200);
plot(40*cos(theta), 40*sin(theta), 'k--'); hold on;
plot(50*cos(theta), 50*sin(theta), 'k--');
plot(x, y, '-o', 'MarkerSize', 2);
axis equal; grid on;
xlabel('x [mm]'); ylabel('y [mm]');
title({sprintf('ESA: %s (R1=40mm, R2=50mm dashed, R0=45mm design radius)', label), ...
    sprintf('particle: 100amu +1 ion, KE=%g eV (design KE=1000eV)', KE_eV)}, 'Interpreter', 'none');
print(fh, fullfile(resultsDir, sprintf('esa_trajectory_%s.png', strrep(label,' ','_'))), '-dpng', '-r150');
fprintf('[%s] SUCCESS: trajectory plot saved.\n', label);

% Native COMSOL result plot + save to disk (label-specific, since this
% function builds a fresh model per call and different test cases --
% design vs off-design energy -- should each be individually inspectable).
pg1 = model.result.create('pg_traj', 'PlotGroup3D');
pg1.label(sprintf('ESA: %s trajectory plot', label));
pg1.set('data', 'pdset1');
pg1.set('titletype', 'manual');
pg1.set('title', sprintf('ESA: 100amu +1 ion, KE=%g eV (design KE=1000eV), R1=40mm R2=50mm', KE_eV));
trj1 = pg1.create('trj1', 'ParticleTrajectories');
trj1.label(sprintf('%s ion trajectory', label));
pg1.run;
modelsDir = paths.modelsDir;
if ~exist(modelsDir, 'dir'), mkdir(modelsDir); end
model.save(fullfile(modelsDir, sprintf('ESA_%s.mph', strrep(label,' ','_'))));
fprintf('[%s] SUCCESS: native trajectory plot created and model saved.\n', label);
end
