function phase5_wehnelt_sweep()
% Phase 5: sweep Wehnelt aperture radius (r_weh_hole) and Wehnelt voltage
% (V_wehnelt) on the coil-filament electron gun (thermal emission @2700K,
% same physics as phase4_thermal_emission_coil.m). For each combination:
% rebuild geometry (aperture radius is a geometry parameter), rebuild ES
% (voltage is a boundary condition), rerun CPT, and record: collection
% efficiency (fraction reaching ~70eV band = passed the anode), fraction
% self-absorbed between coil turns, and beam radius (std of x,y) at the
% drift-region exit as a divergence proxy. Numeric results only (no
% per-run trajectory image export) to keep the sweep tractable.

addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
mphstart(2036);
import com.comsol.model.*
import com.comsol.model.util.*

r_weh_hole_list = [0.7 1.0 1.3];   % mm; 1.0 = baseline from phases 1-4
V_wehnelt_list  = [-1.0 -0.5 0.0]; % V;  -0.5 = baseline from phases 1-4

results = [];
for ri = 1:numel(r_weh_hole_list)
    rh = r_weh_hole_list(ri);
    for vi = 1:numel(V_wehnelt_list)
        vw = V_wehnelt_list(vi);
        fprintf('\n########## r_weh_hole=%.2fmm  V_wehnelt=%.2fV ##########\n', rh, vw);
        r = run_one_case(rh, vw);
        r.r_weh_hole = rh;
        r.V_wehnelt = vw;
        results = [results; r]; %#ok<AGROW>
    end
end

fprintf('\n\n================ SWEEP SUMMARY ================\n');
fprintf('%10s %10s %8s %10s %10s %12s %10s\n', ...
    'r_hole[mm]', 'V_weh[V]', 'N_rel', 'N_arrive', 'Collect%', 'SelfAbs%', 'BeamR[mm]');
for i = 1:numel(results)
    r = results(i);
    fprintf('%10.2f %10.2f %8d %10d %10.2f %12.2f %10.3f\n', ...
        r.r_weh_hole, r.V_wehnelt, r.n_released, r.n_arrived, r.collect_pct, r.selfabs_pct, r.beam_radius_mm);
end

save('C:\Users\Liao\PycharmProjects\PythonProject\comsol_results\wehnelt_sweep_results.mat', 'results');
fprintf('\nSUCCESS: sweep complete, results saved to comsol_results\\wehnelt_sweep_results.mat\n');
end

function res = run_one_case(rh, vw)
import com.comsol.model.*
import com.comsol.model.util.*

if any(strcmp(cell(ModelUtil.tags()), 'ModelSweep'))
    ModelUtil.remove('ModelSweep');
end
model = ModelUtil.create('ModelSweep');

%% Parameters (same as phase1_geometry_coil.m, with r_weh_hole/V_wehnelt overridden)
p = model.param;
p.set('h_cathode', '1[mm]');
p.set('coil_rmaj', '0.3[mm]');
p.set('coil_rmin', '0.05[mm]');
p.set('coil_turns','5');
p.set('coil_pitch','h_cathode/coil_turns');
p.set('weh_skirt', '0.5[mm]');
p.set('weh_gap',   '0.5[mm]');
p.set('weh_wall',  '0.5[mm]');
p.set('r_weh_cavity','1.5[mm]');
p.set('r_weh_out', '4[mm]');
p.set('r_weh_hole', sprintf('%.4f[mm]', rh));
p.set('gap2',      '12[mm]');
p.set('r_an_out',  '8[mm]');
p.set('r_an_hole', '1.5[mm]');
p.set('h_an',      '1[mm]');
p.set('drift',     '3[mm]');
p.set('r_domain',  '10[mm]');
p.set('z_margin',  '1[mm]');
p.set('chamfer_d', '0.1[mm]');
p.set('V_cathode', '0[V]');
p.set('V_wehnelt', sprintf('%.4f[V]', vw));
p.set('V_anode',   '70[V]');
p.set('z_weh_bot',  '-weh_skirt');
p.set('z_weh_ceil', 'h_cathode+weh_gap');
p.set('z_weh_top',  'z_weh_ceil+weh_wall');
p.set('z_an_bot',   'z_weh_top+gap2');
p.set('z_an_top',   'z_an_bot+h_an');
p.set('z_dom_bot',  'z_weh_bot-z_margin');
p.set('z_dom_top',  'z_an_top+drift');

comp1 = model.component.create('comp1', true);
geom1 = comp1.geom.create('geom1', 3);
geom1.lengthUnit('mm');

geom1.feature.create('hel1', 'Helix');
geom1.feature('hel1').set('rmaj', 'coil_rmaj');
geom1.feature('hel1').set('rmin', 'coil_rmin');
geom1.feature('hel1').set('axialpitch', 'coil_pitch');
geom1.feature('hel1').set('turns', 'coil_turns');
geom1.feature('hel1').set('pos', {'0' '0' '0'});

geom1.feature.create('cyl2', 'Cylinder');
geom1.feature('cyl2').set('r', 'r_weh_out'); geom1.feature('cyl2').set('h', 'z_weh_top-z_weh_bot');
geom1.feature('cyl2').set('pos', {'0' '0' 'z_weh_bot'});
geom1.feature.create('cyl2c', 'Cylinder');
geom1.feature('cyl2c').set('r', 'r_weh_cavity'); geom1.feature('cyl2c').set('h', '(z_weh_ceil-z_weh_bot)+0.2[mm]');
geom1.feature('cyl2c').set('pos', {'0' '0' 'z_weh_bot-0.2[mm]'});
geom1.feature.create('cyl3', 'Cylinder');
geom1.feature('cyl3').set('r', 'r_weh_hole'); geom1.feature('cyl3').set('h', '(z_weh_top-z_weh_ceil)+0.4[mm]');
geom1.feature('cyl3').set('pos', {'0' '0' 'z_weh_ceil-0.2[mm]'});
geom1.feature.create('dif1a', 'Difference');
geom1.feature('dif1a').selection('input').set({'cyl2'}); geom1.feature('dif1a').selection('input2').set({'cyl2c'});
geom1.feature.create('dif1', 'Difference');
geom1.feature('dif1').selection('input').set({'dif1a'}); geom1.feature('dif1').selection('input2').set({'cyl3'});

geom1.feature.create('cyl4', 'Cylinder');
geom1.feature('cyl4').set('r', 'r_an_out'); geom1.feature('cyl4').set('h', 'h_an');
geom1.feature('cyl4').set('pos', {'0' '0' 'z_an_bot'});
geom1.feature.create('cyl5', 'Cylinder');
geom1.feature('cyl5').set('r', 'r_an_hole'); geom1.feature('cyl5').set('h', 'h_an+0.4[mm]');
geom1.feature('cyl5').set('pos', {'0' '0' 'z_an_bot-0.2[mm]'});
geom1.feature.create('dif2', 'Difference');
geom1.feature('dif2').selection('input').set({'cyl4'}); geom1.feature('dif2').selection('input2').set({'cyl5'});

geom1.feature.create('cyl6', 'Cylinder');
geom1.feature('cyl6').set('r', 'r_domain'); geom1.feature('cyl6').set('h', 'z_dom_top-z_dom_bot');
geom1.feature('cyl6').set('pos', {'0' '0' 'z_dom_bot'});

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
geom1.feature('chdif2').selection('input').set({'dif1'}); geom1.feature('chdif2').selection('input2').set(tags.weh);
geom1.feature.create('chdif3', 'Difference');
geom1.feature('chdif3').selection('input').set({'dif2'}); geom1.feature('chdif3').selection('input2').set(tags.an);

geom1.feature('hel1').set('selresult', 'on');
geom1.feature('cyl6').set('selresult', 'on');
geom1.feature('chdif2').set('selresult', 'on');
geom1.feature('chdif3').set('selresult', 'on');
geom1.run;

sel_cath = 'geom1_hel1_dom'; sel_weh = 'geom1_chdif2_dom'; sel_an = 'geom1_chdif3_dom';
comp1.selection.create('sel_vac', 'Complement');
comp1.selection('sel_vac').set('input', {sel_cath, sel_weh, sel_an});
sel_vac = 'sel_vac';
vac_n = numel(comp1.selection(sel_vac).entities());
if vac_n ~= 1
    error('sel_vac resolved to %d domains (expected 1) for rh=%.2f vw=%.2f', vac_n, rh, vw);
end

comp1.selection.create('selb_cath', 'Adjacent'); comp1.selection('selb_cath').set('input', {sel_cath});
comp1.selection.create('selb_weh', 'Adjacent'); comp1.selection('selb_weh').set('input', {sel_weh});
comp1.selection.create('selb_an', 'Adjacent'); comp1.selection('selb_an').set('input', {sel_an});

mat_vac = model.material.create('mat_vac', 'Common'); mat_vac.selection.named(sel_vac);
mat_vac.propertyGroup('def').set('relpermittivity', {'1'});
mat_cath = model.material.create('mat_cath', 'Common'); mat_cath.selection.named(sel_cath);
mat_cath.propertyGroup('def').set('relpermittivity', {'1'});
mat_weh = model.material.create('mat_weh', 'Common'); mat_weh.selection.named(sel_weh);
mat_weh.propertyGroup('def').set('relpermittivity', {'1'});
mat_an = model.material.create('mat_an', 'Common'); mat_an.selection.named(sel_an);
mat_an.propertyGroup('def').set('relpermittivity', {'1'});

es = comp1.physics.create('es', 'Electrostatics', 'geom1'); es.selection.named(sel_vac);
pot_c = es.create('pot_cath', 'ElectricPotential', 2); pot_c.selection.named('selb_cath'); pot_c.set('V0', 'V_cathode');
pot_w = es.create('pot_weh', 'ElectricPotential', 2); pot_w.selection.named('selb_weh'); pot_w.set('V0', 'V_wehnelt');
pot_a = es.create('pot_an', 'ElectricPotential', 2); pot_a.selection.named('selb_an'); pot_a.set('V0', 'V_anode');

mesh1 = comp1.mesh.create('mesh1');
mesh1.feature('size').set('hauto', 3);
sz1 = mesh1.feature.create('sz1', 'Size');
sz1.selection.geom('geom1', 2); sz1.selection.named('selb_cath');
sz1.set('custom', 'on');
sz1.set('hmaxactive', true); sz1.set('hmax', '0.03[mm]');
sz1.set('hminactive', true); sz1.set('hmin', '0.005[mm]');
sz1.set('hgradactive', true); sz1.set('hgrad', 1.3);
mesh1.feature.create('ftet1', 'FreeTet');
mesh1.run;
mi = mphmeshstats(model, 'mesh1');
if mi.isempty || mi.hasproblems || ~mi.iscomplete
    error('Mesh failed for rh=%.2f vw=%.2f', rh, vw);
end

std1 = model.study.create('std1'); std1.create('stat1', 'Stationary');
model.sol.create('sol1'); model.sol('sol1').study('std1');
model.sol('sol1').createAutoSequence('std1'); model.sol('sol1').runAll;

%% CPT with thermal emission
cpt = comp1.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
cpt.selection.named(sel_vac);
inl1 = cpt.create('inl1', 'Inlet', 2);
inl1.selection.named('selb_cath');
inl1.set('N', 1);
inl1.set('VelocitySpecification', 'Thermal');
inl1.set('T_src', 'userdef');
inl1.set('T', '2700[K]');
ef1 = cpt.create('ef1', 'ElectricForce', 3);
ef1.selection.named(sel_vac);
ef1.set('E_src', 'root.comp1.es.Ex');

std2 = model.study.create('std2');
tstep = std2.create('time1', 'Transient');
tstep.set('tlist', 'range(0,0.1[ns],40[ns])');
tstep.setEntry('activate', 'es', false);
tstep.setEntry('activate', 'cpt', true);
model.sol.create('sol2'); model.sol('sol2').study('std2');
model.sol('sol2').createAutoSequence('std2');
model.sol('sol2').feature('v1').set('notsolmethod', 'sol');
model.sol('sol2').feature('v1').set('notsol', 'sol1');
model.sol('sol2').runAll;

pdset1 = model.result.dataset.create('pdset1', 'Particle');
pdset1.set('solution', 'sol2');

pd = mphparticle(model, 'dataset', 'pdset1');
me = 9.10938e-31; qe = 1.602176e-19;
n_released = size(pd.p, 2);
qx = pd.p(end,:,1); qy = pd.p(end,:,2); qz = pd.p(end,:,3);
vx = pd.v(end,:,1); vy = pd.v(end,:,2); vz = pd.v(end,:,3);
valid = ~isnan(qz);
speed = sqrt(vx.^2+vy.^2+vz.^2);
KE_eV = 0.5*me*speed.^2/qe;
n_arrived = sum(valid & KE_eV > 60 & KE_eV < 75);
n_selfabs = sum(~valid);

exit_mask = valid & qz > 15;
if any(exit_mask)
    beam_r = sqrt(std(qx(exit_mask))^2 + std(qy(exit_mask))^2);
else
    beam_r = NaN;
end

res.n_released = n_released;
res.n_arrived = n_arrived;
res.collect_pct = 100*n_arrived/n_released;
res.selfabs_pct = 100*n_selfabs/n_released;
res.beam_radius_mm = beam_r;

fprintf('n_released=%d n_arrived=%d collect=%.2f%% selfabs=%.2f%% beamR=%.4fmm\n', ...
    n_released, n_arrived, res.collect_pct, res.selfabs_pct, res.beam_radius_mm);

ModelUtil.remove('ModelSweep');
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
