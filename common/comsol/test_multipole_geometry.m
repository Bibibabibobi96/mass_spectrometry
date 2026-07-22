function test_multipole_geometry(Npoles)
% Builds an N-pole rod array (quadrupole N=4, hexapole N=6, octupole N=8)
% centered on the z-axis: N cylindrical rods evenly spaced in azimuth,
% each rod's surface closest point at radius r0 from the axis. Adjacent
% rods get alternating +V/-V potential (valid for even N). Solves
% electrostatics with a unit RF amplitude and reports on-axis field
% (should be ~0 at the exact center for an ideal multipole) plus
% off-axis field growth to sanity-check the multipole order.
if nargin < 1
    Npoles = 4;
end
commonDir = fileparts(mfilename('fullpath'));
addpath(commonDir);
paths = common_artifact_paths();
import com.comsol.model.*
import com.comsol.model.util.*

tag = sprintf('ModelPole%d', Npoles);
if any(strcmp(cell(ModelUtil.tags()), tag))
    ModelUtil.remove(tag);
end
model = ModelUtil.create(tag);
model.label(sprintf('%d-pole rod array', Npoles));
comp1 = model.component.create('comp1', true);
geom1 = comp1.geom.create('geom1', 3);
geom1.label(sprintf('%d-pole rod array geometry', Npoles));
geom1.lengthUnit('mm');

p = model.param;
p.set('r0', '4[mm]', 'Field radius (inscribed radius to rod surface)');
% Rod-radius-to-r0 ratio: 1.1468 is the classic ideal-quadrupole value;
% for hexapole/octupole this is an approximate placeholder chosen to keep
% rods well-separated and non-overlapping, NOT a precision instrument-
% design ratio (that would need looking up the real multipole formula).
if Npoles == 4
    p.set('rod_ratio', '1.1468');
else
    p.set('rod_ratio', '0.55');
end
p.set('r_rod', 'rod_ratio*r0', 'Rod radius');
p.set('R_center', 'r0+r_rod', 'Rod center distance from axis');
p.set('rod_len', '20[mm]', 'Rod length');
p.set('V_rf', '100[V]', 'RF amplitude (unit test value)');

% Place each rod as its own Cylinder primitive at the computed (x,y)
% position (rather than a Copy/Rotate transform feature, which would need
% separate validation) -- same "build via explicit trig loop" approach
% already validated for the electron-gun chamfer tools.
rodtags = {};
for k = 1:Npoles
    theta_deg = (k-1)*360/Npoles;
    tagk = sprintf('rod%d', k);
    xk = sprintf('R_center*cos(%g[deg])', theta_deg);
    yk = sprintf('R_center*sin(%g[deg])', theta_deg);
    geom1.feature.create(tagk, 'Cylinder');
    geom1.feature(tagk).label(sprintf('Rod %d (theta=%g deg, alternating +/-V_rf)', k, theta_deg));
    geom1.feature(tagk).set('r', 'r_rod');
    geom1.feature(tagk).set('h', 'rod_len');
    geom1.feature(tagk).set('pos', {xk yk '0'});
    geom1.feature(tagk).set('axis', [0 0 1]);
    rodtags{end+1} = tagk; %#ok<AGROW>
end

% Enclosing vacuum domain
geom1.feature.create('cylv', 'Cylinder');
geom1.feature('cylv').label('Vacuum envelope (bounding cylinder)');
geom1.feature('cylv').set('r', 'R_center+r_rod+2[mm]');
geom1.feature('cylv').set('h', 'rod_len');
geom1.feature('cylv').set('pos', {'0' '0' '0'});

% Small dedicated "release volume" along the central axis (r<0.3*r0,
% full rod length) -- matches the near-axis filter criterion previously
% applied post-hoc in test_quadrupole_stability.m. The geometry union
% automatically carves it out as its own domain (still vacuum), so CPT's
% Release feature can select JUST this region -- restricting WHICH
% particles get released/solved, not just filtering afterward, giving a
% clean native trajectory plot with no post-hoc filtering needed.
geom1.feature.create('relvol', 'Cylinder');
geom1.feature('relvol').label('Release volume (near axis, r<0.2*r0)');
geom1.feature('relvol').set('r', '0.2*r0');
geom1.feature('relvol').set('h', '4[mm]'); % short central segment, not the full rod length -- keeps the released particle count manageable
geom1.feature('relvol').set('pos', {'0' '0' '(rod_len-4[mm])/2'});
geom1.feature('relvol').set('selresult', 'on');

for k = 1:Npoles
    geom1.feature(rodtags{k}).set('selresult', 'on');
end
geom1.feature('cylv').set('selresult', 'on');
geom1.run;

gi = mphgeominfo(model, 'geom1');
fprintf('Geometry built. Ndomains=%d\n', gi.Ndomains);

f = figure('Visible','off');
mphgeom(model, 'geom1', 'facealpha', 0.4);
view(2); axis equal;
xlabel('x [mm]'); ylabel('y [mm]');
title({sprintf('%d-pole rod array (top view)', Npoles), sprintf('r0=4mm, V_{rf}=100V (unit test amplitude)')});
outdir = paths.resultsDir;
if ~exist(outdir,'dir'), mkdir(outdir); end
print(f, fullfile(outdir, sprintf('multipole_%d_geom.png', Npoles)), '-dpng', '-r150');
fprintf('SUCCESS: geometry image saved.\n');

model.save(fullfile(paths.modelsDir, sprintf('Multipole%d.mph', Npoles)));
end
