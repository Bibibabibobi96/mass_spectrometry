function phase1_geometry_coil_transverse()
% Phase 1 (transverse-coil variant): electron gun geometry with the
% helical tungsten filament mounted so its OWN helix axis is
% PERPENDICULAR to the gun's beam axis (axis = x), like a small spring
% strung sideways inside the Wehnelt cavity, instead of coaxial with the
% beam (phase1_geometry_coil.m). This matches how real directly-heated
% coiled filaments are typically mounted, and -- for an application like
% a mass-spec EI electron gun where only electron utilization (current
% reaching the collector) matters, not beam symmetry/imaging quality --
% is the more sensible orientation: each turn's "top" arc faces toward
% +z (the Wehnelt aperture/anode), rather than mostly radially/
% circumferentially as in the coaxial design (which caused ~92% of cold-
% emitted electrons to self-absorb on a neighboring turn).

componentRoot = fileparts(mfilename('fullpath'));
addpath(componentRoot);
paths = egun_paths();
import com.comsol.model.*
import com.comsol.model.util.*

model = ModelUtil.create('Model');
model.label('ElectronGunCoilTransverse');

%% Parameters
p = model.param;
p.set('coil_rmaj', '0.3[mm]',  'Filament coil radius (axis to wire center)');
p.set('coil_rmin', '0.05[mm]', 'Filament wire radius (0.1mm diameter tungsten wire)');
p.set('coil_turns','5',        'Filament coil number of turns');
p.set('coil_pitch','0.2[mm]',  'Filament coil axial pitch');
p.set('coil_len',  'coil_turns*coil_pitch', 'Filament coil length along its own (transverse) axis');
p.set('coil_zc',   '0.9[mm]',  'z-height of the coil''s own axis (centered inside the Wehnelt cavity, top arc facing the aperture)');

% Wehnelt cavity geometry is unchanged from phase1_geometry_coil.m, but
% z_weh_ceil/z_weh_top etc no longer derive from a cathode "h_cathode"
% envelope (there is no on-axis cathode block anymore) -- pick the same
% numeric values directly so downstream gun dimensions stay identical.
p.set('weh_skirt', '0.5[mm]',  'Wehnelt cup: how far open end extends below z=0 reference');
p.set('weh_gap',   '0.5[mm]',  'Reference gap used to place the cavity ceiling');
p.set('weh_wall',  '0.5[mm]',  'Wehnelt cup: front wall thickness (contains aperture)');
p.set('r_weh_cavity','1.5[mm]','Wehnelt cup: internal cavity radius (encloses coil)');
p.set('r_weh_out', '4[mm]',    'Wehnelt outer radius');
p.set('r_weh_hole','1[mm]',    'Wehnelt aperture radius');
p.set('gap2',      '12[mm]',   'Gap: Wehnelt front face to anode bottom');
p.set('r_an_out',  '8[mm]',    'Anode outer radius');
p.set('r_an_hole', '1.5[mm]',  'Anode aperture radius');
p.set('h_an',      '1[mm]',    'Anode thickness');
p.set('drift',     '3[mm]',    'Drift space after anode');
p.set('r_domain',  '10[mm]',   'Vacuum domain radius');
p.set('z_margin',  '1[mm]',    'Vacuum domain margin below Wehnelt open end');
p.set('chamfer_d', '0.1[mm]',  'Chamfer distance on Wehnelt/anode electrode edges');

p.set('V_cathode', '0[V]',     'Cathode (filament) potential');
p.set('V_wehnelt', '-0.5[V]',  'Wehnelt (control electrode) potential');
p.set('V_anode',   '70[V]',    'Anode potential (sets 70 eV exit energy)');

p.set('z_weh_bot',  '-weh_skirt');
p.set('z_weh_ceil', '1[mm]+weh_gap');   % same numeric ceiling (1.5mm) as the coaxial version
p.set('z_weh_top',  'z_weh_ceil+weh_wall');
p.set('z_an_bot',   'z_weh_top+gap2');
p.set('z_an_top',   'z_an_bot+h_an');
p.set('z_dom_bot',  'z_weh_bot-z_margin');
p.set('z_dom_top',  'z_an_top+drift');

%% Component + geometry
comp1 = model.component.create('comp1', true);
geom1 = comp1.geom.create('geom1', 3);
geom1.lengthUnit('mm');

% --- Cathode (filament): helical coil, axis TRANSVERSE (x) to the beam
% (z) axis, centered at x=0 (spans -coil_len/2 .. +coil_len/2), y=0, at
% height z=coil_zc so its top arc faces the Wehnelt aperture above it.
geom1.feature.create('hel1', 'Helix');
geom1.feature('hel1').label('Cathode Coil (Filament, transverse)');
geom1.feature('hel1').set('rmaj', 'coil_rmaj');
geom1.feature('hel1').set('rmin', 'coil_rmin');
geom1.feature('hel1').set('axialpitch', 'coil_pitch');
geom1.feature('hel1').set('turns', 'coil_turns');
geom1.feature('hel1').set('axistype', 'x');
geom1.feature('hel1').set('pos', {'-coil_len/2' '0' 'coil_zc'});

% --- Wehnelt electrode: cap/cup shape (same as coaxial version) ---
geom1.feature.create('cyl2', 'Cylinder');
geom1.feature('cyl2').label('Wehnelt Outer');
geom1.feature('cyl2').set('r', 'r_weh_out');
geom1.feature('cyl2').set('h', 'z_weh_top-z_weh_bot');
geom1.feature('cyl2').set('pos', {'0' '0' 'z_weh_bot'});

geom1.feature.create('cyl2c', 'Cylinder');
geom1.feature('cyl2c').label('Wehnelt Cavity');
geom1.feature('cyl2c').set('r', 'r_weh_cavity');
geom1.feature('cyl2c').set('h', '(z_weh_ceil-z_weh_bot)+0.2[mm]');
geom1.feature('cyl2c').set('pos', {'0' '0' 'z_weh_bot-0.2[mm]'});

geom1.feature.create('cyl3', 'Cylinder');
geom1.feature('cyl3').label('Wehnelt Aperture');
geom1.feature('cyl3').set('r', 'r_weh_hole');
geom1.feature('cyl3').set('h', '(z_weh_top-z_weh_ceil)+0.4[mm]');
geom1.feature('cyl3').set('pos', {'0' '0' 'z_weh_ceil-0.2[mm]'});

geom1.feature.create('dif1a', 'Difference');
geom1.feature('dif1a').label('Wehnelt Cup (hollowed)');
geom1.feature('dif1a').selection('input').set({'cyl2'});
geom1.feature('dif1a').selection('input2').set({'cyl2c'});

geom1.feature.create('dif1', 'Difference');
geom1.feature('dif1').label('Wehnelt Blank');
geom1.feature('dif1').selection('input').set({'dif1a'});
geom1.feature('dif1').selection('input2').set({'cyl3'});

% --- Anode: outer disk minus aperture hole ---
geom1.feature.create('cyl4', 'Cylinder');
geom1.feature('cyl4').label('Anode Outer');
geom1.feature('cyl4').set('r', 'r_an_out');
geom1.feature('cyl4').set('h', 'h_an');
geom1.feature('cyl4').set('pos', {'0' '0' 'z_an_bot'});

geom1.feature.create('cyl5', 'Cylinder');
geom1.feature('cyl5').label('Anode Hole');
geom1.feature('cyl5').set('r', 'r_an_hole');
geom1.feature('cyl5').set('h', 'h_an+0.4[mm]');
geom1.feature('cyl5').set('pos', {'0' '0' 'z_an_bot-0.2[mm]'});

geom1.feature.create('dif2', 'Difference');
geom1.feature('dif2').label('Anode Blank');
geom1.feature('dif2').selection('input').set({'cyl4'});
geom1.feature('dif2').selection('input2').set({'cyl5'});

% --- Vacuum domain: enclosing cylinder ---
geom1.feature.create('cyl6', 'Cylinder');
geom1.feature('cyl6').label('Vacuum Domain');
geom1.feature('cyl6').set('r', 'r_domain');
geom1.feature('cyl6').set('h', 'z_dom_top-z_dom_bot');
geom1.feature('cyl6').set('pos', {'0' '0' 'z_dom_bot'});

%% Manual chamfer tools (Wehnelt & anode only, same as coaxial version)
tags.weh = {}; tags.an = {};
tags.weh{end+1} = make_rim_tool(geom1, 'wt1', 'r_weh_out',  'z_weh_bot',  'chamfer_d', 'outer_bottom');
tags.weh{end+1} = make_rim_tool(geom1, 'wt2', 'r_weh_out',  'z_weh_top',  'chamfer_d', 'outer_top');
tags.weh{end+1} = make_rim_tool(geom1, 'wt3', 'r_weh_hole', 'z_weh_ceil', 'chamfer_d', 'inner_bottom');
tags.weh{end+1} = make_rim_tool(geom1, 'wt4', 'r_weh_hole', 'z_weh_top',  'chamfer_d', 'inner_top');
tags.an{end+1} = make_rim_tool(geom1, 'at1', 'r_an_out',  'z_an_bot', 'chamfer_d', 'outer_bottom');
tags.an{end+1} = make_rim_tool(geom1, 'at2', 'r_an_out',  'z_an_top', 'chamfer_d', 'outer_top');
tags.an{end+1} = make_rim_tool(geom1, 'at3', 'r_an_hole', 'z_an_bot', 'chamfer_d', 'inner_bottom');
tags.an{end+1} = make_rim_tool(geom1, 'at4', 'r_an_hole', 'z_an_top', 'chamfer_d', 'inner_top');

geom1.feature.create('chdif2', 'Difference');
geom1.feature('chdif2').label('Wehnelt (chamfered)');
geom1.feature('chdif2').selection('input').set({'dif1'});
geom1.feature('chdif2').selection('input2').set(tags.weh);

geom1.feature.create('chdif3', 'Difference');
geom1.feature('chdif3').label('Anode (chamfered)');
geom1.feature('chdif3').selection('input').set({'dif2'});
geom1.feature('chdif3').selection('input2').set(tags.an);

geom1.run;

gi = mphgeominfo(model, 'geom1');
fprintf('Geometry build complete.\n');
disp(gi);

if ~exist(paths.modelWorkspaceDir, 'dir'), mkdir(paths.modelWorkspaceDir); end
model.save(fullfile(paths.modelWorkspaceDir, 'ElectronGun_CoilT.mph'));
fprintf('SUCCESS: model saved.\n');
end

function tag = make_rim_tool(geom1, id, r0, z0, d, kind)
cylTag  = ['rc_' id]; coneTag = ['rn_' id]; difTag  = ['rd_' id];
switch kind
    case 'outer_top'
        posz = [z0 '-' d];
        geom1.feature.create(cylTag, 'Cylinder'); geom1.feature(cylTag).set('r', r0);
        geom1.feature(cylTag).set('h', d); geom1.feature(cylTag).set('pos', {'0' '0' posz});
        geom1.feature.create(coneTag, 'Cone'); geom1.feature(coneTag).set('r', r0);
        geom1.feature(coneTag).set('specifytop', 'radius'); geom1.feature(coneTag).set('rtop', ['(' r0 '-' d ')']);
        geom1.feature(coneTag).set('h', d); geom1.feature(coneTag).set('pos', {'0' '0' posz});
        geom1.feature.create(difTag, 'Difference');
        geom1.feature(difTag).selection('input').set({cylTag}); geom1.feature(difTag).selection('input2').set({coneTag});
    case 'outer_bottom'
        posz = z0;
        geom1.feature.create(cylTag, 'Cylinder'); geom1.feature(cylTag).set('r', r0);
        geom1.feature(cylTag).set('h', d); geom1.feature(cylTag).set('pos', {'0' '0' posz});
        geom1.feature.create(coneTag, 'Cone'); geom1.feature(coneTag).set('r', ['(' r0 '-' d ')']);
        geom1.feature(coneTag).set('specifytop', 'radius'); geom1.feature(coneTag).set('rtop', r0);
        geom1.feature(coneTag).set('h', d); geom1.feature(coneTag).set('pos', {'0' '0' posz});
        geom1.feature.create(difTag, 'Difference');
        geom1.feature(difTag).selection('input').set({cylTag}); geom1.feature(difTag).selection('input2').set({coneTag});
    case 'inner_top'
        posz = [z0 '-' d];
        geom1.feature.create(coneTag, 'Cone'); geom1.feature(coneTag).set('r', r0);
        geom1.feature(coneTag).set('specifytop', 'radius'); geom1.feature(coneTag).set('rtop', ['(' r0 '+' d ')']);
        geom1.feature(coneTag).set('h', d); geom1.feature(coneTag).set('pos', {'0' '0' posz});
        geom1.feature.create(cylTag, 'Cylinder'); geom1.feature(cylTag).set('r', r0);
        geom1.feature(cylTag).set('h', d); geom1.feature(cylTag).set('pos', {'0' '0' posz});
        geom1.feature.create(difTag, 'Difference');
        geom1.feature(difTag).selection('input').set({coneTag}); geom1.feature(difTag).selection('input2').set({cylTag});
    case 'inner_bottom'
        posz = z0;
        geom1.feature.create(coneTag, 'Cone'); geom1.feature(coneTag).set('r', ['(' r0 '+' d ')']);
        geom1.feature(coneTag).set('specifytop', 'radius'); geom1.feature(coneTag).set('rtop', r0);
        geom1.feature(coneTag).set('h', d); geom1.feature(coneTag).set('pos', {'0' '0' posz});
        geom1.feature.create(cylTag, 'Cylinder'); geom1.feature(cylTag).set('r', r0);
        geom1.feature(cylTag).set('h', d); geom1.feature(cylTag).set('pos', {'0' '0' posz});
        geom1.feature.create(difTag, 'Difference');
        geom1.feature(difTag).selection('input').set({coneTag}); geom1.feature(difTag).selection('input2').set({cylTag});
    otherwise
        error('Unknown rim kind: %s', kind);
end
tag = difTag;
end
