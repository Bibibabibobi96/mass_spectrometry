function [model, context] = build_pre_pulse_interface_transport_model( ...
    resolvedConnection, sharedJoint, rf, oa, oaComsolDir, ...
    multipoleComsolDir, modelTag)
% Build the shared RF-multipole PrePulse connector geometry and return selections.
% REPOSITORY_CONTRACT: MATLAB_BUILD_ONLY

arguments
    resolvedConnection struct
    sharedJoint struct
    rf struct
    oa struct
    oaComsolDir (1,:) char
    multipoleComsolDir (1,:) char
    modelTag (1,:) char
end

assert_resolved_connection(resolvedConnection);
registration = resolvedConnection.spatial_registration;
connector = resolvedConnection.connector;
transitionAperture = resolvedConnection.transition_aperture;
sourceRotation = registration.rotation_upstream_to_downstream;
sourceTranslation = registration.translation_mm(:);
sourceAxis = registration.transformed_upstream_normal(:);
upstreamSurface = resolvedConnection.port_geometry.upstream.mating_surface;
downstreamSurface = resolvedConnection.port_geometry.downstream.mating_surface;
sourceCenter = (sourceRotation*upstreamSurface.center_mm(:)+sourceTranslation).';
targetCenter = downstreamSurface.center_mm(:).';
gapMm = registration.actual_gap_mm;
positionToleranceMm = registration.position_tolerance_mm;
connectorPresent = gapMm > positionToleranceMm;
assert_connection_geometry(sourceCenter, targetCenter, sourceAxis, ...
    connector, transitionAperture, resolvedConnection);

import com.comsol.model.*
import com.comsol.model.util.*
if any(strcmp(cell(ModelUtil.tags()), modelTag)), ModelUtil.remove(modelTag); end
model = ModelUtil.create(modelTag);
model.label(sprintf('RF to oaTOF PrePulse passive connector, gap %.6g mm', gapMm));
comp = model.component.create('comp1', true);
geom = comp.geom.create('geom1', 3);
geom.lengthUnit('mm');
configure_accelerator_parameters(model.param, oa);

sourcePose = struct( ...
    'rotation_component_to_instrument', sourceRotation, ...
    'translation_mm', sourceTranslation);
rfGeometry = rf.geometry_mm;
shieldInnerRadius = sharedJoint.local_domain.rf_shield_inner_radius_mm;
numericalWallMm = sharedJoint.local_domain.rf_shield_numerical_wall_thickness_mm;
downstreamBufferMm = sharedJoint.local_domain.oatof_downstream_buffer_after_grid2_mm;
oaGeometry = oa.geometry_mm;
oaVacuumHalf = oaGeometry.accelerator_bore_half + ...
    oaGeometry.accelerator_ring_width + oaGeometry.accelerator_insulation_gap;

add_cylinder(geom, 'rfvac', shieldInnerRadius, ...
    upstreamSurface.center_mm(3), sourceTranslation.', sourceAxis, true);
if connectorPresent
    add_cylinder(geom, 'connvac', connector.inner_radius_mm, ...
        gapMm, sourceCenter, sourceAxis, true);
end
add_oatof_vacuum(geom, oa, oaVacuumHalf, downstreamBufferMm);
add_oatof_port(geom, transitionAperture, oa, oaVacuumHalf);
add_grid_surfaces(geom, oa);
geom.feature.create('univacgrid', 'Union');
vacuumInputs = {'rfvac','oavac','portvac','wp_grid1','wp_grid2'};
if connectorPresent, vacuumInputs = [vacuumInputs(1), {'connvac'}, vacuumInputs(2:end)]; end
geom.feature('univacgrid').selection('input').set(vacuumInputs);
geom.feature('univacgrid').set('intbnd', true);
geom.feature('univacgrid').set('selresult', 'on');

addpath(oaComsolDir, multipoleComsolDir);
interfacePort = struct('enabled', true, ...
    'full_width_y_mm', transitionAperture.full_width_mm, ...
    'full_height_z_mm', transitionAperture.full_height_mm, ...
    'center_z_mm', transitionAperture.center_mm(3));
acceleratorRingTags = oatof_build_accelerator_geometry( ...
    geom, oa.rings.accelerator_count, interfacePort);
geom.feature('repeller').set('selresult', 'on');
geom.feature('accelshield').set('selresult', 'on');
for index = 1:numel(acceleratorRingTags)
    geom.feature(acceleratorRingTags{index}).set('selresult', 'on');
end
rfRodTags = add_rf_hardware(geom, rfGeometry, rf.interfaces_mm, sourcePose, ...
    sourceAxis, shieldInnerRadius, numericalWallMm);
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
    'source_axis', sourceAxis.', ...
    'connector_inner_radius_mm', connector.inner_radius_mm, ...
    'port_full_width_y_mm', transitionAperture.full_width_mm, ...
    'port_full_height_z_mm', transitionAperture.full_height_mm, ...
    'interface_potential_V', upstreamSurface.potential_V, ...
    'rf_shield_inner_radius_mm', shieldInnerRadius, ...
    'oatof_downstream_buffer_mm', downstreamBufferMm, ...
    'connector_domain_count', numel(connectorDomains), ...
    'port_domain_count', numel(portDomains), ...
    'rf_vacuum_domain_count', numel(rfVacuumDomains), ...
    'oatof_vacuum_domain_count', numel(oaVacuumDomains), ...
    'accelerator_ring_tags', {acceleratorRingTags}, ...
    'rf_ground_tags', {{'rfshield','rfentrance','rfexit'}}, ...
    'rf_rod_tags', {rfRodTags}, ...
    'rf_rod_electrode_groups', [rfGeometry.rod_array.rods.electrode_group]);
end

function assert_resolved_connection(resolved)
assert(strcmp(resolved.role,'resolved_connection_do_not_edit') && ...
    strcmp(resolved.compatibility.status,'pass'), ...
    'PrePulse requires a compatible resolved_connection input.');
assert(strcmp(resolved.coupling_mode,'monolithic_joint_solve'), ...
    'PrePulse requires monolithic_joint_solve field ownership.');
assert(strcmp(resolved.potential_alignment.mode,'continuous') && ...
    abs(resolved.potential_alignment.actual_step_V) <= ...
        resolved.potential_alignment.tolerance_V, ...
    'PrePulse requires continuous port potential alignment.');
assert(strcmp(resolved.clock_alignment.mode,'same_origin') && ...
    abs(resolved.clock_alignment.offset_s) <= 1e-15, ...
    'PrePulse requires one unchanged instrument clock origin.');
end

function assert_connection_geometry(sourceCenter, targetCenter, sourceAxis, ...
    connector, aperture, resolved)
tolerance = resolved.spatial_registration.position_tolerance_mm;
gapMm = resolved.spatial_registration.actual_gap_mm;
assert(abs(norm(sourceAxis)-1.0) <= 1e-12 && ...
    all(abs(targetCenter(:)-sourceCenter(:)-gapMm*sourceAxis(:)) <= tolerance,'all'), ...
    'Resolved connection centers, axis and gap are inconsistent.');
assert(abs(connector.length_mm-gapMm) <= tolerance && connector.inner_radius_mm > 0, ...
    'Resolved connector geometry differs from the registered gap.');
assert(strcmp(aperture.coordinate_frame_id, ...
    resolved.port_geometry.downstream.coordinate_frame.frame_id) && ...
    all(abs(aperture.center_mm(:)-targetCenter(:)) <= tolerance,'all') && ...
    aperture.full_width_mm > 0 && aperture.full_height_mm > 0, ...
    'Resolved transition aperture is inconsistent with the downstream port.');
assert(all(abs(sourceAxis(:)-[1;0;0]) <= 1e-12,'all') && ...
    all(abs(aperture.width_axis(:)-[0;1;0]) <= 1e-12,'all') && ...
    all(abs(aperture.height_axis(:)-[0;0;1]) <= 1e-12,'all'), ...
    'The current COMSOL joint implementation requires RF +z -> oa +x.');
segments = resolved.field_ownership_segments;
if gapMm <= tolerance
    assert(isempty(segments), ...
        'Direct mating cannot retain a finite connector field-ownership segment.');
else
    assert(numel(segments) == 1 && strcmp(segments(1).owner,'integration') && ...
        abs(segments(1).start_mm) <= tolerance && ...
        abs(segments(1).end_mm-gapMm) <= tolerance, ...
        'Finite connector field ownership must cover the full integration gap.');
end
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

function add_cylinder(geom, tag, radiusMm, lengthMm, positionMm, axisDirection, selectionEnabled)
geom.feature.create(tag, 'Cylinder');
geom.feature(tag).set('axis', axisDirection(:).');
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

function add_oatof_port(geom, port, oa, vacuumHalfMm)
g = oa.geometry_mm;
outerX = oa.coordinate_convention.accelerator_axis_x-(vacuumHalfMm+g.accelerator_shield_wall);
innerX = oa.coordinate_convention.accelerator_axis_x-vacuumHalfMm;
geom.feature.create('portvac', 'Block');
geom.feature('portvac').set('size', cellstr(compose('%.17g[mm]', ...
    [innerX-outerX, port.full_width_mm, port.full_height_mm])));
geom.feature('portvac').set('pos', cellstr(compose('%.17g[mm]', ...
    [outerX, port.center_mm(2)-port.full_width_mm/2, ...
    port.center_mm(3)-port.full_height_mm/2])));
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

function rodTags = add_rf_hardware( ...
    geom, g, interfaces, sourcePose, sourceAxis, shieldRadius, wallMm)
assert(isfield(g,'rod_array') && isfield(g.rod_array,'rods') && ...
    ~isempty(g.rod_array.rods), ...
    'RF multipole geometry must provide a nonempty resolved rod_array.');
assert(all(abs(sourcePose.rotation_component_to_instrument(:)- ...
    [0;1;0;0;0;1;1;0;0]) <= 1e-12,'all'), ...
    'The common rod builder requires the resolved RF +z to oaTOF +x mapping.');
rodTags = create_multipole_round_rods(geom, g.rod_array, 'rfrod', 'x', ...
    sourcePose.translation_mm(:).');
add_cylinder(geom, 'rfshieldO', shieldRadius+wallMm, ...
    interfaces.exit.aperture_plate_upstream_face_z_mm-interfaces.entrance.aperture_plate_downstream_face_z_mm, ...
    transform_source_position(sourcePose, ...
        [0.0, 0.0, interfaces.entrance.aperture_plate_downstream_face_z_mm]), sourceAxis, false);
add_cylinder(geom, 'rfshieldH', shieldRadius, ...
    interfaces.exit.aperture_plate_upstream_face_z_mm-interfaces.entrance.aperture_plate_downstream_face_z_mm, ...
    transform_source_position(sourcePose, ...
        [0.0, 0.0, interfaces.entrance.aperture_plate_downstream_face_z_mm]), sourceAxis, false);
geom.feature.create('rfshield', 'Difference');
geom.feature('rfshield').selection('input').set({'rfshieldO'});
geom.feature('rfshield').selection('input2').set({'rfshieldH'});
geom.feature('rfshield').set('selresult', 'on');
add_annular_plate(geom, 'rfentrance', interfaces.entrance.aperture_plate_upstream_face_z_mm, ...
    interfaces.entrance.aperture_plate_downstream_face_z_mm-interfaces.entrance.aperture_plate_upstream_face_z_mm, ...
    shieldRadius+wallMm, interfaces.entrance.aperture_radius_mm, sourcePose, sourceAxis);
add_annular_plate(geom, 'rfexit', interfaces.exit.aperture_plate_upstream_face_z_mm, ...
    interfaces.exit.aperture_plate_downstream_face_z_mm-interfaces.exit.aperture_plate_upstream_face_z_mm, ...
    shieldRadius+wallMm, interfaces.exit.aperture_radius_mm, sourcePose, sourceAxis);
end

function add_annular_plate(geom, tag, localZStart, thickness, outerRadius, holeRadius, sourcePose, sourceAxis)
position = transform_source_position(sourcePose, [0.0, 0.0, localZStart]);
add_cylinder(geom, [tag 'O'], outerRadius, thickness, position, sourceAxis, false);
add_cylinder(geom, [tag 'H'], holeRadius, thickness, position, sourceAxis, false);
geom.feature.create(tag, 'Difference');
geom.feature(tag).selection('input').set({[tag 'O']});
geom.feature(tag).selection('input2').set({[tag 'H']});
geom.feature(tag).set('selresult', 'on');
end

function positionMm = transform_source_position(sourcePose, localPositionMm)
rotation = sourcePose.rotation_component_to_instrument;
translation = sourcePose.translation_mm(:);
positionMm = (rotation*localPositionMm(:)+translation).';
end
