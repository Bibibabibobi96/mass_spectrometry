function result = phase2_electrostatics_coil_transverse(resolvedContractPath)
% Phase 2 (transverse-coil variant): materials, voltage boundary
% conditions, electrostatics solve, potential/field result plots for the
% electron gun geometry with the filament coil's own axis PERPENDICULAR
% to the beam axis (see phase1_geometry_coil_transverse.m). Same
% Complement-selection / FreeTet-mesh fixes as phase2_electrostatics_coil.m
% documented in COMSOL_API.md under Geometry, Selections, and Mesh.
% The selected resolved mode determines whether the solver is executed.

componentRoot = fileparts(mfilename('fullpath'));
addpath(componentRoot);
paths = egun_paths();
if nargin < 1 || isempty(resolvedContractPath)
    error('A resolved Wehnelt contract path is required; no defaults exist.');
end
contract = load_wehnelt_contract(char(resolvedContractPath));
executionMode = contract.numerical.execution_mode;
import com.comsol.model.*
import com.comsol.model.util.*

modelPath = fullfile(paths.modelWorkspaceDir, 'ElectronGun_CoilT.mph');
savePath  = fullfile(paths.modelWorkspaceDir, 'ElectronGun_CoilT_ES.mph');
if any(strcmp(cell(ModelUtil.tags()), 'Model'))
    ModelUtil.remove('Model');
end
model = ModelUtil.load('Model', modelPath);
parameterBindingsVerified = apply_wehnelt_contract_parameters(model, contract);
comp1 = model.component('comp1');
geom1 = comp1.geom('geom1');

geom1.feature('hel1').set('selresult', 'on');
geom1.feature('cyl6').set('selresult', 'on');
geom1.feature('chdif2').set('selresult', 'on');
geom1.feature('chdif3').set('selresult', 'on');
geom1.run;

sel_cath = 'geom1_hel1_dom';
sel_weh  = 'geom1_chdif2_dom';
sel_an   = 'geom1_chdif3_dom';

comp1.selection.create('sel_vac', 'Complement');
comp1.selection('sel_vac').label('Vacuum (complement of electrodes)');
comp1.selection('sel_vac').set('input', {sel_cath, sel_weh, sel_an});
sel_vac = 'sel_vac';

vac_entities = comp1.selection(sel_vac).entities();
cath_entities = comp1.selection(sel_cath).entities();
fprintf('sel_vac resolves to %d domain(s): %s\n', numel(vac_entities), mat2str(vac_entities));
fprintf('sel_cath resolves to %d domain(s): %s\n', numel(cath_entities), mat2str(cath_entities));
if numel(vac_entities) ~= 1
    error('sel_vac resolved to %d domains, expected exactly 1 -- check selection setup before continuing.', numel(vac_entities));
end

comp1.selection.create('selb_cath', 'Adjacent');
comp1.selection('selb_cath').label('Cathode Coil Surface');
comp1.selection('selb_cath').set('input', {sel_cath});

comp1.selection.create('selb_weh', 'Adjacent');
comp1.selection('selb_weh').label('Wehnelt Surface');
comp1.selection('selb_weh').set('input', {sel_weh});

comp1.selection.create('selb_an', 'Adjacent');
comp1.selection('selb_an').label('Anode Surface');
comp1.selection('selb_an').set('input', {sel_an});

%% Materials
mat_vac = model.material.create('mat_vac', 'Common');
mat_vac.selection.named(sel_vac);
mat_vac.propertyGroup('def').set('relpermittivity', {'1'});
mat_cath = model.material.create('mat_cath', 'Common');
mat_cath.selection.named(sel_cath);
mat_cath.propertyGroup('def').set('relpermittivity', {'1'});
mat_weh = model.material.create('mat_weh', 'Common');
mat_weh.selection.named(sel_weh);
mat_weh.propertyGroup('def').set('relpermittivity', {'1'});
mat_an = model.material.create('mat_an', 'Common');
mat_an.selection.named(sel_an);
mat_an.propertyGroup('def').set('relpermittivity', {'1'});

%% Physics
es = comp1.physics.create('es', 'Electrostatics', 'geom1');
es.selection.named(sel_vac);
pot_c = es.create('pot_cath', 'ElectricPotential', 2);
pot_c.selection.named('selb_cath'); pot_c.set('V0', 'V_cathode');
pot_w = es.create('pot_weh', 'ElectricPotential', 2);
pot_w.selection.named('selb_weh'); pot_w.set('V0', 'V_wehnelt');
pot_a = es.create('pot_an', 'ElectricPotential', 2);
pot_a.selection.named('selb_an'); pot_a.set('V0', 'V_anode');

%% Mesh (same recipe as phase2_electrostatics_coil.m: global Finer +
% explicit local size on the coil surface + explicit FreeTet + health check)
mesh1 = comp1.mesh.create('mesh1');
mesh1.feature('size').set('hauto', contract.numerical.mesh.automatic_level);
sz1 = mesh1.feature.create('sz1', 'Size');
sz1.selection.geom('geom1', 2);
sz1.selection.named('selb_cath');
sz1.set('custom', 'on');
sz1.set('hmaxactive', true); sz1.set('hmax', 'mesh_coil_hmax');
sz1.set('hminactive', true); sz1.set('hmin', 'mesh_coil_hmin');
sz1.set('hgradactive', true); sz1.set('hgrad', 'mesh_hgrad');
mesh1.feature.create('ftet1', 'FreeTet');
mesh1.run;
meshinfo = mphmeshstats(model, 'mesh1');
if meshinfo.isempty || meshinfo.hasproblems || ~meshinfo.iscomplete
    error('Mesh build failed (isempty=%d hasproblems=%d iscomplete=%d)', ...
        meshinfo.isempty, meshinfo.hasproblems, meshinfo.iscomplete);
end
fprintf('Mesh OK: isempty=%d hasproblems=%d iscomplete=%d\n', ...
    meshinfo.isempty, meshinfo.hasproblems, meshinfo.iscomplete);

%% Study + solve
std1 = model.study.create('std1');
std1.create('stat1', 'Stationary');
model.sol.create('sol1');
model.sol('sol1').study('std1');
model.sol('sol1').createAutoSequence('std1');
if strcmp(executionMode, 'build_only')
    model.save(savePath);
    result = struct('status', 'PASS', 'execution_mode', executionMode, ...
        'model_path', savePath, 'geometry_built', true, 'mesh_built', true, ...
        'electrostatics_solved', false, 'contract_loaded', true, ...
        'contract_project_id', contract.project_id, ...
        'selected_mode_id', contract.selected_mode_id, ...
        'parameter_bindings_verified', parameterBindingsVerified, ...
        'candidate_evidence_allowed', ...
        contract.evidence.candidate_evidence_allowed);
    fprintf('BUILD_ONLY=PASS model=%s\n', savePath);
    return;
end
model.sol('sol1').runAll;
fprintf('SUCCESS: Electrostatics solved.\n');

%% Result plots
pg1 = model.result.create('pg_V', 'PlotGroup3D');
sl1 = pg1.create('slice1', 'Slice');
sl1.set('quickplane', 'zx'); sl1.set('quickznumber', '1'); sl1.set('quickxnumber', '1'); sl1.set('quickynumber', '1');
sl1.set('expr', 'V');
pg2 = model.result.create('pg_E', 'PlotGroup3D');
sl2 = pg2.create('slice2', 'Slice');
sl2.set('quickplane', 'zx'); sl2.set('quickznumber', '1'); sl2.set('quickxnumber', '1'); sl2.set('quickynumber', '1');
sl2.set('expr', 'es.normE');

resultsDir = paths.resultsDir;
if ~exist(resultsDir, 'dir'), mkdir(resultsDir); end
imgV = model.result.export.create('imgV', 'Image');
imgV.set('plotgroup', 'pg_V'); imgV.set('pngfilename', fullfile(resultsDir, 'potential_distribution_coilT.png'));
imgV.set('width', contract.numerical.reporting.field_image_width_px);
imgV.set('height', contract.numerical.reporting.field_image_height_px);
imgV.run;
imgE = model.result.export.create('imgE', 'Image');
imgE.set('plotgroup', 'pg_E'); imgE.set('pngfilename', fullfile(resultsDir, 'efield_distribution_coilT.png'));
imgE.set('width', contract.numerical.reporting.field_image_width_px);
imgE.set('height', contract.numerical.reporting.field_image_height_px);
imgE.run;
fprintf('SUCCESS: Result images exported.\n');

%% Resolver-defined on-axis diagnostic points avoid the filament solid
zvals = contract.numerical.reporting.electrostatic_axis_samples_z_mm(:).';
coords = [zeros(1,numel(zvals)); zeros(1,numel(zvals)); zvals];
Vq = mphinterp(model, 'V', 'coord', coords, 'dataset', 'dset1', 'matherr', 'off');
Eq = mphinterp(model, 'es.normE', 'coord', coords, 'dataset', 'dset1', 'matherr', 'off');
fprintf('\nOn-axis (x=y=0) potential / field along beam path:\n');
fprintf('%10s %12s %14s\n', 'z [mm]', 'V [V]', '|E| [V/m]');
for i = 1:numel(zvals)
    fprintf('%10.2f %12.4f %14.3e\n', zvals(i), Vq(i), Eq(i));
end

model.save(savePath);
fprintf('\nSUCCESS: model saved to %s\n', savePath);
result = struct('status', 'PASS', 'execution_mode', executionMode, ...
    'model_path', savePath, 'geometry_built', true, 'mesh_built', true, ...
    'electrostatics_solved', true, 'contract_loaded', true, ...
    'contract_project_id', contract.project_id, ...
    'selected_mode_id', contract.selected_mode_id, ...
    'parameter_bindings_verified', parameterBindingsVerified, ...
    'candidate_evidence_allowed', ...
    contract.evidence.candidate_evidence_allowed);
end
