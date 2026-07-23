function [model, context] = build_s2_passive_connector_model(contract, sharedJoint, rf, oa, oaComsolDir, modelTag)
% Build the shared S2 passive-connector geometry and return its selections.
% REPOSITORY_CONTRACT: MATLAB_BUILD_ONLY

arguments
    contract struct
    sharedJoint struct
    rf struct
    oa struct
    oaComsolDir (1,:) char
    modelTag (1,:) char
end

spatialRegistrationPath = getenv('RF_OATOF_SPATIAL_REGISTRATION');
assert(isfile(spatialRegistrationPath), ...
    'S2 requires a frozen authoritative spatial-registration release.');
spatial = jsondecode(fileread(spatialRegistrationPath));
registration = contract.nominal_registration;
connector = contract.passive_connector_geometry;
assert_supported_registration(registration, spatial);
sourceCenter = spatial.resolved_surfaces.source_exit.in_instrument_frame.center_mm(:).';
targetCenter = spatial.resolved_surfaces.target_entry.in_instrument_frame.center_mm(:).';
gapMm = spatial.project_semantics.connector_gap_mm;
assert(gapMm >= 0, 'Connector gap cannot be negative.');
connectorPresent = gapMm > 0;
assert(abs(targetCenter(1)-sourceCenter(1)-gapMm) < 1e-12, ...
    'Connector endpoints do not reproduce the frozen S2 gap.');
assert(abs(connector.length_mm-gapMm) < 1e-12, ...
    'Connector geometry length differs from the registration gap.');

import com.comsol.model.*
import com.comsol.model.util.*
if any(strcmp(cell(ModelUtil.tags()), modelTag)), ModelUtil.remove(modelTag); end
model = ModelUtil.create(modelTag);
model.label(sprintf('RF to oaTOF S2 passive connector, gap %.6g mm', gapMm));
comp = model.component.create('comp1', true);
geom = comp.geom.create('geom1', 3);
geom.lengthUnit('mm');
configure_accelerator_parameters(model.param, oa);

sourcePose = registration.source_component_pose;
tx = sourcePose.translation_mm(1);
tz = sourcePose.translation_mm(3);
rfGeometry = rf.geometry_mm;
shieldInnerRadius = sharedJoint.local_domain.rf_shield_inner_radius_mm;
numericalWallMm = sharedJoint.local_domain.rf_shield_numerical_wall_thickness_mm;
downstreamBufferMm = sharedJoint.local_domain.oatof_downstream_buffer_after_grid2_mm;
oaGeometry = oa.geometry_mm;
oaVacuumHalf = oaGeometry.accelerator_bore_half + ...
    oaGeometry.accelerator_ring_width + oaGeometry.accelerator_insulation_gap;

add_cylinder(geom, 'rfvac', shieldInnerRadius, ...
    registration.source_exit_center_local_mm(3), [tx, 0.0, tz], true);
if connectorPresent
    add_cylinder(geom, 'connvac', connector.cavity.inner_radius_mm, gapMm, sourceCenter, true);
end
add_oatof_vacuum(geom, oa, oaVacuumHalf, downstreamBufferMm);
add_oatof_port(geom, connector, oa, oaVacuumHalf);
add_grid_surfaces(geom, oa);
geom.feature.create('univacgrid', 'Union');
vacuumInputs = {'rfvac','oavac','portvac','wp_grid1','wp_grid2'};
if connectorPresent, vacuumInputs = [vacuumInputs(1), {'connvac'}, vacuumInputs(2:end)]; end
geom.feature('univacgrid').selection('input').set(vacuumInputs);
geom.feature('univacgrid').set('intbnd', true);
geom.feature('univacgrid').set('selresult', 'on');

addpath(oaComsolDir);
downstream = connector.downstream_entry_aperture;
interfacePort = struct('enabled', true, ...
    'full_width_y_mm', downstream.full_width_y_mm, ...
    'full_height_z_mm', downstream.full_height_z_mm, ...
    'center_z_mm', downstream.center_mm(3));
acceleratorRingTags = oatof_build_accelerator_geometry( ...
    geom, oa.rings.accelerator_count, interfacePort);
geom.feature('repeller').set('selresult', 'on');
geom.feature('accelshield').set('selresult', 'on');
for index = 1:numel(acceleratorRingTags)
    geom.feature(acceleratorRingTags{index}).set('selresult', 'on');
end
add_rf_hardware(geom, rfGeometry, rf.interfaces_mm, tx, tz, ...
    shieldInnerRadius, numericalWallMm);
geom.run;

if connectorPresent
    connectorDomains = comp.selection('geom1_connvac_dom').entities(3);
else
    connectorDomains = [];
end
portDomains = comp.selection('geom1_portvac_dom').entities(3);
rfVacuumDomains = comp.selection('geom1_rfvac_dom').entities(3);
oaVacuumDomains = comp.selection('geom1_oavac_dom').entities(3);
assert(~isempty(portDomains), 'The oaTOF port vacuum selection is empty after geometry build.');
assert(~connectorPresent || ~isempty(connectorDomains), ...
    'The finite connector vacuum selection is empty after geometry build.');
assert(~isempty(rfVacuumDomains) && ~isempty(oaVacuumDomains), ...
    'Upstream or downstream vacuum selection is empty after geometry build.');

context = struct( ...
    'gap_mm', gapMm, ...
    'connector_present', connectorPresent, ...
    'source_center_mm', sourceCenter, ...
    'target_center_mm', targetCenter, ...
    'connector_inner_radius_mm', connector.cavity.inner_radius_mm, ...
    'port_full_width_y_mm', downstream.full_width_y_mm, ...
    'port_full_height_z_mm', downstream.full_height_z_mm, ...
    'rf_shield_inner_radius_mm', shieldInnerRadius, ...
    'oatof_downstream_buffer_mm', downstreamBufferMm, ...
    'connector_domain_count', numel(connectorDomains), ...
    'port_domain_count', numel(portDomains), ...
    'rf_vacuum_domain_count', numel(rfVacuumDomains), ...
    'oatof_vacuum_domain_count', numel(oaVacuumDomains), ...
    'accelerator_ring_tags', {acceleratorRingTags}, ...
    'rf_ground_tags', {{'rfshield','rfentrance','rfexit'}}, ...
    'rf_rod_tags', {{'rfrod1','rfrod2','rfrod3','rfrod4'}});
end

function assert_supported_registration(registration, spatial)
assert(strcmp(spatial.role,'resolved_spatial_registration_do_not_edit') && ...
    strcmp(spatial.project_semantics.stage,'S2'), ...
    'S2 requires the authoritative S2 spatial registration.');
sourcePose = spatial.component_poses.rf_quadrupole_component;
targetPose = spatial.component_poses.oatof_global;
assert(isequal(registration.source_component_pose.rotation_component_to_instrument,sourcePose.rotation) && ...
    isequal(registration.source_component_pose.translation_mm,sourcePose.translation_mm) && ...
    isequal(registration.target_component_pose.rotation_component_to_instrument,targetPose.rotation) && ...
    isequal(registration.target_component_pose.translation_mm,targetPose.translation_mm), ...
    'S2 project inputs are stale relative to resolved spatial registration.');
sourceCenter = spatial.resolved_surfaces.source_exit.in_instrument_frame.center_mm;
targetCenter = spatial.resolved_surfaces.target_entry.in_instrument_frame.center_mm;
gapMm = spatial.project_semantics.connector_gap_mm;
assert(all(abs(sourceCenter-registration.source_exit_center_instrument_mm) <= 1e-12) && ...
    all(abs(targetCenter-registration.target_entry_center_instrument_mm) <= 1e-12) && ...
    abs(targetCenter(1)-sourceCenter(1)-gapMm) <= 1e-12 && ...
    all(abs(targetCenter(2:3)-sourceCenter(2:3)) <= 1e-12), ...
    'S2 resolved connector centers or gap are inconsistent.');
end

function configure_accelerator_parameters(parameters, oa)
g = oa.geometry_mm;
parameters.set('x_accel_center', sprintf('%.17g[mm]', oa.coordinate_convention.accelerator_axis_x));
parameters.set('z_accel_origin', sprintf('%.17g[mm]', g.accelerator_repeller_z));
parameters.set('L_accel', sprintf('%.17g[mm]', g.L_accel));
parameters.set('z_accel_grid1', sprintf('%.17g[mm]', g.accelerator_grid1_z));
parameters.set('z_accel_grid2', sprintf('%.17g[mm]', g.accelerator_grid2_z));
parameters.set('accel_ring_bore_half', sprintf('%.17g[mm]', g.accelerator_bore_half));
parameters.set('accel_shield_half', sprintf('%.17g[mm]', ...
    g.accelerator_bore_half+g.accelerator_ring_width+g.accelerator_insulation_gap));
parameters.set('accel_ring_gap', sprintf('%.17g[mm]', g.accelerator_insulation_gap));
parameters.set('accel_shield_wall', sprintf('%.17g[mm]', g.accelerator_shield_wall));
parameters.set('accel_repeller_thickness', sprintf('%.17g[mm]', g.accelerator_repeller_thickness));
parameters.set('accel_ring_thickness', sprintf('%.17g[mm]', g.accelerator_ring_thickness));
parameters.set('accel_shield_back_extra', sprintf('%.17g[mm]', g.accelerator_rear_clearance));
parameters.set('V_grid1', sprintf('%.17g[V]', oa.electrodes_V.grid1));
end

function add_cylinder(geom, tag, radiusMm, lengthMm, positionMm, selectionEnabled)
geom.feature.create(tag, 'Cylinder');
geom.feature(tag).set('axis', {'1','0','0'});
geom.feature(tag).set('r', sprintf('%.17g[mm]', radiusMm));
geom.feature(tag).set('h', sprintf('%.17g[mm]', lengthMm));
geom.feature(tag).set('pos', cellstr(compose('%.17g[mm]', positionMm)));
if selectionEnabled, geom.feature(tag).set('selresult', 'on'); end
end

function add_oatof_vacuum(geom, oa, halfWidthMm, downstreamBufferMm)
g = oa.geometry_mm;
zMin = g.accelerator_repeller_z-g.accelerator_repeller_thickness-g.accelerator_rear_clearance;
zMax = g.accelerator_grid2_z+downstreamBufferMm;
geom.feature.create('oavac', 'Block');
geom.feature('oavac').set('size', cellstr(compose('%.17g[mm]', ...
    [2*halfWidthMm, 2*halfWidthMm, zMax-zMin])));
geom.feature('oavac').set('pos', cellstr(compose('%.17g[mm]', ...
    [oa.coordinate_convention.accelerator_axis_x-halfWidthMm, -halfWidthMm, zMin])));
geom.feature('oavac').set('selresult', 'on');
end

function add_oatof_port(geom, connector, oa, vacuumHalfMm)
g = oa.geometry_mm;
port = connector.downstream_entry_aperture;
outerX = oa.coordinate_convention.accelerator_axis_x-(vacuumHalfMm+g.accelerator_shield_wall);
innerX = oa.coordinate_convention.accelerator_axis_x-vacuumHalfMm;
geom.feature.create('portvac', 'Block');
geom.feature('portvac').set('size', cellstr(compose('%.17g[mm]', ...
    [innerX-outerX, port.full_width_y_mm, port.full_height_z_mm])));
geom.feature('portvac').set('pos', cellstr(compose('%.17g[mm]', ...
    [outerX, -port.full_width_y_mm/2, port.center_mm(3)-port.full_height_z_mm/2])));
geom.feature('portvac').set('selresult', 'on');
end

function add_grid_surfaces(geom, oa)
g = oa.geometry_mm;
specifications = {{'wp_grid1', g.accelerator_grid1_z, ...
    2*(g.accelerator_bore_half+g.accelerator_ring_width)}, ...
    {'wp_grid2', g.accelerator_grid2_z, ...
    2*(g.accelerator_bore_half+g.accelerator_ring_width+g.accelerator_insulation_gap)}};
for specification = specifications
    item = specification{1};
    workPlane = geom.feature.create(item{1}, 'WorkPlane');
    workPlane.set('quickplane', 'xy');
    workPlane.set('quickz', sprintf('%.17g[mm]', item{2}));
    workPlane.geom.feature.create('r1', 'Rectangle');
    workPlane.geom.feature('r1').set('size', cellstr(compose('%.17g[mm]', [item{3}, item{3}])));
    workPlane.geom.feature('r1').set('pos', cellstr(compose('%.17g[mm]', ...
        [oa.coordinate_convention.accelerator_axis_x-item{3}/2, -item{3}/2])));
end
end

function add_rf_hardware(geom, g, interfaces, tx, tz, shieldRadius, wallMm)
for index = 1:4
    tag = sprintf('rfrod%d', index);
    angleDeg = (index-1)*90;
    add_cylinder(geom, tag, g.rod_radius, g.rod_length, ...
        [tx+g.rod_z_min, g.rod_center_radius*cosd(angleDeg), ...
        tz+g.rod_center_radius*sind(angleDeg)], true);
end
add_cylinder(geom, 'rfshieldO', shieldRadius+wallMm, ...
    interfaces.exit.plate_z_min_mm-interfaces.entrance.plate_z_max_mm, ...
    [tx+interfaces.entrance.plate_z_max_mm, 0.0, tz], false);
add_cylinder(geom, 'rfshieldH', shieldRadius, ...
    interfaces.exit.plate_z_min_mm-interfaces.entrance.plate_z_max_mm, ...
    [tx+interfaces.entrance.plate_z_max_mm, 0.0, tz], false);
geom.feature.create('rfshield', 'Difference');
geom.feature('rfshield').selection('input').set({'rfshieldO'});
geom.feature('rfshield').selection('input2').set({'rfshieldH'});
geom.feature('rfshield').set('selresult', 'on');
add_annular_plate(geom, 'rfentrance', tx+interfaces.entrance.plate_z_min_mm, ...
    interfaces.entrance.plate_z_max_mm-interfaces.entrance.plate_z_min_mm, ...
    shieldRadius+wallMm, interfaces.entrance.aperture_radius_mm, tz);
add_annular_plate(geom, 'rfexit', tx+interfaces.exit.plate_z_min_mm, ...
    interfaces.exit.plate_z_max_mm-interfaces.exit.plate_z_min_mm, ...
    shieldRadius+wallMm, interfaces.exit.aperture_radius_mm, tz);
end

function add_annular_plate(geom, tag, xStart, thickness, outerRadius, holeRadius, zCenter)
add_cylinder(geom, [tag 'O'], outerRadius, thickness, [xStart, 0.0, zCenter], false);
add_cylinder(geom, [tag 'H'], holeRadius, thickness, [xStart, 0.0, zCenter], false);
geom.feature.create(tag, 'Difference');
geom.feature(tag).selection('input').set({[tag 'O']});
geom.feature(tag).selection('input2').set({[tag 'H']});
geom.feature(tag).set('selresult', 'on');
end
