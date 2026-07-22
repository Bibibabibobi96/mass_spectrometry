% Build the S2 passive RF-to-oaTOF connector geometry without mesh or physics.

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
metricsPath = getenv('RF_OATOF_S2_GEOMETRY_METRICS');
contractPath = getenv('RF_OATOF_S2_CONTRACT');
s1ContractPath = getenv('RF_OATOF_S2_S1_CONTRACT');
rfResolvedPath = getenv('RF_OATOF_S2_RF_RESOLVED');
oaBaselinePath = getenv('RF_OATOF_S2_OA_BASELINE');
oaComsolDir = getenv('RF_OATOF_S2_OA_COMSOL_DIR');
assert(~isempty(reportPath) && ~isempty(metricsPath), 'S2 output paths are incomplete.');
assert(isfile(contractPath) && isfile(s1ContractPath) && ...
    isfile(rfResolvedPath) && isfile(oaBaselinePath), ...
    'S2 contract inputs are incomplete.');
assert(isfolder(oaComsolDir), 'The oaTOF COMSOL source directory is missing.');

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not create the S2 COMSOL task report.');
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, 'TASK=S2_PASSIVE_CONNECTOR_GEOMETRY\n');

try
    contract = jsondecode(fileread(contractPath));
    s1 = jsondecode(fileread(s1ContractPath));
    rf = jsondecode(fileread(rfResolvedPath));
    oa = jsondecode(fileread(oaBaselinePath));
    assert(contract.permissions.geometry_builder_implementation_allowed, ...
        'The S2 contract does not authorize geometry construction.');
    assert(~contract.permissions.field_solve_allowed && ...
        ~contract.permissions.particle_runtime_allowed, ...
        'This build-only task requires field and particle runtime to remain disabled.');

    registration = contract.nominal_registration;
    connector = contract.passive_connector_geometry;
    sourceCenter = registration.source_exit_center_instrument_mm(:).';
    targetCenter = registration.target_entry_center_instrument_mm(:).';
    gapMm = registration.connector_gap_mm;
    assert(abs(targetCenter(1)-sourceCenter(1)-gapMm) < 1e-12, ...
        'Connector endpoints do not reproduce the frozen S2 gap.');
    assert(abs(connector.length_mm-gapMm) < 1e-12, ...
        'Connector geometry length differs from the registration gap.');

    import com.comsol.model.*
    import com.comsol.model.util.*
    tag = 'RFOATOF_S2_GEOMETRY';
    if any(strcmp(cell(ModelUtil.tags()), tag)), ModelUtil.remove(tag); end
    model = ModelUtil.create(tag);
    model.label(sprintf('RF to oaTOF S2 passive connector, gap %.6g mm', gapMm));
    comp = model.component.create('comp1', true);
    geom = comp.geom.create('geom1', 3);
    geom.lengthUnit('mm');
    configure_accelerator_parameters(model.param, oa);

    sourcePose = registration.source_component_pose;
    tx = sourcePose.translation_mm(1);
    tz = sourcePose.translation_mm(3);
    rfGeometry = rf.geometry_mm;
    shieldInnerRadius = s1.local_domain.rf_shield_inner_radius_mm;
    numericalWallMm = s1.local_domain.rf_shield_numerical_wall_thickness_mm;
    downstreamBufferMm = s1.local_domain.oatof_downstream_buffer_after_grid2_mm;
    oaGeometry = oa.geometry_mm;
    oaVacuumHalf = oaGeometry.accelerator_bore_half + ...
        oaGeometry.accelerator_ring_width + oaGeometry.accelerator_insulation_gap;

    add_cylinder(geom, 'rfvac', shieldInnerRadius, ...
        registration.source_exit_center_local_mm(3), ...
        [tx, 0.0, tz], true);
    add_cylinder(geom, 'connvac', connector.cavity.inner_radius_mm, gapMm, ...
        sourceCenter, true);
    add_oatof_vacuum(geom, oa, oaVacuumHalf, downstreamBufferMm);
    add_oatof_port(geom, connector, oa, oaVacuumHalf);
    add_grid_surfaces(geom, oa);
    geom.feature.create('univacgrid', 'Union');
    geom.feature('univacgrid').selection('input').set( ...
        {'rfvac','connvac','oavac','portvac','wp_grid1','wp_grid2'});
    geom.feature('univacgrid').set('intbnd', true);
    geom.feature('univacgrid').set('selresult', 'on');

    addpath(oaComsolDir);
    downstream = connector.downstream_entry_aperture;
    interfacePort = struct('enabled', true, ...
        'full_width_y_mm', downstream.full_width_y_mm, ...
        'full_height_z_mm', downstream.full_height_z_mm, ...
        'center_z_mm', downstream.center_mm(3));
    acceleratorRingTags = oatof_build_accelerator_geometry(geom, interfacePort);
    geom.feature('repeller').set('selresult', 'on');
    geom.feature('accelshield').set('selresult', 'on');
    for index = 1:numel(acceleratorRingTags)
        geom.feature(acceleratorRingTags{index}).set('selresult', 'on');
    end
    add_rf_hardware(geom, rfGeometry, tx, tz, shieldInnerRadius, numericalWallMm);
    geom.run;

    connectorDomains = comp.selection('geom1_connvac_dom').entities(3);
    portDomains = comp.selection('geom1_portvac_dom').entities(3);
    rfVacuumDomains = comp.selection('geom1_rfvac_dom').entities(3);
    oaVacuumDomains = comp.selection('geom1_oavac_dom').entities(3);
    assert(~isempty(connectorDomains) && ~isempty(portDomains), ...
        'Connector or oaTOF port vacuum selection is empty after geometry build.');
    assert(~isempty(rfVacuumDomains) && ~isempty(oaVacuumDomains), ...
        'Upstream or downstream vacuum selection is empty after geometry build.');
    geometryInfo = mphgeominfo(model, 'geom1');

    metrics = struct( ...
        'schema_version', 1, ...
        'role', 'rf_to_oatof_s2_passive_connector_geometry_metrics', ...
        'status', 'BUILT', ...
        'gap_mm', gapMm, ...
        'source_exit_center_instrument_mm', sourceCenter, ...
        'target_entry_center_instrument_mm', targetCenter, ...
        'connector_inner_radius_mm', connector.cavity.inner_radius_mm, ...
        'oatof_port_full_width_y_mm', downstream.full_width_y_mm, ...
        'oatof_port_full_height_z_mm', downstream.full_height_z_mm, ...
        'rf_shield_inner_radius_mm', shieldInnerRadius, ...
        'oatof_downstream_buffer_mm', downstreamBufferMm, ...
        'geometry_domains', geometryInfo.Ndomains, ...
        'connector_domain_count', numel(connectorDomains), ...
        'port_domain_count', numel(portDomains), ...
        'rf_vacuum_domain_count', numel(rfVacuumDomains), ...
        'oatof_vacuum_domain_count', numel(oaVacuumDomains), ...
        'mesh_built', false, ...
        'physics_created', false, ...
        'field_solved', false, ...
        'particle_runtime_executed', false, ...
        'model_saved', false, ...
        'claim_limit', 'Build-only S2 candidate geometry; no field, transport, stage PASS or Formal claim.');
    metricsDir = fileparts(metricsPath);
    if ~isfolder(metricsDir), mkdir(metricsDir); end
    metricsFid = fopen(metricsPath, 'w');
    assert(metricsFid >= 0, 'Could not create S2 geometry metrics.');
    fprintf(metricsFid, '%s', jsonencode(metrics, 'PrettyPrint', true));
    fclose(metricsFid);
    fprintf(fid, ['GAP_MM=%.17g\nCONNECTOR_DOMAINS=%d\nPORT_DOMAINS=%d\n' ...
        'GEOMETRY_DOMAINS=%d\nMESH_BUILT=false\nPHYSICS_CREATED=false\n' ...
        'FIELD_SOLVED=false\nPARTICLE_RUNTIME=false\nMODEL_SAVED=false\nSTATUS=PASS\n'], ...
        gapMm, numel(connectorDomains), numel(portDomains), geometryInfo.Ndomains);
    ModelUtil.remove(tag);
catch exception
    fprintf(fid, 'STATUS=FAIL\nERROR=%s\n', ...
        getReport(exception, 'extended', 'hyperlinks', 'off'));
    rethrow(exception)
end
clear cleanup

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

function add_rf_hardware(geom, g, tx, tz, shieldRadius, wallMm)
for index = 1:4
    tag = sprintf('rfrod%d', index);
    angleDeg = (index-1)*90;
    add_cylinder(geom, tag, g.rod_radius, g.rod_length, ...
        [tx+g.rod_z_min, g.rod_center_radius*cosd(angleDeg), ...
        tz+g.rod_center_radius*sind(angleDeg)], true);
end
add_cylinder(geom, 'rfshieldO', shieldRadius+wallMm, ...
    g.exit_enclosure_z_min-g.entrance_plate_z_max, ...
    [tx+g.entrance_plate_z_max, 0.0, tz], false);
add_cylinder(geom, 'rfshieldH', shieldRadius, ...
    g.exit_enclosure_z_min-g.entrance_plate_z_max, ...
    [tx+g.entrance_plate_z_max, 0.0, tz], false);
geom.feature.create('rfshield', 'Difference');
geom.feature('rfshield').selection('input').set({'rfshieldO'});
geom.feature('rfshield').selection('input2').set({'rfshieldH'});
geom.feature('rfshield').set('selresult', 'on');
add_annular_plate(geom, 'rfentrance', tx+g.entrance_plate_z_min, ...
    g.entrance_plate_z_max-g.entrance_plate_z_min, ...
    shieldRadius+wallMm, g.entrance_aperture_radius, tz);
add_annular_plate(geom, 'rfexit', tx+g.exit_enclosure_z_min, ...
    g.exit_enclosure_front_wall_end_z-g.exit_enclosure_z_min, ...
    shieldRadius+wallMm, g.exit_aperture_radius, tz);
end

function add_annular_plate(geom, tag, xStart, thickness, outerRadius, holeRadius, zCenter)
add_cylinder(geom, [tag 'O'], outerRadius, thickness, [xStart, 0.0, zCenter], false);
add_cylinder(geom, [tag 'H'], holeRadius, thickness, [xStart, 0.0, zCenter], false);
geom.feature.create(tag, 'Difference');
geom.feature(tag).selection('input').set({[tag 'O']});
geom.feature(tag).selection('input2').set({[tag 'H']});
geom.feature(tag).set('selresult', 'on');
end
