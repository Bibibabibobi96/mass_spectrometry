% Solve the two no-pulse S2 field bases on the shared passive-connector geometry.

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
metricsPath = getenv('RF_OATOF_S2_FIELD_METRICS');
samplesPath = getenv('RF_OATOF_S2_FIELD_SAMPLES');
contractPath = getenv('RF_OATOF_S2_CONTRACT');
s1ContractPath = getenv('RF_OATOF_S2_S1_CONTRACT');
rfResolvedPath = getenv('RF_OATOF_S2_RF_RESOLVED');
oaBaselinePath = getenv('RF_OATOF_S2_OA_BASELINE');
oaComsolDir = getenv('RF_OATOF_S2_OA_COMSOL_DIR');
assert(~isempty(reportPath) && ~isempty(metricsPath) && ~isempty(samplesPath), ...
    'S2 field output paths are incomplete.');
assert(isfile(contractPath) && isfile(s1ContractPath) && ...
    isfile(rfResolvedPath) && isfile(oaBaselinePath), ...
    'S2 field contract inputs are incomplete.');
assert(isfolder(oaComsolDir), 'The oaTOF COMSOL source directory is missing.');

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not create the S2 field task report.');
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, 'TASK=S2_PASSIVE_CONNECTOR_NO_PULSE_FIELD\n');

try
    contract = jsondecode(fileread(contractPath));
    s1 = jsondecode(fileread(s1ContractPath));
    rf = jsondecode(fileread(rfResolvedPath));
    oa = jsondecode(fileread(oaBaselinePath));
    assert(contract.permissions.field_solve_allowed, ...
        'The S2 contract does not authorize a field solve.');
    assert(~contract.permissions.particle_runtime_allowed, ...
        'The no-pulse S2 field task requires particle runtime to remain disabled.');
    assert(~contract.field_ownership.oa_extraction_pulse_included, ...
        'The no-pulse S2 field task cannot include an oa extraction pulse.');

    import com.comsol.model.util.*
    tag = 'RFOATOF_S2_FIELD';
    [model, context] = build_s2_passive_connector_model( ...
        contract, s1, rf, oa, oaComsolDir, tag);
    comp = model.component('comp1');
    geometryInfo = mphgeominfo(model, 'geom1');
    create_field_selections(comp, context, oa, contract);
    create_field_physics(model, comp, context, s1, oa);
    create_field_mesh(comp, contract, oa);

    study = model.study.create('std1');
    study.create('stat', 'Stationary');
    solution = model.sol.create('sol1');
    solution.study('std1');
    solution.createAutoSequence('std1');
    solution.attach('std1');
    solution.runAll;

    [probeNames, coordinates] = field_probe_coordinates(contract, rf, oa);
    expressions = {'-d(V,x)','-d(V,y)','-d(V,z)','V', ...
        '-d(Vrf,x)','-d(Vrf,y)','-d(Vrf,z)','Vrf'};
    values = cell(1, numel(expressions));
    [values{:}] = mphinterp(model, expressions, 'coord', coordinates.', ...
        'dataset', 'dset1', 'matherr', 'on');
    matrix = zeros(size(coordinates,1), numel(expressions));
    for index = 1:numel(values), matrix(:,index) = values{index}(:); end
    assert(all(isfinite(matrix), 'all'), 'S2 field probes contain nonfinite values.');
    rfOffAxisFieldNorm = norm(matrix(1,5:7));
    assert(rfOffAxisFieldNorm > 0, 'The RF off-axis probe did not resolve the RF-unit field.');

    samples = table(probeNames(:), coordinates(:,1), coordinates(:,2), coordinates(:,3), ...
        matrix(:,1), matrix(:,2), matrix(:,3), matrix(:,4), ...
        matrix(:,5), matrix(:,6), matrix(:,7), matrix(:,8), ...
        'VariableNames', {'probe','x_mm','y_mm','z_mm', ...
        'static_Ex_V_per_m','static_Ey_V_per_m','static_Ez_V_per_m','static_potential_V', ...
        'rf_Ex_V_per_m','rf_Ey_V_per_m','rf_Ez_V_per_m','rf_potential_V'});
    outputDir = fileparts(samplesPath);
    if ~isfolder(outputDir), mkdir(outputDir); end
    writetable(samples, samplesPath);

    meshInfo = mphmeshstats(model, 'mesh1');
    meshElementCounts = meshInfo.numelem(:).';
    meshElementTotal = sum(meshElementCounts);
    metrics = struct( ...
        'schema_version', 1, ...
        'role', 'rf_to_oatof_s2_no_pulse_field_metrics', ...
        'status', 'SOLVED', ...
        'gap_mm', context.gap_mm, ...
        'geometry_domains', geometryInfo.Ndomains, ...
        'mesh_element_counts_by_type', meshElementCounts, ...
        'mesh_elements_total', meshElementTotal, ...
        'field_bases_solved', {{'oatof_static','rf_unit_100_V'}}, ...
        'probe_count', height(samples), ...
        'all_probe_values_finite', true, ...
        'rf_off_axis_field_norm_V_per_m', rfOffAxisFieldNorm, ...
        'particle_runtime_executed', false, ...
        'oa_extraction_pulse_included', false, ...
        'model_saved', false, ...
        'mesh_convergence_claimed', false, ...
        's2_stage_passed', false, ...
        'formal_gate_passed', false, ...
        'claim_limit', contract.no_pulse_field_candidate.claim_limit);
    metricsFid = fopen(metricsPath, 'w');
    assert(metricsFid >= 0, 'Could not create S2 field metrics.');
    fprintf(metricsFid, '%s', jsonencode(metrics, 'PrettyPrint', true));
    fclose(metricsFid);
    fprintf(fid, ['GAP_MM=%.17g\nGEOMETRY_DOMAINS=%d\nMESH_ELEMENTS=%d\n' ...
        'FIELD_BASES=2\nPROBE_ROWS=%d\nFINITE_PROBES=true\nPARTICLE_RUNTIME=false\n' ...
        'OA_PULSE=false\nMODEL_SAVED=false\nSTATUS=PASS\n'], ...
        context.gap_mm, geometryInfo.Ndomains, meshElementTotal, height(samples));
    ModelUtil.remove(tag);
catch exception
    fprintf(fid, 'STATUS=FAIL\nERROR=%s\n', ...
        getReport(exception, 'extended', 'hyperlinks', 'off'));
    rethrow(exception)
end
clear cleanup

function create_field_selections(comp, context, oa, contract)
solidTags = [{'repeller','accelshield'}, context.rf_ground_tags, ...
    context.accelerator_ring_tags, context.rf_rod_tags];
solidSelections = cellfun(@(name) ['geom1_' name '_dom'], ...
    solidTags, 'UniformOutput', false);
comp.selection.create('sel_vac', 'Complement');
comp.selection('sel_vac').set('input', solidSelections);
for index = 1:numel(solidTags)
    name = solidTags{index};
    comp.selection.create(['selb_' name], 'Adjacent');
    comp.selection(['selb_' name]).set('input', {['geom1_' name '_dom']});
end
create_grid_selection(comp, 'selb_grid1', oa.geometry_mm.accelerator_grid1_z, ...
    oa.coordinate_convention.accelerator_axis_x, ...
    oa.geometry_mm.accelerator_bore_half+oa.geometry_mm.accelerator_ring_width, 0.2);
create_grid_selection(comp, 'selb_grid2', oa.geometry_mm.accelerator_grid2_z, ...
    oa.coordinate_convention.accelerator_axis_x, ...
    oa.geometry_mm.accelerator_bore_half+oa.geometry_mm.accelerator_ring_width+ ...
    oa.geometry_mm.accelerator_insulation_gap, 0.05);
create_connector_wall_selection(comp, contract);
end

function create_connector_wall_selection(comp, contract)
xMin = contract.passive_connector_geometry.axial_extent_x_mm(1);
xMax = contract.passive_connector_geometry.axial_extent_x_mm(2);
tolerance = 1e-6;
comp.selection.create('selb_conn_all', 'Adjacent');
comp.selection('selb_conn_all').set('input', {'geom1_connvac_dom'});
for item = {{'selb_conn_up', xMin}, {'selb_conn_down', xMax}}
    spec = item{1};
    comp.selection.create(spec{1}, 'Box');
    comp.selection(spec{1}).geom('geom1', 2);
    comp.selection(spec{1}).set('xmin', spec{2}-tolerance);
    comp.selection(spec{1}).set('xmax', spec{2}+tolerance);
    comp.selection(spec{1}).set('condition', 'inside');
end
comp.selection.create('selb_conn_ends', 'Union');
comp.selection('selb_conn_ends').geom('geom1', 2);
comp.selection('selb_conn_ends').set('input', {'selb_conn_up','selb_conn_down'});
comp.selection.create('selb_connector_wall', 'Difference');
comp.selection('selb_connector_wall').geom('geom1', 2);
comp.selection('selb_connector_wall').set('add', {'selb_conn_all'});
comp.selection('selb_connector_wall').set('subtract', {'selb_conn_ends'});
end

function create_field_physics(model, comp, context, s1, oa)
material = model.material.create('mat_vac', 'Common');
material.selection.named('sel_vac');
material.propertyGroup('def').set('relpermittivity', {'1'});
esStatic = comp.physics.create('es_static', 'Electrostatics', 'geom1');
esStatic.selection.named('sel_vac');
esStatic.field('electricpotential').field('V');
esStatic.field('electricpotential').component({'V'});
esRf = comp.physics.create('es_rf', 'Electrostatics', 'geom1');
esRf.selection.named('sel_vac');
esRf.field('electricpotential').field('Vrf');
esRf.field('electricpotential').component({'Vrf'});

set_potential(esStatic, 'repeller', 'selb_repeller', oa.electrodes_V.repeller);
set_potential(esStatic, 'accelshield', 'selb_accelshield', 0);
set_potential(esStatic, 'grid1', 'selb_grid1', oa.electrodes_V.grid1);
set_potential(esStatic, 'grid2', 'selb_grid2', 0);
set_potential(esStatic, 'connector', 'selb_connector_wall', 0);
for index = 1:numel(context.rf_ground_tags)
    name = context.rf_ground_tags{index};
    set_potential(esStatic, name, ['selb_' name], 0);
end
for index = 1:numel(context.rf_rod_tags)
    name = context.rf_rod_tags{index};
    set_potential(esStatic, name, ['selb_' name], 0);
end
for index = 1:numel(context.accelerator_ring_tags)
    name = context.accelerator_ring_tags{index};
    set_potential(esStatic, sprintf('ring%d', index), ['selb_' name], ...
        oa.electrodes_V.grid1*(1-index/(numel(context.accelerator_ring_tags)+1)));
end

groundedTags = [{'repeller','accelshield'}, context.rf_ground_tags, ...
    context.accelerator_ring_tags];
for index = 1:numel(groundedTags)
    name = groundedTags{index};
    set_potential(esRf, ['g_' name], ['selb_' name], 0);
end
set_potential(esRf, 'g_grid1', 'selb_grid1', 0);
set_potential(esRf, 'g_grid2', 'selb_grid2', 0);
set_potential(esRf, 'g_connector', 'selb_connector_wall', 0);
for index = 1:numel(context.rf_rod_tags)
    name = context.rf_rod_tags{index};
    set_potential(esRf, ['u_' name], ['selb_' name], ...
        s1.field_basis.rf_unit.rod_differential_pattern_V(index));
end
end

function create_field_mesh(comp, contract, oa)
meshContract = contract.no_pulse_field_candidate.mesh;
g = oa.geometry_mm;
mesh = comp.mesh.create('mesh1');
mesh.feature('size').set('hauto', meshContract.global_auto_level);
comp.selection.create('sel_accel_mesh', 'Box');
comp.selection('sel_accel_mesh').geom('geom1', 3);
halfWidth = g.accelerator_bore_half+g.accelerator_ring_width+g.accelerator_insulation_gap;
comp.selection('sel_accel_mesh').set('xmin', oa.coordinate_convention.accelerator_axis_x-halfWidth);
comp.selection('sel_accel_mesh').set('xmax', oa.coordinate_convention.accelerator_axis_x+halfWidth);
comp.selection('sel_accel_mesh').set('ymin', -halfWidth);
comp.selection('sel_accel_mesh').set('ymax', halfWidth);
comp.selection('sel_accel_mesh').set('zmin', g.accelerator_repeller_z);
comp.selection('sel_accel_mesh').set('zmax', g.accelerator_grid2_z);
comp.selection('sel_accel_mesh').set('condition', 'inside');
comp.selection.create('sel_connector_mesh', 'Union');
comp.selection('sel_connector_mesh').set('input', ...
    {'geom1_connvac_dom','geom1_portvac_dom'});
mesh.feature.create('szaccel', 'Size');
mesh.feature('szaccel').selection.geom('geom1', 3);
mesh.feature('szaccel').selection.named('sel_accel_mesh');
mesh.feature('szaccel').set('custom', 'on');
mesh.feature('szaccel').set('hmaxactive', true);
mesh.feature('szaccel').set('hmax', sprintf('%.17g[mm]', meshContract.accelerator_hmax_mm));
mesh.feature.create('szconnector', 'Size');
mesh.feature('szconnector').selection.geom('geom1', 3);
mesh.feature('szconnector').selection.named('sel_connector_mesh');
mesh.feature('szconnector').set('custom', 'on');
mesh.feature('szconnector').set('hmaxactive', true);
mesh.feature('szconnector').set('hmax', ...
    sprintf('%.17g[mm]', meshContract.connector_and_port_hmax_mm));
mesh.feature.create('ftet1', 'FreeTet');
mesh.run;
end

function [names, coordinates] = field_probe_coordinates(contract, rf, oa)
source = contract.nominal_registration.source_exit_center_instrument_mm(:).';
target = contract.nominal_registration.target_entry_center_instrument_mm(:).';
offset = contract.no_pulse_field_candidate.boundary_probe_inset_mm;
pose = contract.nominal_registration.source_component_pose;
rotation = pose.rotation_component_to_instrument;
localProbe = [contract.no_pulse_field_candidate.rf_off_axis_probe_radius_mm; 0; ...
    (rf.geometry_mm.rod_z_min+rf.geometry_mm.rod_z_max)/2];
rfOffAxis = (rotation*localProbe + pose.translation_mm(:)).';
names = ["rf_rod_region_off_axis";"rf_exit_center";"connector_midpoint"; ...
    "oatof_entry_center";"oatof_ideal_source_center"];
coordinates = [rfOffAxis; source+[offset,0,0]; (source+target)/2; target+[offset,0,0]; ...
    [oa.particle_source.center_x_mm, oa.particle_source.center_y_mm, oa.particle_source.center_z_mm]];
end

function create_grid_selection(comp, tag, zValue, xCenter, halfWidth, zHalf)
comp.selection.create(tag, 'Box');
comp.selection(tag).geom('geom1', 2);
comp.selection(tag).set('xmin', xCenter-halfWidth);
comp.selection(tag).set('xmax', xCenter+halfWidth);
comp.selection(tag).set('ymin', -halfWidth);
comp.selection(tag).set('ymax', halfWidth);
comp.selection(tag).set('zmin', zValue-zHalf);
comp.selection(tag).set('zmax', zValue+zHalf);
comp.selection(tag).set('condition', 'inside');
end

function set_potential(physics, tag, selection, value)
feature = physics.create(['pot_' tag], 'ElectricPotential', 2);
feature.selection.named(selection);
feature.set('V0', value);
end
