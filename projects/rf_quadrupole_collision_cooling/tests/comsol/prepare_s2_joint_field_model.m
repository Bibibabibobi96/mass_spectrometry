function [model, comp, context, geometryInfo, meshElementCounts] = ...
    prepare_s2_joint_field_model(contract, s1, rf, oa, oaComsolDir, modelTag)
% Build, mesh and solve the shared S2/S3 electrostatic field bases.

[model, context] = build_s2_passive_connector_model( ...
    contract, s1, rf, oa, oaComsolDir, modelTag);
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
meshInfo = mphmeshstats(model, 'mesh1');
meshElementCounts = meshInfo.numelem(:).';
end

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
if context.connector_present, create_connector_wall_selection(comp, contract); end
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
if context.connector_present, set_potential(esStatic, 'connector', 'selb_connector_wall', 0); end
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
if context.connector_present, set_potential(esRf, 'g_connector', 'selb_connector_wall', 0); end
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
connectorMeshInputs = {'geom1_portvac_dom'};
if contract.nominal_registration.connector_gap_mm > 0
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
    sprintf('%.17g[mm]', meshContract.connector_and_port_hmax_mm));
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
