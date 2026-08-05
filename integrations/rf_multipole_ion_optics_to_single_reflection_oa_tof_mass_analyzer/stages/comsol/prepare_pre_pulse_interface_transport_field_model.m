function [model, comp, context, geometryInfo, meshElementCounts] = ...
    prepare_pre_pulse_interface_transport_field_model( ...
    contract, resolvedConnection, sharedJoint, rf, oa, oaComsolDir, ...
    multipoleComsolDir, modelTag)
% Build, mesh and solve shared multipole PrePulse/PulseCapture field bases.

[model, context] = build_pre_pulse_interface_transport_model( ...
    resolvedConnection, sharedJoint, rf, oa, oaComsolDir, ...
    multipoleComsolDir, modelTag);
comp = model.component('comp1');
geometryInfo = mphgeominfo(model, 'geom1');
create_field_selections(comp, context, oa);
create_field_physics(model, comp, context, resolvedConnection, sharedJoint, oa);
create_field_mesh(comp, context, contract, oa);

study = model.study.create('std1');
study.create('stat', 'Stationary');
solution = model.sol.create('sol1');
solution.study('std1');
solution.createAutoSequence('std1');
solution.attach('std1');
solution.runAll;
meshInfo = mphmeshstats(model, 'mesh1');
meshElementCounts = meshInfo.numelem(:).';
end

function create_field_selections(comp, context, oa)
solidTags = [{'repeller','accelshield'}, context.rf_ground_tags, ...
    {context.rf_entrance_plate_tag}, ...
    {context.entrance_reference_sleeve_tag}, ...
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
if context.connector_present, create_connector_wall_selection(comp, context); end
end

function create_connector_wall_selection(comp, context)
xMin = context.source_center_mm(1);
xMax = context.target_center_mm(1);
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

function create_field_physics(model, comp, context, resolvedConnection, sharedJoint, oa)
material = model.material.create('mat_vac', 'Common');
material.selection.named('sel_vac');
material.propertyGroup('def').set('relpermittivity', {'1'});
esAxial = comp.physics.create('es_axial_dc', 'Electrostatics', 'geom1');
esAxial.selection.named('sel_vac');
esAxial.field('electricpotential').field('Vaxial');
esAxial.field('electricpotential').component({'Vaxial'});
esRf = comp.physics.create('es_rf', 'Electrostatics', 'geom1');
esRf.selection.named('sel_vac');
esRf.field('electricpotential').field('Vrf');
esRf.field('electricpotential').component({'Vrf'});
esOatof = comp.physics.create('es_oatof_pulse', 'Electrostatics', 'geom1');
esOatof.selection.named('sel_vac');
esOatof.field('electricpotential').field('Voatof');
esOatof.field('electricpotential').component({'Voatof'});

oatofTags = [{'repeller','accelshield'}, context.accelerator_ring_tags];
for index = 1:numel(oatofTags)
    name = oatofTags{index};
    set_potential(esAxial, ['g_' name], ['selb_' name], 0);
end
set_potential(esAxial, 'g_grid1', 'selb_grid1', 0);
set_potential(esAxial, 'g_grid2', 'selb_grid2', 0);
if context.connector_present
    set_potential(esAxial, 'connector', 'selb_connector_wall', 0);
end
for index = 1:numel(context.rf_ground_tags)
    name = context.rf_ground_tags{index};
    set_potential(esAxial, name, ['selb_' name], ...
        context.rf_upstream_hardware_potential_V);
end
set_potential(esAxial, 'entrance_plate', ...
    ['selb_' context.rf_entrance_plate_tag], ...
    context.rf_entrance_plate_potential_V);
set_potential(esAxial, 'source_reference_sleeve', ...
    ['selb_' context.entrance_reference_sleeve_tag], ...
    context.entrance_reference_sleeve_potential_V);
for index = 1:numel(context.rf_rod_tags)
    name = context.rf_rod_tags{index};
    set_potential(esAxial, name, ['selb_' name], ...
        context.rf_rod_common_mode_V(index));
end

groundedTags = [{'repeller','accelshield'}, context.rf_ground_tags, ...
    {context.rf_entrance_plate_tag}, ...
    {context.entrance_reference_sleeve_tag}, ...
    context.accelerator_ring_tags];
for index = 1:numel(groundedTags)
    name = groundedTags{index};
    set_potential(esRf, ['g_' name], ['selb_' name], 0);
end
set_potential(esRf, 'g_grid1', 'selb_grid1', 0);
set_potential(esRf, 'g_grid2', 'selb_grid2', 0);
if context.connector_present
    set_potential(esRf, 'g_connector', 'selb_connector_wall', 0);
end
unitPattern = sharedJoint.field_basis.rf_unit.rod_differential_pattern_V(:).';
assert(~isempty(unitPattern) && all(isfinite(unitPattern)) && ...
    all(abs(abs(unitPattern)-abs(unitPattern(1))) <= 1e-12,'all') && ...
    unitPattern(1) > 0, ...
    'The RF unit basis must freeze one finite symmetric differential magnitude.');
unitMagnitude = abs(unitPattern(1));
for index = 1:numel(context.rf_rod_tags)
    name = context.rf_rod_tags{index};
    electrodeGroup = context.rf_rod_electrode_groups(index);
    assert(ismember(electrodeGroup,[1 2]), ...
        'RF rod electrode_group must be 1 or 2.');
    differentialPotential = unitMagnitude*(3-2*electrodeGroup);
    set_potential(esRf, ['u_' name], ['selb_' name], ...
        differentialPotential);
end
if numel(unitPattern) == numel(context.rf_rod_tags)
    expectedPattern = unitMagnitude*(3-2*context.rf_rod_electrode_groups);
    assert(all(abs(unitPattern-expectedPattern) <= 1e-12,'all'), ...
        'Legacy per-rod RF unit pattern differs from resolved electrode groups.');
end

set_potential(esOatof, 'repeller', 'selb_repeller', oa.electrodes_V.repeller);
set_potential(esOatof, 'accelshield', 'selb_accelshield', 0);
set_potential(esOatof, 'grid1', 'selb_grid1', oa.electrodes_V.grid1);
set_potential(esOatof, 'grid2', 'selb_grid2', 0);
if context.connector_present
    set_potential(esOatof, 'connector', 'selb_connector_wall', 0);
end
for index = 1:numel(context.rf_ground_tags)
    name = context.rf_ground_tags{index};
    set_potential(esOatof, ['g_' name], ['selb_' name], 0);
end
set_potential(esOatof, 'g_entrance_plate', ...
    ['selb_' context.rf_entrance_plate_tag], 0);
set_potential(esOatof, 'g_source_reference_sleeve', ...
    ['selb_' context.entrance_reference_sleeve_tag], 0);
for index = 1:numel(context.rf_rod_tags)
    name = context.rf_rod_tags{index};
    set_potential(esOatof, ['g_' name], ['selb_' name], 0);
end
for index = 1:numel(context.accelerator_ring_tags)
    name = context.accelerator_ring_tags{index};
    set_potential(esOatof, sprintf('ring%d', index), ['selb_' name], ...
        oa.electrodes_V.grid1*(1-index/(numel(context.accelerator_ring_tags)+1)));
end
assert(abs(resolvedConnection.port_geometry.upstream.mating_surface.potential_V- ...
    resolvedConnection.port_geometry.downstream.mating_surface.potential_V) <= ...
    resolvedConnection.potential_alignment.tolerance_V, ...
    'Resolved continuous interface potentials differ.');
end

function create_field_mesh(comp, context, contract, oa)
meshContract = contract.field_runtime.mesh;
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
connectorMeshInputs = {'geom1_portvac_dom'};
if context.connector_present
    connectorMeshInputs = {'geom1_connvac_dom','geom1_portvac_dom'};
end
comp.selection('sel_connector_mesh').set('input', connectorMeshInputs);
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
    sprintf('%.17g[mm]', meshContract.interface_hmax_mm));
mesh.feature.create('ftet1', 'FreeTet');
mesh.run;
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
