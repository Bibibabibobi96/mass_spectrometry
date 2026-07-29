% Solve finite 3D circular-rod fields and direct RF/zero-RF particle transport.

addpath(fileparts(mfilename('fullpath')));
addpath(fullfile(fileparts(mfilename('fullpath')),'..','comsol'));

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
resolvedDesignPath = getenv('MULTIPOLE_RESOLVED_DESIGN');
numericsPath = getenv('MULTIPOLE_SOLVER_NUMERICS');
sourcePath = getenv('MULTIPOLE_L3_PARTICLE_SOURCE');
sourceMetadataPath = getenv('MULTIPOLE_L3_PARTICLE_SOURCE_METADATA');
runtimeDir = getenv('MULTIPOLE_L3_RUNTIME_DIR');
solverProgressDir = getenv('MULTIPOLE_L3_SOLVER_PROGRESS_DIR');
eventsPath = getenv('MULTIPOLE_L3_EVENTS');
trajectoryPath = getenv('MULTIPOLE_L3_TRAJECTORIES');
metricsPath = getenv('MULTIPOLE_L3_METRICS');
plotPath = getenv('MULTIPOLE_L3_PLOT');
modelPath = getenv('MULTIPOLE_L3_MODEL');
canonicalStatePath = getenv('MULTIPOLE_L3_CANONICAL_STATE');
primaryCanonicalStatePath = getenv('MULTIPOLE_L3_PRIMARY_CANONICAL_STATE');
controlCanonicalStatePath = getenv('MULTIPOLE_L3_CONTROL_CANONICAL_STATE');
primaryTrajectoryPath = getenv('MULTIPOLE_L3_PRIMARY_TRAJECTORIES');
controlTrajectoryPath = getenv('MULTIPOLE_L3_CONTROL_TRAJECTORIES');
stopStage = getenv('MULTIPOLE_L3_STOP_STAGE');
fieldSamplePointsPath = getenv('MULTIPOLE_L3_FIELD_SAMPLE_POINTS');
fieldSamplesPath = getenv('MULTIPOLE_L3_FIELD_SAMPLES');
assert(any(strcmp(stopStage, {'transport', 'mesh_build', 'field_solve'})), ...
    'Finite 3D multipole stop stage is unsupported.');
meshBuildOnly = strcmp(stopStage, 'mesh_build');
fieldSolveOnly = strcmp(stopStage, 'field_solve');
if fieldSolveOnly
    assert(~isempty(fieldSamplePointsPath) && ~isempty(fieldSamplesPath), ...
        'Field-solve sampling environment is incomplete.');
    assert(isfile(fieldSamplePointsPath), ...
        'Field-solve sampling points are missing.');
end
required = {reportPath, resolvedDesignPath, numericsPath, sourcePath, sourceMetadataPath, ...
    runtimeDir, solverProgressDir, eventsPath, trajectoryPath, metricsPath, plotPath, modelPath};
assert(all(~cellfun(@isempty, required)), 'Finite 3D multipole environment is incomplete.');
assert(isfile(resolvedDesignPath) && isfile(numericsPath) && isfile(sourcePath) && isfile(sourceMetadataPath), ...
    'Resolved-design finite 3D multipole inputs are missing.');
if ~isfolder(runtimeDir), mkdir(runtimeDir); end
assert(isfolder(solverProgressDir), ...
    'Finite 3D multipole solver-progress directory is missing.');

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not create the finite 3D transport report.');
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, 'TASK=MULTIPOLE_FINITE_3D_TRANSPORT\n');

try
    design = jsondecode(fileread(resolvedDesignPath));
    numerics = jsondecode(fileread(numericsPath));
    sourceMetadata = jsondecode(fileread(sourceMetadataPath));
    assert(strcmp(design.role,'multipole_resolved_design_do_not_edit'), ...
        'COMSOL requires the canonical multipole resolved design.');
    assert(strcmp(numerics.role,'multipole_comsol_solver_numerics'), ...
        'COMSOL numerical contract role differs.');
    assert(isfield(numerics,'stationary_linear_solver_backend'), ...
        'COMSOL numerical contract omits the stationary linear-solver backend.');
    stationaryLinearSolverBackend=lower(char(numerics.stationary_linear_solver_backend));
    assert(any(strcmp(stationaryLinearSolverBackend, {'mumps', 'pardiso', 'cg_amg'})), ...
        'COMSOL stationary linear-solver backend is unsupported.');
    hasIterativeSettings=isfield(numerics,'stationary_iterative_solver');
    if strcmp(stationaryLinearSolverBackend,'cg_amg')
        assert(hasIterativeSettings, ...
            'CG-AMG requires stationary iterative-solver settings.');
        stationaryIterativeSettings=numerics.stationary_iterative_solver;
    else
        assert(~hasIterativeSettings, ...
            'Direct stationary solvers forbid iterative-solver settings.');
        stationaryIterativeSettings=struct();
    end
    assert(isfield(numerics,'electric_potential_element_order'), ...
        'COMSOL numerical contract omits the electric-potential element order.');
    electricPotentialElementOrder=lower(char(numerics.electric_potential_element_order));
    assert(any(strcmp(electricPotentialElementOrder, {'linear', 'quadratic'})), ...
        'COMSOL electric-potential element order is unsupported.');
    assert(strcmp(sourceMetadata.role,'multipole_canonical_particle_source_metadata'), ...
        'COMSOL particle-source metadata role differs.');
    assert(strcmp(sourceMetadata.parent_resolved_design_sha256,design.resolved_sha256), ...
        'COMSOL particle source is not bound to this resolved design.');
    assert(sourceMetadata.charge_state==design.particle_source.charge_state, ...
        'COMSOL particle-source charge differs from the resolved design.');
    axialTopology = design.axial_drive.topology;
    segmentedAccelerationEnabled = strcmp(axialTopology,'segmented_rod_axial_acceleration');
    segmentedRodGeometry = isfield(design.segmentation,'segmented_rod_array');
    exitAperturePlateAcceleration = strcmp(axialTopology,'exit_aperture_plate_potential_step');
    accelerationEnabled = segmentedAccelerationEnabled || exitAperturePlateAcceleration;
    if segmentedRodGeometry
        segmentationAcceleration = design.segmentation.axial_acceleration;
        assert(strcmp(segmentationAcceleration.role,'multipole_axial_acceleration_resolved_contract'), ...
            'Resolved design segmentation is incomplete.');
    else
        segmentationAcceleration = struct();
    end
    if exitAperturePlateAcceleration
        claimLimit = ['N=100 functional exit-aperture-plate acceleration reference only; ' ...
            'acceleration is localized near the exit and does not establish continuous ' ...
            'in-rod acceleration, convergence, cross-solver numerical equivalence, ' ...
            'mechanical or Formal qualification.'];
    else
        claimLimit = 'Resolved-design functional transport only; no formal claim.';
    end
    source = readtable(sourcePath);
    n = design.identity.radial_order_n;
    electrodeCount = design.identity.electrode_count;
    assert(electrodeCount == 2*n, 'Finite 3D multipole identity is invalid.');
    resolvedGeometry = design.geometry_mm;
    selected = struct('rod_radius_ratio',resolvedGeometry.rod_radius_ratio, ...
        'rod_radius_mm',resolvedGeometry.rod_radius, ...
        'rod_center_radius_mm',resolvedGeometry.rod_center_radius);
    r0 = resolvedGeometry.inscribed_radius_r0;
    rodArray = resolvedGeometry.rod_array;
    rods = rodArray.rods;
    assert(numel(rods) == electrodeCount, 'Resolved rod-array identity differs.');
    enclosure = resolvedGeometry.enclosure;
    interfaces = design.interfaces_mm;
    g = struct('working_region_radius',enclosure.working_region_radius_mm, ...
        'entrance_interface',struct('aperture_radius_mm',interfaces.entrance.aperture_radius_mm, ...
        'plate_thickness_mm',interfaces.entrance.aperture_plate_downstream_face_z_mm-interfaces.entrance.aperture_plate_upstream_face_z_mm, ...
        'connector_length_mm',interfaces.entrance.connector_length_mm, ...
        'connector_shape',interfaces.entrance.connector_shape), ...
        'exit_interface',struct('aperture_radius_mm',interfaces.exit.aperture_radius_mm, ...
        'plate_thickness_mm',interfaces.exit.aperture_plate_downstream_face_z_mm-interfaces.exit.aperture_plate_upstream_face_z_mm, ...
        'connector_length_mm',interfaces.exit.connector_length_mm, ...
        'connector_shape',interfaces.exit.connector_shape));
    d = struct('rod_length',resolvedGeometry.rod_length, ...
        'rod_z_min',resolvedGeometry.rod_z_min,'rod_z_max',resolvedGeometry.rod_z_max, ...
        'vacuum_z_min',enclosure.vacuum_z_min_mm,'vacuum_z_max',enclosure.vacuum_z_max_mm, ...
        'release_plane_z',interfaces.entrance.release_plane_z_mm, ...
        'census_plane_z',interfaces.exit.census_plane_z_mm, ...
        'handoff_plane_z',interfaces.exit.handoff_plane_z_mm, ...
        'entrance_aperture_plate_upstream_face_z',interfaces.entrance.aperture_plate_upstream_face_z_mm, ...
        'entrance_aperture_plate_downstream_face_z',interfaces.entrance.aperture_plate_downstream_face_z_mm, ...
        'exit_aperture_plate_upstream_face_z',interfaces.exit.aperture_plate_upstream_face_z_mm, ...
        'exit_aperture_plate_downstream_face_z',interfaces.exit.aperture_plate_downstream_face_z_mm, ...
        'exit_aperture_crossing_plane_z',interfaces.exit.aperture_crossing_plane_z_mm);
    geometryModel = enclosure.model;
    rectangularReference = strcmp(geometryModel,'rectangular_reference_enclosure_v1');
    assert(rectangularReference || strcmp(geometryModel,'cylindrical_grounded_shield_v1'), ...
        'Unsupported shared finite-3D geometry model.');
    censusRadius=g.working_region_radius;
    if isfield(enclosure,'physical_detector_radius_mm')
        censusRadius=enclosure.physical_detector_radius_mm;
    end
    assert(all(abs(source.z_mm-d.release_plane_z) < 1e-12), ...
        'Particle source differs from the canonical release plane.');
    rf = design.drive;
    staticElectrodes = design.static_electrodes_V;
    import com.comsol.model.*
    import com.comsol.model.util.*
    tag = sprintf('MULTIPOLE_FINITE_3D_%d', electrodeCount);
    if any(strcmp(cell(ModelUtil.tags()), tag)), ModelUtil.remove(tag); end
    model = ModelUtil.create(tag);
    model.label(sprintf('%d-pole finite 3D circular-rod L3 transport', electrodeCount));
    model.param.set('V_rf', sprintf('%.17g[V]', rf.rf_amplitude_V_zero_to_peak_per_group));
    model.param.set('V_dc', sprintf('%.17g[V]', rf.dc_amplitude_V_per_group));
    model.param.set('V_axis', sprintf('%.17g[V]', rf.common_mode_offset_V));
    model.param.set('f_rf', sprintf('%.17g[Hz]', rf.frequency_Hz));
    model.param.set('phi_rf', sprintf('%.17g[rad]', rf.phase_rad));
    model.param.set('rf_scale', '1');
    model.param.set('axial_scale', '1');
    if strcmp(rf.waveform, 'sine')
        rfWaveform = 'sin(2*pi*f_rf*t+phi_rf)';
    elseif strcmp(rf.waveform, 'cosine')
        rfWaveform = 'cos(2*pi*f_rf*t+phi_rf)';
    else
        error('Unsupported shared multipole RF waveform: %s', rf.waveform);
    end
    model.param.set('m_ion', sprintf('%.17g[kg]', sourceMetadata.mass_amu*1.66053906660e-27));
    comp = model.component.create('comp1', true);
    geom = comp.geom.create('geom1', 3);
    geom.lengthUnit('mm');
    vacuumHeight = d.vacuum_z_max-d.vacuum_z_min;
    if rectangularReference
        shieldOuter=enclosure.outer_half_width_mm;
        geom.feature.create('vac', 'Block');
        geom.feature('vac').set('size',{sprintf('%.17g[mm]',2*shieldOuter), ...
            sprintf('%.17g[mm]',2*shieldOuter),sprintf('%.17g[mm]',vacuumHeight)});
        geom.feature('vac').set('pos',{sprintf('%.17g[mm]',-shieldOuter), ...
            sprintf('%.17g[mm]',-shieldOuter),sprintf('%.17g[mm]',d.vacuum_z_min)});
    else
        shieldOuter = enclosure.shield_outer_radius_mm;
        geom.feature.create('vac', 'Cylinder');
        geom.feature('vac').set('r', sprintf('%.17g[mm]', enclosure.shield_inner_radius_mm));
        geom.feature('vac').set('h', sprintf('%.17g[mm]', vacuumHeight));
        geom.feature('vac').set('pos', {'0','0',sprintf('%.17g[mm]', d.vacuum_z_min)});
    end
    geom.feature('vac').set('selresult', 'on');
    geom.feature.create('workvol', 'Cylinder');
    geom.feature('workvol').set('r', sprintf('%.17g[mm]', g.working_region_radius));
    geom.feature('workvol').set('h', sprintf('%.17g[mm]', vacuumHeight));
    geom.feature('workvol').set('pos', {'0','0',sprintf('%.17g[mm]', d.vacuum_z_min)});
    geom.feature('workvol').set('selresult', 'on');
    meshStrategy = 'selected_region_free_tetrahedral';
    if isfield(numerics.mesh, 'strategy')
        meshStrategy = numerics.mesh.strategy;
    end
    segmentHybridMesh = strcmp(meshStrategy, 'physical_segment_hybrid_swept_tetra_v1');
    assert(segmentHybridMesh || strcmp(meshStrategy, 'selected_region_free_tetrahedral'), ...
        'Unsupported finite-3D multipole mesh strategy: %s', meshStrategy);
    sweepGeometryTags = {};
    if segmentHybridMesh
        assert(~rectangularReference && segmentedRodGeometry, ...
            'Segment-hybrid meshing requires cylindrical segmented-rod geometry.');
        hybrid = numerics.mesh.hybrid;
        assert(isfinite(hybrid.segment_end_buffer_mm) && hybrid.segment_end_buffer_mm > 0, ...
            'Segment-hybrid end buffer must be positive and finite.');
        assert(hybrid.core_radius_mm > ...
            selected.rod_center_radius_mm + selected.rod_radius_mm, ...
            ['Segment-hybrid core boundary must lie strictly outside every rod; ' ...
            'a tangent core partition is forbidden.']);
        geom.feature.create('meshCore', 'Cylinder');
        geom.feature('meshCore').set('r', sprintf('%.17g[mm]', hybrid.core_radius_mm));
        geom.feature('meshCore').set('h', sprintf('%.17g[mm]', vacuumHeight));
        geom.feature('meshCore').set('pos', {'0','0',sprintf('%.17g[mm]', d.vacuum_z_min)});
        geom.feature('meshCore').set('selresult', 'on');
        if isfield(hybrid, 'sensitive_region')
            sensitive = hybrid.sensitive_region;
            assert(isfinite(sensitive.particle_corridor_radius_mm) && ...
                sensitive.particle_corridor_radius_mm > 0 && ...
                sensitive.particle_corridor_radius_mm <= resolvedGeometry.inscribed_radius_r0, ...
                'Localized particle corridor must lie within the inscribed radius.');
            geom.feature.create('meshSensitiveCorridor', 'Cylinder');
            geom.feature('meshSensitiveCorridor').set('r', ...
                sprintf('%.17g[mm]', sensitive.particle_corridor_radius_mm));
            geom.feature('meshSensitiveCorridor').set('h', ...
                sprintf('%.17g[mm]', vacuumHeight));
            geom.feature('meshSensitiveCorridor').set('pos', ...
                {'0','0',sprintf('%.17g[mm]', d.vacuum_z_min)});
            geom.feature('meshSensitiveCorridor').set('selresult', 'on');
        end
        physicalSegments = segmentationAcceleration.derived.segments;
        assert(numel(physicalSegments) == hybrid.physical_segment_count, ...
            'Segment-hybrid physical-segment count differs from the resolved design.');
        sweepGeometryTags = cell(1, numel(physicalSegments));
        for segmentIndex = 1:numel(physicalSegments)
            segment = physicalSegments(segmentIndex);
            sweepZMin = segment.z_min_mm + hybrid.segment_end_buffer_mm;
            sweepZMax = segment.z_max_mm - hybrid.segment_end_buffer_mm;
            assert(sweepZMax > sweepZMin, ...
                'Segment-hybrid end buffers consume physical rod segment %d.', segmentIndex);
            assert(abs((sweepZMax-sweepZMin)-hybrid.swept_length_per_segment_mm) < 1e-9, ...
                'Segment-hybrid swept length differs for physical segment %d.', segmentIndex);
            tag = sprintf('meshSweep%d', segmentIndex);
            sweepGeometryTags{segmentIndex} = tag;
            geom.feature.create(tag, 'Cylinder');
            geom.feature(tag).set('r', sprintf('%.17g[mm]', enclosure.shield_inner_radius_mm));
            geom.feature(tag).set('h', sprintf('%.17g[mm]', sweepZMax-sweepZMin));
            geom.feature(tag).set('pos', {'0','0',sprintf('%.17g[mm]', sweepZMin)});
            geom.feature(tag).set('selresult', 'on');
        end
    end
    if segmentedRodGeometry
        [rodTags,rodMetadata]=create_multipole_segmented_round_rods( ...
            geom,rodArray,segmentationAcceleration,'rod');
    else
        rodTags=create_multipole_round_rods(geom,rodArray,'rod','z',[0 0 0]);
        rodMetadata=repmat(struct('tag','','rod_id',0,'electrode_group',0, ...
            'segment_id',1,'common_mode_V',rf.common_mode_offset_V),1,electrodeCount);
        for k=1:electrodeCount
            rodMetadata(k).tag=rodTags{k}; rodMetadata(k).rod_id=rods(k).rod_id;
            rodMetadata(k).electrode_group=rods(k).electrode_group;
        end
    end
    if rectangularReference
        create_rectangular_reference_enclosure(geom,enclosure,g,d,censusRadius);
        connectorTags={};
        if create_comsol_grounded_connector(geom,'connIn',g.entrance_interface.connector_shape, ...
                enclosure.outer_half_width_mm,g.entrance_interface.aperture_radius_mm, ...
                g.entrance_interface.connector_length_mm, ...
                d.entrance_aperture_plate_upstream_face_z-g.entrance_interface.connector_length_mm)
            connectorTags{end+1}='connIn';
        end
        if create_comsol_grounded_connector(geom,'connOut',g.exit_interface.connector_shape, ...
                enclosure.inner_half_width_mm,g.exit_interface.aperture_radius_mm, ...
                g.exit_interface.connector_length_mm,d.exit_aperture_plate_downstream_face_z)
            connectorTags{end+1}='connOut';
        end
        groundTags=[{'entrance','exit_enclosure','physical_detector'},connectorTags];
    else
        create_comsol_cylindrical_shell(geom,'shield',enclosure.shield_inner_radius_mm, ...
            shieldOuter,vacuumHeight,d.vacuum_z_min);
        create_comsol_cylinder(geom,'outerIn',shieldOuter, ...
            enclosure.entrance_outer_endcap_downstream_face_z_mm-enclosure.entrance_outer_endcap_upstream_face_z_mm, ...
            enclosure.entrance_outer_endcap_upstream_face_z_mm);
        create_comsol_cylinder(geom,'outerOut',shieldOuter, ...
            enclosure.exit_outer_endcap_downstream_face_z_mm-enclosure.exit_outer_endcap_upstream_face_z_mm, ...
            enclosure.exit_outer_endcap_upstream_face_z_mm);
        create_comsol_apertured_plate(geom, 'capIn', shieldOuter, ...
            g.entrance_interface.aperture_radius_mm, g.entrance_interface.plate_thickness_mm, ...
            d.entrance_aperture_plate_upstream_face_z);
        create_comsol_apertured_plate(geom, 'capOut', shieldOuter, ...
            g.exit_interface.aperture_radius_mm, g.exit_interface.plate_thickness_mm, ...
            d.exit_aperture_plate_upstream_face_z);
        connectorTags = {};
        if create_comsol_grounded_connector(geom,'connIn',g.entrance_interface.connector_shape, ...
                shieldOuter,g.entrance_interface.aperture_radius_mm, ...
                g.entrance_interface.connector_length_mm, ...
                d.entrance_aperture_plate_upstream_face_z-g.entrance_interface.connector_length_mm)
            connectorTags{end+1} = 'connIn';
        end
        if create_comsol_grounded_connector(geom,'connOut',g.exit_interface.connector_shape, ...
                shieldOuter,g.exit_interface.aperture_radius_mm, ...
                g.exit_interface.connector_length_mm,d.exit_aperture_plate_downstream_face_z)
            connectorTags{end+1} = 'connOut';
        end
        groundTags = [{'shield','outerIn','outerOut','capIn','capOut'}, connectorTags];
    end
    geom.run;

    electrodeTags = [rodTags, groundTags];
    electrodeDomains = cellfun(@(name) ['geom1_' name '_dom'], electrodeTags, ...
        'UniformOutput', false);
    comp.selection.create('sel_vac', 'Complement');
    comp.selection('sel_vac').set('input', electrodeDomains);
    rodBoundarySelectionTags = cell(1, numel(rodTags));
    for k = 1:numel(rodTags)
        boundarySelection = ['selb_' rodTags{k}];
        comp.selection.create(boundarySelection, 'Adjacent');
        comp.selection(boundarySelection).set('input', {['geom1_' rodTags{k} '_dom']});
        rodBoundarySelectionTags{k} = boundarySelection;
    end
    sweepRodBoundarySelectionTags = {};
    interfaceBoundarySelectionTags = {};
    if segmentHybridMesh
        sweepRodBoundarySelectionTags = cell(1, numel(physicalSegments));
        for segmentIndex = 1:numel(physicalSegments)
            segmentBoundarySelections = rodBoundarySelectionTags( ...
                [rodMetadata.segment_id] == physicalSegments(segmentIndex).segment_id);
            assert(numel(segmentBoundarySelections) == electrodeCount, ...
                'Segment-hybrid rod-boundary identity differs for physical segment %d.', ...
                segmentIndex);
            selectionTag = sprintf('sel_mesh_sweep_%d_rod_bnd', segmentIndex);
            comp.selection.create(selectionTag, 'Union');
            comp.selection(selectionTag).set('entitydim', 2);
            comp.selection(selectionTag).set('input', segmentBoundarySelections);
            sweepRodBoundarySelectionTags{segmentIndex} = selectionTag;
        end
        if isfield(numerics.mesh.hybrid, 'sensitive_region')
            interfaceBoundarySelectionTags = cell(1, 2);
            interfaceTags = {'capIn', 'capOut'};
            for interfaceIndex = 1:numel(interfaceTags)
                selectionTag = sprintf('sel_mesh_%s_bnd', interfaceTags{interfaceIndex});
                comp.selection.create(selectionTag, 'Adjacent');
                comp.selection(selectionTag).set( ...
                    'input', {['geom1_' interfaceTags{interfaceIndex} '_dom']});
                interfaceBoundarySelectionTags{interfaceIndex} = selectionTag;
            end
        end
    end

    mesh = comp.mesh.create('mesh1');
    hybridSelections = struct();
    if segmentHybridMesh
        hybridSelections = configure_comsol_segment_hybrid_mesh( ...
            comp, mesh, 'geom1', numerics, sweepGeometryTags, ...
            rodBoundarySelectionTags, sweepRodBoundarySelectionTags, ...
            interfaceBoundarySelectionTags);
    else
        workingHmax=numerics.mesh.working_region_maximum_element_size_mm;
        if isempty(workingHmax), workingHmax=NaN; end
        if isfinite(workingHmax) && workingHmax>0
            configure_comsol_mesh(mesh,'geom1',numerics.mesh.global_auto_level,'geom1_workvol_dom',workingHmax);
        else
            configure_comsol_mesh(mesh,'geom1',numerics.mesh.global_auto_level,'',workingHmax);
        end
    end
    meshPrebuildDiagnostics = emit_mesh_prebuild_diagnostics(fid, model, comp, mesh, ...
        segmentHybridMesh, hybridSelections);
    assert(meshPrebuildDiagnostics.vacuum.entity_count > 0 && ...
        strcmp(meshPrebuildDiagnostics.vacuum.volume_status, 'MEASURED') && ...
        isfinite(meshPrebuildDiagnostics.vacuum.volume_mm3) && ...
        meshPrebuildDiagnostics.vacuum.volume_mm3 > 0, ...
        'Finite 3D vacuum selection is empty or has no measurable volume.');
    if segmentHybridMesh
        assert(meshPrebuildDiagnostics.tetrahedral.overlap_domain_count == 0 && ...
            meshPrebuildDiagnostics.tetrahedral.uncovered_vacuum_domain_count == 0 && ...
            meshPrebuildDiagnostics.tetrahedral.extra_domain_count == 0, ...
            'Segment-hybrid vacuum partition coverage differs.');
        assert(meshPrebuildDiagnostics.rod_boundary.entity_count > 0 && ...
            meshPrebuildDiagnostics.rod_boundary.feature_present, ...
            'Segment-hybrid rod-boundary sizing is incomplete.');
        if isfield(meshPrebuildDiagnostics, 'sensitive_region')
            assert(meshPrebuildDiagnostics.sensitive_region.domain_count > 0 && ...
                meshPrebuildDiagnostics.sensitive_region.interface_boundary_entity_count > 0 && ...
                meshPrebuildDiagnostics.sensitive_region.feature_present, ...
                'Localized sensitive-region sizing is incomplete.');
        end
    end
    mesh.run;
    meshInfo = mphmeshstats(model, 'mesh1');
    vacuumMeshInfo = mphmeshstats(model, 'mesh1', 'selection', 'sel_vac');
    meshDiagnostics = emit_mesh_postbuild_diagnostics(fid, model, ...
        meshInfo, vacuumMeshInfo, segmentHybridMesh, hybridSelections, ...
        meshPrebuildDiagnostics);
    emit_mesh_problem_diagnostics(fid, mesh);
    assert(~meshInfo.isempty && ~meshInfo.hasproblems && ...
        ~vacuumMeshInfo.isempty && ~vacuumMeshInfo.hasproblems && ...
        sum(vacuumMeshInfo.numelem) > 0, 'Finite 3D vacuum mesh failed.');
    if ~segmentHybridMesh
        assert(meshInfo.iscomplete, 'Finite 3D free-tetrahedral mesh is incomplete.');
    end
    if segmentHybridMesh
        tetrahedralInfo = meshDiagnostics.tetrahedral;
        assert(~tetrahedralInfo.isempty && ~tetrahedralInfo.hasproblems && ...
            tetrahedralInfo.element_count > 0, ...
            'Segment-hybrid tetrahedral transition coverage failed.');
        for selectionIndex = 1:numel(meshDiagnostics.swept)
            sweptInfo = meshDiagnostics.swept{selectionIndex};
            assert(~sweptInfo.isempty && ~sweptInfo.hasproblems && ...
                sweptInfo.element_count > 0, ...
                'Segment-hybrid swept coverage failed for physical segment %d.', ...
                selectionIndex);
        end
    end
    fprintf(fid,'CHECKPOINT=MESH_COMPLETE\n');
    maximumMeshCellsText = strtrim(getenv('MULTIPOLE_L3_MAXIMUM_MESH_CELLS'));
    if ~isempty(maximumMeshCellsText)
        maximumMeshCells = str2double(maximumMeshCellsText);
        assert(isfinite(maximumMeshCells) && maximumMeshCells > 0 && ...
            maximumMeshCells == floor(maximumMeshCells), ...
            'MULTIPOLE_L3_MAXIMUM_MESH_CELLS must be a positive integer.');
        assert(meshDiagnostics.global.element_count <= maximumMeshCells, ...
            ['COMSOL mesh cell budget exceeded: MESH_GLOBAL_ELEMENTS=%d ' ...
            'maximum_mesh_cells=%d'], ...
            meshDiagnostics.global.element_count, maximumMeshCells);
    end
    if meshBuildOnly
        physicsTags = cell(comp.physics.tags());
        studyTags = cell(model.study.tags());
        solutionTags = cell(model.sol.tags());
        fieldPhysicsCreated = sum(ismember(physicsTags, {'es', 'es_static'}));
        particlePhysicsCreated = sum(strcmp(physicsTags, 'cpt'));
        fieldStudiesCreated = numel(studyTags);
        particleStudiesCreated = numel(studyTags);
        fieldSolutionsCreated = numel(solutionTags);
        fprintf(fid, 'STOP_STAGE=mesh_build\n');
        fprintf(fid, 'FIELD_PHYSICS_CREATED=%d\n', fieldPhysicsCreated);
        fprintf(fid, 'FIELD_STUDIES_CREATED=%d\n', fieldStudiesCreated);
        fprintf(fid, 'FIELD_SOLUTIONS_CREATED=%d\n', fieldSolutionsCreated);
        fprintf(fid, 'PARTICLE_PHYSICS_CREATED=%d\n', particlePhysicsCreated);
        fprintf(fid, 'PARTICLE_STUDIES_CREATED=%d\n', particleStudiesCreated);
        assert(fieldPhysicsCreated == 0 && fieldStudiesCreated == 0 && ...
            fieldSolutionsCreated == 0 && particlePhysicsCreated == 0 && ...
            particleStudiesCreated == 0, ...
            'Mesh-build stop stage created forbidden physics, Study or Solution nodes.');
        fprintf(fid, 'MESH_BUILD_DIAGNOSTIC=PASS\n');
        fprintf(fid, 'STATUS=PASS\n');
        ModelUtil.remove(tag);
        return
    end
    material = model.material.create('mat_vac', 'Common');
    material.selection.named('sel_vac');
    material.propertyGroup('def').set('relpermittivity', {'1'});
    es = comp.physics.create('es', 'Electrostatics', 'geom1');
    es.label('Differential RF/DC unit field');
    es.selection.named('sel_vac');
    es.field('electricpotential').field('Vdiff');
    es.field('electricpotential').component({'Vdiff'});
    actualEsElementOrder=apply_electric_potential_element_order( ...
        es,electricPotentialElementOrder);
    if accelerationEnabled, model.param.set('field_case','1'); end
    for k = 1:numel(rodTags)
        potential = es.create(sprintf('pot_rod%d', k), 'ElectricPotential', 2);
        potential.selection.named(rodBoundarySelectionTags{k});
        differentialVoltage=100*(3-2*rodMetadata(k).electrode_group);
        if accelerationEnabled
            potential.set('V0',sprintf('if(field_case>0.5,%d[V],%.17g[V])', ...
                differentialVoltage,rodMetadata(k).common_mode_V));
        else
            potential.set('V0',sprintf('%d[V]',differentialVoltage));
        end
    end
    for groundIndex = 1:numel(groundTags)
        name = groundTags{groundIndex};
        selection = ['selb_' name];
        comp.selection.create(selection, 'Adjacent');
        comp.selection(selection).set('input', {['geom1_' name '_dom']});
        potential = es.create(['pot_' name], 'ElectricPotential', 2);
        potential.selection.named(selection);
        staticVoltage=static_boundary_voltage(staticElectrodes,rectangularReference,name);
        if accelerationEnabled
            potential.set('V0',sprintf('if(field_case>0.5,0[V],%.17g[V])',staticVoltage));
        else
            potential.set('V0','0[V]');
        end
    end
    if ~accelerationEnabled
        esStatic = comp.physics.create('es_static', 'Electrostatics', 'geom1');
        esStatic.label('Common-mode static field');
        esStatic.selection.named('sel_vac');
        esStatic.field('electricpotential').field('Vstatic');
        esStatic.field('electricpotential').component({'Vstatic'});
        actualEsStaticElementOrder=apply_electric_potential_element_order( ...
            esStatic,electricPotentialElementOrder);
        for k = 1:numel(rodTags)
            potential = esStatic.create(sprintf('pot_rod%d', k), 'ElectricPotential', 2);
            potential.selection.named(rodBoundarySelectionTags{k});
            potential.set('V0', sprintf('%.17g[V]',rodMetadata(k).common_mode_V));
        end
        for groundIndex = 1:numel(groundTags)
            name = groundTags{groundIndex};
            potential = esStatic.create(['pot_' name], 'ElectricPotential', 2);
            potential.selection.named(['selb_' name]);
            staticVoltage=static_boundary_voltage(staticElectrodes,rectangularReference,name);
            potential.set('V0', sprintf('%.17g[V]',staticVoltage));
        end
    end
    if accelerationEnabled
        studyDiff=model.study.create('std_es_diff');
        statDiff=studyDiff.create('stat','Stationary');
        statDiff.setEntry('activate','es',true);
        solutionDiff=model.sol.create('sol_es_diff');
        solutionDiff.study('std_es_diff');
        solutionDiff.createAutoSequence('std_es_diff');
        actualDiffSolver=configure_comsol_stationary_solver( ...
            solutionDiff,stationaryLinearSolverBackend,stationaryIterativeSettings);
        solutionDiff.attach('std_es_diff');
        differentialProgressPath=fullfile(solverProgressDir,'stationary_differential_progress.log');
        run_stationary_solution(solutionDiff,differentialProgressPath);
        differentialInfo=mphsolinfo(model,'soltag','sol_es_diff');
        differentialDof=double(differentialInfo.size);
        differentialSolverEvidence=collect_stationary_solver_evidence( ...
            differentialProgressPath,actualDiffSolver.backend);
        fprintf(fid,'CHECKPOINT=DIFFERENTIAL_FIELD_COMPLETE\n');
        model.param.set('field_case','0');
        studyStatic=model.study.create('std_es_static');
        statStatic=studyStatic.create('stat','Stationary');
        statStatic.setEntry('activate','es',true);
        solutionStatic=model.sol.create('sol_es_static');
        solutionStatic.study('std_es_static');
        solutionStatic.createAutoSequence('std_es_static');
        actualStaticSolver=configure_comsol_stationary_solver( ...
            solutionStatic,stationaryLinearSolverBackend,stationaryIterativeSettings);
        solutionStatic.attach('std_es_static');
        staticProgressPath=fullfile(solverProgressDir,'stationary_static_progress.log');
        run_stationary_solution(solutionStatic,staticProgressPath);
        staticInfo=mphsolinfo(model,'soltag','sol_es_static');
        staticDof=double(staticInfo.size);
        staticSolverEvidence=collect_stationary_solver_evidence( ...
            staticProgressPath,actualStaticSolver.backend);
        model.param.set('field_case','1');
    else
        studyEs = model.study.create('std_es');
        studyEs.create('stat', 'Stationary');
        solutionEs = model.sol.create('sol_es');
        solutionEs.study('std_es');
        solutionEs.createAutoSequence('std_es');
        actualFieldSolver=configure_comsol_stationary_solver( ...
            solutionEs,stationaryLinearSolverBackend,stationaryIterativeSettings);
        solutionEs.attach('std_es');
        fieldProgressPath=fullfile(solverProgressDir,'stationary_field_progress.log');
        run_stationary_solution(solutionEs,fieldProgressPath);
        fieldInfo=mphsolinfo(model,'soltag','sol_es');
        fieldDof=double(fieldInfo.size);
        fieldSolverEvidence=collect_stationary_solver_evidence( ...
            fieldProgressPath,actualFieldSolver.backend);
    end
    fprintf(fid,'CHECKPOINT=STATIONARY_FIELDS_COMPLETE\n');
    fprintf(fid,'ELECTRIC_POTENTIAL_ELEMENT_ORDER=%s\n',upper(actualEsElementOrder));
    if exist('actualEsStaticElementOrder','var')
        assert(strcmp(actualEsStaticElementOrder,electricPotentialElementOrder), ...
            'Static electric-potential element order differs from the governed order.');
    end
    assert(strcmp(actualEsElementOrder,electricPotentialElementOrder), ...
        'Differential electric-potential element order differs from the governed order.');
    if accelerationEnabled
        assert(stationary_solver_configurations_match(actualDiffSolver,actualStaticSolver) && ...
            strcmp(actualDiffSolver.backend,stationaryLinearSolverBackend), ...
            'Acceleration field solvers did not retain the governed backend.');
        actualStationarySolver=actualDiffSolver;
        fprintf(fid,'STATIONARY_LINEAR_SOLVER_BACKEND=%s\n', ...
            upper(actualStationarySolver.backend));
        emit_field_solver_evidence(fid,'DIFFERENTIAL_FIELD',differentialDof, ...
            differentialSolverEvidence);
        emit_field_solver_evidence(fid,'STATIC_FIELD',staticDof,staticSolverEvidence);
    else
        assert(strcmp(actualFieldSolver.backend,stationaryLinearSolverBackend), ...
            'Stationary field solver did not retain the governed backend.');
        actualStationarySolver=actualFieldSolver;
        fprintf(fid,'STATIONARY_LINEAR_SOLVER_BACKEND=%s\n', ...
            upper(actualStationarySolver.backend));
        emit_field_solver_evidence(fid,'STATIONARY_FIELD',fieldDof,fieldSolverEvidence);
    end
    emit_stationary_solver_configuration(fid,actualStationarySolver);

    if fieldSolveOnly
        if accelerationEnabled
            fieldSampleCases = struct( ...
                'case_id', {'differential', 'static'}, ...
                'solution_tag', {'sol_es_diff', 'sol_es_static'}, ...
                'potential_expression', {'Vdiff', 'Vdiff'}, ...
                'Ex_expression', {'es.Ex', 'es.Ex'}, ...
                'Ey_expression', {'es.Ey', 'es.Ey'}, ...
                'Ez_expression', {'es.Ez', 'es.Ez'});
        else
            fieldSampleCases = struct( ...
                'case_id', {'differential', 'static'}, ...
                'solution_tag', {'sol_es', 'sol_es'}, ...
                'potential_expression', {'Vdiff', 'Vstatic'}, ...
                'Ex_expression', {'es.Ex', 'es_static.Ex'}, ...
                'Ey_expression', {'es.Ey', 'es_static.Ey'}, ...
                'Ez_expression', {'es.Ez', 'es_static.Ez'});
        end
        fieldSamples = export_comsol_stationary_field_samples( ...
            model, fieldSamplePointsPath, fieldSamplesPath, fieldSampleCases);
        fieldSamplePointCount = height(fieldSamples)/2;
        assert(fieldSamplePointCount == floor(fieldSamplePointCount) && ...
            fieldSamplePointCount > 0, ...
            'Field-solve sampling produced an invalid paired row count.');
        fprintf(fid,'FIELD_SAMPLE_POINT_COUNT=%d\n',fieldSamplePointCount);
        fprintf(fid,'FIELD_SAMPLE_ROW_COUNT=%d\n',height(fieldSamples));
        fprintf(fid,'CHECKPOINT=STATIONARY_FIELD_SAMPLES_COMPLETE\n');
        physicsTags = cell(comp.physics.tags());
        studyTags = cell(model.study.tags());
        solutionTags = cell(model.sol.tags());
        particlePhysicsCreated = sum(strcmp(physicsTags, 'cpt'));
        if accelerationEnabled
            assert(isfinite(differentialDof) && differentialDof > 0 && ...
                isfinite(staticDof) && staticDof > 0, ...
                'Acceleration field solution sizes are invalid.');
        else
            assert(isfinite(fieldDof) && fieldDof > 0, ...
                'Stationary field solution size is invalid.');
        end
        fprintf(fid,'STOP_STAGE=field_solve\n');
        fprintf(fid,'FIELD_PHYSICS_CREATED=%d\n', ...
            sum(ismember(physicsTags, {'es', 'es_static'})));
        fprintf(fid,'FIELD_STUDIES_CREATED=%d\n',numel(studyTags));
        fprintf(fid,'FIELD_SOLUTIONS_CREATED=%d\n',numel(solutionTags));
        fprintf(fid,'PARTICLE_PHYSICS_CREATED=%d\n',particlePhysicsCreated);
        fprintf(fid,'PARTICLE_STUDIES_CREATED=0\n');
        assert(particlePhysicsCreated == 0, ...
            'Field-solve stop stage created forbidden particle physics.');
        fprintf(fid,'FIELD_SOLVE_DIAGNOSTIC=PASS\n');
        fprintf(fid,'STATUS=PASS\n');
        ModelUtil.remove(tag);
        return
    end

    cpt = comp.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
    cpt.selection.named('sel_vac');
    cpt.feature('pp1').set('mp', 'm_ion');
    cpt.feature('pp1').set('Z', sprintf('%d', design.particle_source.charge_state));
    for index = 1:height(source)
        releaseData = [source.x_mm(index), source.y_mm(index), source.z_mm(index), ...
            source.vx_m_s(index), source.vy_m_s(index), source.vz_m_s(index)];
        releasePath = fullfile(runtimeDir, sprintf('particle_%03d.txt', source.particle_id(index)));
        writematrix(releaseData, releasePath, 'Delimiter', 'tab');
        release = cpt.create(sprintf('rel%03d', index), 'ReleaseFromDataFile', -1);
        release.set('Filename', releasePath);
        release.set('icolp', '0');
        release.set('VelocitySpecification', 'SpecifyVelocity');
        release.set('InitialVelocity', 'FromFile');
        release.set('icolv', '3');
        release.set('rt', sprintf('%.17g[s]', source.birth_time_s(index)));
        release.importData();
    end
    force = cpt.create('ef1', 'ElectricForce', 3);
    force.selection.named('sel_vac');
    force.set('E_src', 'userdef');
    differentialScale = ['((V_dc+rf_scale*V_rf*' rfWaveform ')/100[V])'];
    if accelerationEnabled
        force.set('E', { ...
            [differentialScale '*withsol(''sol_es_diff'',-d(Vdiff,x))+axial_scale*withsol(''sol_es_static'',-d(Vdiff,x))'], ...
            [differentialScale '*withsol(''sol_es_diff'',-d(Vdiff,y))+axial_scale*withsol(''sol_es_static'',-d(Vdiff,y))'], ...
            [differentialScale '*withsol(''sol_es_diff'',-d(Vdiff,z))+axial_scale*withsol(''sol_es_static'',-d(Vdiff,z))']});
    else
        force.set('E', { ...
            [differentialScale '*(-d(Vdiff,x))-axial_scale*d(Vstatic,x)'], ...
            [differentialScale '*(-d(Vdiff,y))-axial_scale*d(Vstatic,y)'], ...
            [differentialScale '*(-d(Vdiff,z))-axial_scale*d(Vstatic,z)']});
    end
    dt = 1/rf.frequency_Hz/numerics.trajectory.rf_steps_per_period;
    timeMaximum = numerics.trajectory.maximum_global_time_us*1e-6;
    if accelerationEnabled, stationarySolutionTag=''; else, stationarySolutionTag='sol_es'; end
    if accelerationEnabled
        if exitAperturePlateAcceleration
            primaryCaseId='exit_aperture_plate_acceleration_rf_on';
            controlCaseId='zero_exit_aperture_plate_drop_rf_on';
        else
            primaryCaseId='axial_acceleration_rf_on';
            controlCaseId='zero_axial_drop_rf_on';
        end
        [pdOn, solutionOn] = solve_particle_case(model, cpt, 'on', 1, 1, dt, timeMaximum,stationarySolutionTag);
        fprintf(fid,'CHECKPOINT=PRIMARY_PARTICLE_CASE_COMPLETE\n');
        [pdZero, solutionZero] = solve_particle_case(model, cpt, 'zero', 1, 0, dt, timeMaximum,stationarySolutionTag);
        fprintf(fid,'CHECKPOINT=CONTROL_PARTICLE_CASE_COMPLETE\n');
    else
        primaryCaseId='finite_3d_rf_on'; controlCaseId='zero_rf_control';
        [pdOn, solutionOn] = solve_particle_case(model, cpt, 'on', 1, 1, dt, timeMaximum,stationarySolutionTag);
        fprintf(fid,'CHECKPOINT=PRIMARY_PARTICLE_CASE_COMPLETE\n');
        [pdZero, solutionZero] = solve_particle_case(model, cpt, 'zero', 0, 1, dt, timeMaximum,stationarySolutionTag);
        fprintf(fid,'CHECKPOINT=CONTROL_PARTICLE_CASE_COMPLETE\n');
    end
    massKg=sourceMetadata.mass_amu*1.66053906660e-27;
    [onMetrics, onEvents, onTrajectories] = analyze_particle_case( ...
        pdOn, source, primaryCaseId, d.census_plane_z, g.working_region_radius, censusRadius, ...
        d.rod_z_min, d.rod_z_max, d.entrance_aperture_plate_downstream_face_z, d.exit_aperture_crossing_plane_z, ...
        g.entrance_interface.aperture_radius_mm, g.exit_interface.aperture_radius_mm,massKg);
    [zeroMetrics, zeroEvents, zeroTrajectories] = analyze_particle_case( ...
        pdZero, source, controlCaseId, d.census_plane_z, g.working_region_radius, censusRadius, ...
        d.rod_z_min, d.rod_z_max, d.entrance_aperture_plate_downstream_face_z, d.exit_aperture_crossing_plane_z, ...
        g.entrance_interface.aperture_radius_mm, g.exit_interface.aperture_radius_mm,massKg);
    events = [onEvents; zeroEvents];
    trajectories = [onTrajectories; zeroTrajectories];
    outputDir = fileparts(eventsPath);
    if ~isfolder(outputDir), mkdir(outputDir); end
    writetable(events, eventsPath);
    writetable(trajectories, trajectoryPath);
    pairedTrajectories = ~isempty(primaryTrajectoryPath) || ~isempty(controlTrajectoryPath);
    assert(~pairedTrajectories || ...
        (~isempty(primaryTrajectoryPath) && ~isempty(controlTrajectoryPath)), ...
        'Paired trajectory outputs must be configured together.');
    if pairedTrajectories
        writetable(onTrajectories, primaryTrajectoryPath);
        writetable(zeroTrajectories, controlTrajectoryPath);
    end
    pairedCanonicalStates = ~isempty(primaryCanonicalStatePath) || ~isempty(controlCanonicalStatePath);
    assert(~pairedCanonicalStates || ...
        (~isempty(primaryCanonicalStatePath) && ~isempty(controlCanonicalStatePath)), ...
        'Paired canonical particle-state outputs must be configured together.');
    if pairedCanonicalStates
        write_canonical_particle_state(pdOn,source,primaryCanonicalStatePath,d.rod_z_max, ...
            d.handoff_plane_z,d.census_plane_z,g.working_region_radius,censusRadius, ...
            massKg,rf.frequency_Hz,rf.phase_rad);
        write_canonical_particle_state(pdZero,source,controlCanonicalStatePath,d.rod_z_max, ...
            d.handoff_plane_z,d.census_plane_z,g.working_region_radius,censusRadius, ...
            massKg,rf.frequency_Hz,rf.phase_rad);
        if ~isempty(canonicalStatePath)
            copyfile(primaryCanonicalStatePath,canonicalStatePath,'f');
        end
    elseif ~isempty(canonicalStatePath)
        write_canonical_particle_state(pdOn,source,canonicalStatePath,d.rod_z_max, ...
            d.handoff_plane_z,d.census_plane_z,g.working_region_radius,censusRadius, ...
            massKg,rf.frequency_Hz,rf.phase_rad);
    end
    improvement = onMetrics.transmission_fraction-zeroMetrics.transmission_fraction;
    checks = struct();
    metrics = struct('schema_version', 1, 'role', 'multipole_finite_3d_transport_metrics', ...
        'status', 'UNRESOLVED', 'project_id', design.identity.project_id, ...
        'model_level', 'L3', 'selected_geometry', selected, ...
        'voltage_contract', rf, ...
        'interface_geometry_mm', struct('entrance_aperture_radius', ...
        g.entrance_interface.aperture_radius_mm, 'exit_aperture_radius', ...
        g.exit_interface.aperture_radius_mm, 'release_plane_z', d.release_plane_z, ...
        'census_plane_z', d.census_plane_z), ...
        'primary_case_id',primaryCaseId,'control_case_id',controlCaseId, ...
        'cases', struct(primaryCaseId, onMetrics, controlCaseId, zeroMetrics), ...
        'rf_minus_zero_transmission', improvement, 'checks', checks, ...
        'axial_drive_topology',axialTopology, ...
        'segmentation_enabled',segmentedRodGeometry, ...
        'segmented_rod_acceleration_enabled',segmentedAccelerationEnabled, ...
        'exit_aperture_plate_acceleration_enabled',exitAperturePlateAcceleration, ...
        'mesh', struct('global_auto_level', numerics.mesh.global_auto_level, ...
        'working_region_hmax_mm', numerics.mesh.working_region_maximum_element_size_mm), ...
        'claim_limit', claimLimit);
    metrics.status = 'UNQUALIFIED';
    metricsFid = fopen(metricsPath, 'w');
    assert(metricsFid >= 0, 'Could not create finite 3D metrics.');
    fprintf(metricsFid, '%s', jsonencode(metrics, 'PrettyPrint', true));
    fclose(metricsFid);
    write_transport_plot(onMetrics, zeroMetrics, onEvents, zeroEvents, ...
        onTrajectories, zeroTrajectories, plotPath, design.identity.project_id, g, d, ...
        primaryCaseId,controlCaseId);
    create_native_plot(model, solutionOn, 'pd_on', 'pg_on', strrep(primaryCaseId,'_',' '));
    create_native_plot(model, solutionZero, 'pd_zero', 'pg_zero', strrep(controlCaseId,'_',' '));
    model.param.set('rf_scale', '1');
    model.save(modelPath);
    delete(fullfile(runtimeDir, 'particle_*.txt'));
    if isfolder(runtimeDir), rmdir(runtimeDir); end
    fprintf(fid, ['ELECTRODE_COUNT=%d\nPRIMARY_TRANSMISSION=%.17g\n' ...
        'CONTROL_TRANSMISSION=%.17g\nMODEL_SAVED=true\nSTATUS=PASS\n'], ...
        electrodeCount, onMetrics.transmission_fraction, zeroMetrics.transmission_fraction);
    ModelUtil.remove(tag);
catch exception
    fprintf(fid, 'STATUS=FAIL\nERROR=%s\n', ...
        getReport(exception, 'extended', 'hyperlinks', 'off'));
    rethrow(exception)
end
clear cleanup

function actualOrder = apply_electric_potential_element_order(physics, requestedOrder)
requestedOrder = lower(char(requestedOrder));
if strcmp(requestedOrder, 'linear')
    orderCode = 1;
elseif strcmp(requestedOrder, 'quadratic')
    orderCode = 2;
else
    error('Unsupported electric-potential element order: %s', requestedOrder);
end
shapeProperty = physics.prop('ShapeProperty');
shapeProperty.set('order_electricpotential', orderCode);
actualCode = str2double(char(shapeProperty.getString('order_electricpotential')));
assert(actualCode == orderCode, ...
    'Electric-potential element order was not retained by COMSOL.');
actualOrder = requestedOrder;
end

function matches = stationary_solver_configurations_match(first, second)
matches = strcmp(first.backend,second.backend) && ...
    strcmp(first.fully_coupled_linsolver,second.fully_coupled_linsolver) && ...
    strcmp(first.control,second.control) && ...
    isequaln(first.relative_tolerance,second.relative_tolerance) && ...
    isequaln(first.maximum_linear_iterations,second.maximum_linear_iterations) && ...
    strcmp(first.linear_error_check,second.linear_error_check) && ...
    strcmp(first.convergence_log,second.convergence_log);
end

function emit_stationary_solver_configuration(fid, actual)
fprintf(fid,'STATIONARY_CONTROL=%s\n',upper(actual.control));
if isfinite(actual.relative_tolerance)
    fprintf(fid,'STATIONARY_RELATIVE_TOLERANCE=%.17g\n',actual.relative_tolerance);
else
    fprintf(fid,'STATIONARY_RELATIVE_TOLERANCE=NOT_APPLICABLE\n');
end
fprintf(fid,'STATIONARY_FULLY_COUPLED_LINEAR_SOLVER=%s\n', ...
    upper(actual.fully_coupled_linsolver));
if isfinite(actual.maximum_linear_iterations)
    fprintf(fid,'STATIONARY_MAX_LINEAR_ITERATIONS=%d\n', ...
        actual.maximum_linear_iterations);
else
    fprintf(fid,'STATIONARY_MAX_LINEAR_ITERATIONS=NOT_APPLICABLE\n');
end
fprintf(fid,'STATIONARY_LINEAR_ERROR_CHECK=%s\n',upper(actual.linear_error_check));
fprintf(fid,'STATIONARY_CONVERGENCE_LOG=%s\n',upper(actual.convergence_log));
end

function run_stationary_solution(solution, progressPath)
com.comsol.model.util.ModelUtil.showProgress(progressPath);
progressCleanup=onCleanup(@() com.comsol.model.util.ModelUtil.showProgress(false));
solution.runAll;
clear progressCleanup
end

function evidence = collect_stationary_solver_evidence(progressPath, actualBackend)
evidence = struct('iteration_count',NaN,'final_residual',NaN, ...
    'source','UNAVAILABLE_FROM_COMSOL_PROGRESS_LOG');
if any(strcmp(actualBackend, {'mumps', 'pardiso'}))
    evidence.source = 'NOT_APPLICABLE_DIRECT_SOLVER';
    return
end
if ~isfile(progressPath), return; end
lines = regexp(fileread(progressPath), '\r?\n', 'split');
for lineIndex = 1:numel(lines)
    columns = regexp(strtrim(lines{lineIndex}), '\s+', 'split');
    iterationColumn=find(strcmpi(columns,'LinIt'),1);
    residualColumn=find(strcmpi(columns,'LinRes'),1);
    if isempty(iterationColumn) || isempty(residualColumn), continue; end
    parsedAny = false;
    for dataIndex = lineIndex+1:numel(lines)
        values = regexp(strtrim(lines{dataIndex}), '\s+', 'split');
        if numel(values) < max(iterationColumn,residualColumn)
            if parsedAny, break; end
            continue
        end
        iterationValue=str2double(values{iterationColumn});
        residualValue=str2double(values{residualColumn});
        if ~isfinite(iterationValue) || iterationValue < 0 || ...
            iterationValue ~= fix(iterationValue) || ...
            ~isfinite(residualValue) || residualValue < 0
            if parsedAny, break; end
            continue
        end
        parsedAny = true;
        evidence.iteration_count = iterationValue;
        evidence.final_residual = residualValue;
        evidence.source = 'COMSOL_PROGRESS_LINIT_LINRES';
    end
end
end

function emit_field_solver_evidence(fid, prefix, dof, evidence)
assert(isfinite(dof) && dof > 0, ...
    '%s solution size is invalid.', lower(strrep(prefix,'_',' ')));
fprintf(fid,'%s_DOF=%d\n',prefix,dof);
if isfinite(evidence.iteration_count)
    fprintf(fid,'%s_ITERATIONS=%d\n',prefix,evidence.iteration_count);
else
    fprintf(fid,'%s_ITERATIONS=UNKNOWN\n',prefix);
end
if isfinite(evidence.final_residual) && evidence.final_residual >= 0
    fprintf(fid,'%s_FINAL_RESIDUAL=%.17g\n',prefix,evidence.final_residual);
else
    fprintf(fid,'%s_FINAL_RESIDUAL=UNKNOWN\n',prefix);
end
fprintf(fid,'%s_SOLVER_EVIDENCE_SOURCE=%s\n',prefix,evidence.source);
end

function diagnostics = emit_mesh_prebuild_diagnostics(fid, model, comp, mesh, ...
    segmentHybridMesh, hybridSelections)
diagnostics = struct();
diagnostics.vacuum = selection_region_diagnostic(model, comp, 'sel_vac');
emit_selection_region(fid, 'MESH_VACUUM', diagnostics.vacuum);
if ~segmentHybridMesh
    fprintf(fid, 'MESH_STRATEGY=selected_region_free_tetrahedral\n');
    return
end

featureTags = cell(mesh.feature.tags());
diagnostics.tetrahedral = selection_region_diagnostic(model, comp, ...
    hybridSelections.tetrahedral);
tetrahedralFeatureTags = cell(mesh.feature('ftet1').feature.tags());
rodBoundarySizeCount = double(any(strcmp(tetrahedralFeatureTags, 'szTetRod')));
localized = isfield(hybridSelections, 'tetrahedral_sensitive');
if localized
    sensitiveSizeCount = double(any(strcmp( ...
        tetrahedralFeatureTags, 'szTetSensitive')));
    sensitiveDomains = selection_entities( ...
        comp, hybridSelections.tetrahedral_sensitive);
else
    sensitiveSizeCount = 0;
    sensitiveDomains = [];
end
diagnostics.rod_boundary = struct( ...
    'entity_count', numel(selection_entities(comp, hybridSelections.rod_boundary)), ...
    'feature_present', false, ...
    'size_feature_count', 0, ...
    'expected_size_feature_count', ...
        (~localized) * (numel(hybridSelections.sweep) + 1));
diagnostics.swept = cell(1, numel(hybridSelections.sweep));
sweptDomains = [];
for index = 1:numel(hybridSelections.sweep)
    diagnostics.swept{index} = selection_region_diagnostic(model, comp, ...
        hybridSelections.sweep{index});
    sweptDomains = union(sweptDomains, diagnostics.swept{index}.entities);
    emit_selection_region(fid, sprintf('MESH_SWEPT_SEGMENT_%d', index), ...
        diagnostics.swept{index});
    sweepFeatureTags = cell(mesh.feature(sprintf('swe%d', index)).feature.tags());
    rodBoundarySizeCount = rodBoundarySizeCount + ...
        double(any(strcmp(sweepFeatureTags, sprintf('szRod%d', index))));
    if localized
        sensitiveSizeCount = sensitiveSizeCount + double(any(strcmp( ...
            sweepFeatureTags, sprintf('szSensitive%d', index))));
        sensitiveDomains = union(sensitiveDomains, selection_entities( ...
            comp, hybridSelections.sweep_sensitive{index}));
    end
end
diagnostics.rod_boundary.size_feature_count = rodBoundarySizeCount;
diagnostics.rod_boundary.feature_present = ...
    rodBoundarySizeCount == diagnostics.rod_boundary.expected_size_feature_count;
if localized
    diagnostics.sensitive_region = struct( ...
        'domain_count', numel(sensitiveDomains), ...
        'interface_boundary_entity_count', numel(selection_entities( ...
            comp, hybridSelections.interface_boundary)), ...
        'size_feature_count', sensitiveSizeCount, ...
        'expected_size_feature_count', numel(hybridSelections.sweep) + 1, ...
        'feature_present', sensitiveSizeCount == ...
            numel(hybridSelections.sweep) + 1);
end

tetrahedralDomains = diagnostics.tetrahedral.entities;
vacuumDomains = diagnostics.vacuum.entities;
diagnostics.tetrahedral.overlap_domain_count = numel(intersect(sweptDomains, tetrahedralDomains));
diagnostics.tetrahedral.uncovered_vacuum_domain_count = numel(setdiff( ...
    vacuumDomains, union(sweptDomains, tetrahedralDomains)));
diagnostics.tetrahedral.extra_domain_count = numel(setdiff( ...
    union(sweptDomains, tetrahedralDomains), vacuumDomains));
fprintf(fid, 'MESH_STRATEGY=physical_segment_hybrid_swept_tetra_v1\n');
fprintf(fid, 'MESH_FEATURE_SWEEP_COUNT=%d\n', sum(cellfun(@(tag) strncmp(tag, 'swe', 3), featureTags)));
fprintf(fid, 'MESH_FEATURE_TETRAHEDRAL_PRESENT=%d\n', any(strcmp(featureTags, 'ftet1')));
fprintf(fid, 'MESH_FEATURE_ROD_BOUNDARY_SIZE_PRESENT=%d\n', diagnostics.rod_boundary.feature_present);
fprintf(fid, 'MESH_FEATURE_ROD_BOUNDARY_SIZE_COUNT=%d\n', diagnostics.rod_boundary.size_feature_count);
fprintf(fid, 'MESH_FEATURE_ROD_BOUNDARY_SIZE_EXPECTED_COUNT=%d\n', diagnostics.rod_boundary.expected_size_feature_count);
fprintf(fid, 'MESH_ROD_BOUNDARY_ENTITY_COUNT=%d\n', diagnostics.rod_boundary.entity_count);
if localized
    fprintf(fid, 'MESH_LOCAL_SENSITIVE_REGION_PRESENT=1\n');
    fprintf(fid, 'MESH_LOCAL_SENSITIVE_DOMAIN_COUNT=%d\n', ...
        diagnostics.sensitive_region.domain_count);
    fprintf(fid, 'MESH_LOCAL_SENSITIVE_INTERFACE_BOUNDARY_ENTITY_COUNT=%d\n', ...
        diagnostics.sensitive_region.interface_boundary_entity_count);
    fprintf(fid, 'MESH_LOCAL_SENSITIVE_SIZE_FEATURE_PRESENT=%d\n', ...
        diagnostics.sensitive_region.feature_present);
    fprintf(fid, 'MESH_LOCAL_SENSITIVE_SIZE_FEATURE_COUNT=%d\n', ...
        diagnostics.sensitive_region.size_feature_count);
end
fprintf(fid, 'MESH_SWEPT_TETRAHEDRAL_OVERLAP_DOMAIN_COUNT=%d\n', diagnostics.tetrahedral.overlap_domain_count);
fprintf(fid, 'MESH_VACUUM_UNCOVERED_DOMAIN_COUNT=%d\n', diagnostics.tetrahedral.uncovered_vacuum_domain_count);
fprintf(fid, 'MESH_NONVACUUM_PARTITION_DOMAIN_COUNT=%d\n', diagnostics.tetrahedral.extra_domain_count);
emit_selection_region(fid, 'MESH_TETRAHEDRAL', diagnostics.tetrahedral);
end

function emit_mesh_problem_diagnostics(fid, mesh)
try
    featureTags = cell(mesh.feature.tags());
    problemCount = 0;
    for featureIndex = 1:numel(featureTags)
        feature = mesh.feature(featureTags{featureIndex});
        problemTags = cell(feature.problems());
        for problemIndex = 1:numel(problemTags)
            problemCount = problemCount + 1;
            message = char(feature.problem(problemTags{problemIndex}).message());
            message = regexprep(message, '[\r\n]+', ' ');
            fprintf(fid, 'MESH_PROBLEM_%d_FEATURE=%s\n', problemCount, ...
                upper(featureTags{featureIndex}));
            fprintf(fid, 'MESH_PROBLEM_%d_MESSAGE=%s\n', problemCount, message);
        end
    end
    fprintf(fid, 'MESH_PROBLEM_DIAGNOSTIC_STATUS=AVAILABLE\n');
    fprintf(fid, 'MESH_PROBLEM_COUNT=%d\n', problemCount);
catch exception
    message = regexprep(exception.message, '[\r\n]+', ' ');
    fprintf(fid, 'MESH_PROBLEM_DIAGNOSTIC_STATUS=UNAVAILABLE\n');
    fprintf(fid, 'MESH_PROBLEM_DIAGNOSTIC_ERROR_ID=%s\n', exception.identifier);
    fprintf(fid, 'MESH_PROBLEM_DIAGNOSTIC_ERROR_MESSAGE=%s\n', message);
end
end

function diagnostics = emit_mesh_postbuild_diagnostics(fid, model, ...
    meshInfo, vacuumMeshInfo, segmentHybridMesh, hybridSelections, prebuild)
diagnostics = prebuild;
diagnostics.global = mesh_info_diagnostic(meshInfo);
diagnostics.vacuum = mesh_region_post_diagnostic(prebuild.vacuum, vacuumMeshInfo);
emit_mesh_info(fid, 'MESH_GLOBAL', diagnostics.global);
emit_mesh_info(fid, 'MESH_VACUUM', diagnostics.vacuum);
if ~segmentHybridMesh
    return
end
diagnostics.tetrahedral = mesh_region_post_diagnostic( ...
    prebuild.tetrahedral, mphmeshstats(model, 'mesh1', ...
    'selection', hybridSelections.tetrahedral));
emit_mesh_info(fid, 'MESH_TETRAHEDRAL', diagnostics.tetrahedral);
for index = 1:numel(hybridSelections.sweep)
    diagnostics.swept{index} = mesh_region_post_diagnostic( ...
        prebuild.swept{index}, mphmeshstats(model, 'mesh1', ...
        'selection', hybridSelections.sweep{index}));
    emit_mesh_info(fid, sprintf('MESH_SWEPT_SEGMENT_%d', index), ...
        diagnostics.swept{index});
end
end

function diagnostic = selection_region_diagnostic(model, comp, selectionTag)
diagnostic = struct();
diagnostic.entities = selection_entities(comp, selectionTag);
diagnostic.entity_count = numel(diagnostic.entities);
[diagnostic.volume_mm3, diagnostic.volume_status] = ...
    selection_volume_mm3(model, diagnostic.entities);
end

function diagnostic = mesh_region_post_diagnostic(selectionDiagnostic, info)
diagnostic = selectionDiagnostic;
meshDiagnostic = mesh_info_diagnostic(info);
fields = fieldnames(meshDiagnostic);
for index = 1:numel(fields)
    diagnostic.(fields{index}) = meshDiagnostic.(fields{index});
end
end

function diagnostic = mesh_info_diagnostic(info)
diagnostic = struct( ...
    'isempty', logical(info.isempty), ...
    'iscomplete', logical(info.iscomplete), ...
    'hasproblems', logical(info.hasproblems), ...
    'element_count', sum(info.numelem), ...
    'minimum_quality', mesh_info_scalar(info, 'minquality'), ...
    'mean_quality', mesh_info_scalar(info, 'meanquality'));
end

function emit_mesh_info(fid, prefix, diagnostic)
fprintf(fid, '%s_EMPTY=%d\n', prefix, diagnostic.isempty);
fprintf(fid, '%s_COMPLETE=%d\n', prefix, diagnostic.iscomplete);
fprintf(fid, '%s_HAS_PROBLEMS=%d\n', prefix, diagnostic.hasproblems);
fprintf(fid, '%s_ELEMENTS=%d\n', prefix, diagnostic.element_count);
fprintf(fid, '%s_MIN_QUALITY=%.17g\n', prefix, diagnostic.minimum_quality);
fprintf(fid, '%s_MEAN_QUALITY=%.17g\n', prefix, diagnostic.mean_quality);
end

function emit_selection_region(fid, prefix, diagnostic)
fprintf(fid, '%s_SELECTION_ENTITY_COUNT=%d\n', prefix, diagnostic.entity_count);
fprintf(fid, '%s_VOLUME_STATUS=%s\n', prefix, diagnostic.volume_status);
if strcmp(diagnostic.volume_status, 'MEASURED')
    fprintf(fid, '%s_VOLUME_MM3=%.17g\n', prefix, diagnostic.volume_mm3);
else
    fprintf(fid, '%s_VOLUME_MM3=UNKNOWN\n', prefix);
end
end

function entities = selection_entities(comp, selectionTag)
entities = double(comp.selection(selectionTag).entities());
entities = unique(entities(:)');
end

function [volume, status] = selection_volume_mm3(model, entities)
volume = [];
status = 'UNKNOWN';
try
    measurements = double(mphmeasure( ...
        model, 'geom1', 'domain', 'selection', entities));
    measuredVolume = sum(measurements(:));
    if isscalar(measuredVolume) && isfinite(measuredVolume) && measuredVolume >= 0
        volume = measuredVolume;
        status = 'MEASURED';
    end
catch
    % Selection diagnostics must emit UNKNOWN and fail closed when the
    % geometry-domain measure is unavailable.
end
end

function value = mesh_info_scalar(info, field)
if isfield(info, field)
    value = double(info.(field));
else
    value = NaN;
end
end

function [pd, solutionTag] = solve_particle_case(model, cpt, label, rfScale, axialScale, dt, timeMaximum,stationarySolutionTag)
studyTag = ['std_' label];
stepTag = ['time_' label];
solutionTag = ['sol_' label];
model.param.set('rf_scale', sprintf('%d', rfScale));
model.param.set('axial_scale', sprintf('%d', axialScale));
study = model.study.create(studyTag);
time = study.create(stepTag, 'Transient');
time.set('tlist', sprintf('range(0,%.17g,%.17g)', dt, timeMaximum));
time.setEntry('activate', 'es', false);
physicsTags=cell(model.component('comp1').physics.tags());
if any(strcmp(physicsTags,'es_static'))
    time.setEntry('activate', 'es_static', false);
end
time.setEntry('activate', 'cpt', true);
featureTags = cell(cpt.feature.tags());
releaseTags = featureTags(startsWith(featureTags, 'rel'));
for index = 1:numel(releaseTags)
    cpt.feature(releaseTags{index}).set('StudyStep', [studyTag '/' stepTag]);
end
cpt.feature('pp1').set('StudyStep', [studyTag '/' stepTag]);
solution = model.sol.create(solutionTag);
solution.study(studyTag);
solution.createAutoSequence(studyTag);
if ~isempty(stationarySolutionTag)
    solution.feature('v1').set('notsolmethod', 'sol');
    solution.feature('v1').set('notsol', stationarySolutionTag);
end
solution.attach(studyTag);
solution.runAll;
datasetTag = ['pd_' label '_temp'];
dataset = model.result.dataset.create(datasetTag, 'Particle');
dataset.set('solution', solutionTag);
pd = mphparticle(model, 'dataset', datasetTag);
model.result.dataset.remove(datasetTag);
end

function [metrics, events, trajectories] = analyze_particle_case(pd, source, caseId, ...
    censusPlaneZ, usableRadius, censusRadius, rodZMin, rodZMax, entranceCrossingZ, exitCrossingZ, ...
    entranceApertureRadius, exitApertureRadius,massKg)
if ismatrix(pd.p) && size(pd.p,2)==3
    x=pd.p(:,1); y=pd.p(:,2); z=pd.p(:,3);
    vx=pd.v(:,1); vy=pd.v(:,2); vz=pd.v(:,3);
else
    x=squeeze(pd.p(:,:,1)); y=squeeze(pd.p(:,:,2)); z=squeeze(pd.p(:,:,3));
    vx=squeeze(pd.v(:,:,1)); vy=squeeze(pd.v(:,:,2)); vz=squeeze(pd.v(:,:,3));
end
if isvector(x), x = x(:); y = y(:); z = z(:); end
radius = sqrt(x.^2+y.^2);
particleCount = size(z,2);
eventRows = cell(particleCount, 13);
trajectoryRows = cell(0, 7);
transmitted = false(1, particleCount);
exitRadii = nan(1, particleCount);
maximumRodRadius = nan(1, particleCount);
entranceRadii = nan(1, particleCount);
exitRadiiAtPlate = nan(1, particleCount);
outputEnergyEv=nan(1,particleCount);
for particle = 1:particleCount
    valid = find(isfinite(x(:,particle)) & isfinite(y(:,particle)) & isfinite(z(:,particle)));
    assert(~isempty(valid), 'A finite 3D particle has no trajectory samples.');
    rodSamples = valid(z(valid,particle) >= rodZMin & z(valid,particle) <= rodZMax);
    if isempty(rodSamples)
        maximumRodRadius(particle) = radius(valid(1),particle);
    else
        maximumRodRadius(particle) = max(radius(rodSamples,particle));
    end
    crossing = valid(find(z(valid,particle) >= censusPlaneZ, 1, 'first'));
    entranceCrossing = valid(find(z(valid,particle) >= entranceCrossingZ, 1, 'first'));
    exitCrossing = valid(find(z(valid,particle) >= exitCrossingZ, 1, 'first'));
    if ~isempty(entranceCrossing), entranceRadii(particle) = radius(entranceCrossing,particle); end
    if ~isempty(exitCrossing), exitRadiiAtPlate(particle) = radius(exitCrossing,particle); end
    if ~isempty(crossing) && maximumRodRadius(particle) < usableRadius && ...
            radius(crossing,particle) <= censusRadius
        transmitted(particle) = true;
        reason = 'near_interface_census_plane';
        terminal = crossing;
        exitRadii(particle) = radius(crossing,particle);
        outputEnergyEv(particle)=0.5*massKg*(vx(crossing,particle)^2+ ...
            vy(crossing,particle)^2+vz(crossing,particle)^2)/1.602176634e-19;
    else
        terminal = valid(end);
        if isempty(entranceCrossing) || entranceRadii(particle) > entranceApertureRadius
            reason = 'entrance_aperture_loss';
        elseif maximumRodRadius(particle) >= usableRadius
            reason = 'usable_radius_exceeded';
        elseif isempty(exitCrossing) || exitRadiiAtPlate(particle) > exitApertureRadius
            reason = 'exit_aperture_loss';
        else
            reason = 'external_region_or_timeout';
        end
    end
    status = 'lost'; if transmitted(particle), status = 'transmitted'; end
    eventRows(particle,:) = {caseId, source.particle_id(particle), status, reason, ...
        source.birth_time_s(particle), pd.t(terminal), x(terminal,particle), ...
        y(terminal,particle), z(terminal,particle), radius(terminal,particle), ...
        maximumRodRadius(particle), entranceRadii(particle), exitRadiiAtPlate(particle)};
    sampled = unique([valid(1:20:end); valid(end)]);
    for sample = sampled'
        trajectoryRows(end+1,:) = {caseId, source.particle_id(particle), pd.t(sample), ...
            x(sample,particle), y(sample,particle), z(sample,particle), radius(sample,particle)}; %#ok<AGROW>
    end
end

events = cell2table(eventRows, 'VariableNames', {'case_id','particle_id','status','terminal_reason', ...
    'birth_time_s','terminal_time_s','terminal_x_mm','terminal_y_mm','terminal_z_mm', ...
    'terminal_radius_mm','maximum_rod_radius_mm','entrance_aperture_radius_mm', ...
    'exit_aperture_radius_mm'});
trajectories = cell2table(trajectoryRows, 'VariableNames', {'case_id','particle_id', ...
    'time_s','x_mm','y_mm','z_mm','radius_mm'});
metrics = struct('particles', particleCount, 'transmitted', sum(transmitted), ...
    'transmission_fraction', mean(transmitted), ...
    'entrance_passed', sum(isfinite(entranceRadii) & entranceRadii <= entranceApertureRadius), ...
    'exit_passed', sum(isfinite(exitRadiiAtPlate) & exitRadiiAtPlate <= exitApertureRadius), ...
    'exit_rms_radius_mm', sqrt(mean(exitRadii(transmitted).^2)), ...
    'mean_output_energy_eV',mean(outputEnergyEv(transmitted)), ...
    'output_energy_standard_deviation_eV',std(outputEnergyEv(transmitted)), ...
    'maximum_rod_radius_mm', max(maximumRodRadius));
end

function create_rectangular_reference_enclosure(geom,enclosure,g,d,physicalDetectorRadius)
outer=enclosure.outer_half_width_mm;
entranceThickness=d.entrance_aperture_plate_downstream_face_z-d.entrance_aperture_plate_upstream_face_z;
geom.feature.create('ent_outer','Block');
geom.feature('ent_outer').set('size',{sprintf('%.17g[mm]',2*outer),sprintf('%.17g[mm]',2*outer),sprintf('%.17g[mm]',entranceThickness)});
geom.feature('ent_outer').set('pos',{sprintf('%.17g[mm]',-outer),sprintf('%.17g[mm]',-outer),sprintf('%.17g[mm]',d.entrance_aperture_plate_upstream_face_z)});
geom.feature.create('ent_hole','Cylinder'); geom.feature('ent_hole').set('r',sprintf('%.17g[mm]',g.entrance_interface.aperture_radius_mm));
geom.feature('ent_hole').set('h',sprintf('%.17g[mm]',entranceThickness)); geom.feature('ent_hole').set('pos',{'0','0',sprintf('%.17g[mm]',d.entrance_aperture_plate_upstream_face_z)});
geom.feature.create('entrance','Difference'); geom.feature('entrance').selection('input').set({'ent_outer'}); geom.feature('entrance').selection('input2').set({'ent_hole'}); geom.feature('entrance').set('selresult','on');
exitHeight=enclosure.exit_enclosure_z_max_mm-enclosure.exit_enclosure_z_min_mm;
geom.feature.create('exit_outer','Block'); geom.feature('exit_outer').set('size',{sprintf('%.17g[mm]',2*outer),sprintf('%.17g[mm]',2*outer),sprintf('%.17g[mm]',exitHeight)});
geom.feature('exit_outer').set('pos',{sprintf('%.17g[mm]',-outer),sprintf('%.17g[mm]',-outer),sprintf('%.17g[mm]',enclosure.exit_enclosure_z_min_mm)});
inner=enclosure.inner_half_width_mm; innerHeight=enclosure.exit_enclosure_z_max_mm-enclosure.exit_front_wall_end_z_mm;
geom.feature.create('exit_inner','Block'); geom.feature('exit_inner').set('size',{sprintf('%.17g[mm]',2*inner),sprintf('%.17g[mm]',2*inner),sprintf('%.17g[mm]',innerHeight)});
geom.feature('exit_inner').set('pos',{sprintf('%.17g[mm]',-inner),sprintf('%.17g[mm]',-inner),sprintf('%.17g[mm]',enclosure.exit_front_wall_end_z_mm)});
geom.feature.create('exit_hole','Cylinder'); geom.feature('exit_hole').set('r',sprintf('%.17g[mm]',g.exit_interface.aperture_radius_mm));
geom.feature('exit_hole').set('h',sprintf('%.17g[mm]',exitHeight)); geom.feature('exit_hole').set('pos',{'0','0',sprintf('%.17g[mm]',enclosure.exit_enclosure_z_min_mm)});
geom.feature.create('exit_enclosure','Difference'); geom.feature('exit_enclosure').selection('input').set({'exit_outer'}); geom.feature('exit_enclosure').selection('input2').set({'exit_inner','exit_hole'}); geom.feature('exit_enclosure').set('selresult','on');
geom.feature.create('physical_detector','Cylinder'); geom.feature('physical_detector').set('r',sprintf('%.17g[mm]',physicalDetectorRadius));
geom.feature('physical_detector').set('h',sprintf('%.17g[mm]',enclosure.physical_detector_thickness_mm)); geom.feature('physical_detector').set('pos',{'0','0',sprintf('%.17g[mm]',d.census_plane_z)}); geom.feature('physical_detector').set('selresult','on');
end

function write_canonical_particle_state(pd,source,path,rodExitZ,handoffZ,censusPlaneZ, ...
    usableRadius,censusRadius,massKg,frequencyHz,phaseRad)
[x,y,z,vx,vy,vz]=particle_arrays(pd);
radius=sqrt(x.^2+y.^2); rows=cell(0,17);
for particle=1:size(z,2)
    valid=find(isfinite(x(:,particle))&isfinite(y(:,particle))&isfinite(z(:,particle)));
    rodSamples=valid(z(valid,particle)>=min(source.z_mm(particle),rodExitZ)&z(valid,particle)<=rodExitZ);
    if isempty(rodSamples), maxRodRadius=radius(valid(1),particle); else, maxRodRadius=max(radius(rodSamples,particle)); end
    sourceState=struct('t_s',source.birth_time_s(particle),'x_mm',source.x_mm(particle), ...
        'y_mm',source.y_mm(particle),'z_mm',source.z_mm(particle),'vx_m_s',source.vx_m_s(particle), ...
        'vy_m_s',source.vy_m_s(particle),'vz_m_s',source.vz_m_s(particle));
    rows(end+1,:)=canonical_state_row(source.particle_id(particle),'source','alive','none', ...
        sourceState,source.birth_time_s(particle),frequencyHz,phaseRad,massKg,maxRodRadius); %#ok<AGROW>
    [rodState,rodFound]=interpolate_particle_plane(pd.t,x(:,particle),y(:,particle),z(:,particle), ...
        vx(:,particle),vy(:,particle),vz(:,particle),rodExitZ);
    if rodFound
        rows(end+1,:)=canonical_state_row(source.particle_id(particle),'rod_exit','alive','none', ...
            rodState,source.birth_time_s(particle),frequencyHz,phaseRad,massKg,maxRodRadius); %#ok<AGROW>
    end
    [handoffState,handoffFound]=interpolate_particle_plane(pd.t,x(:,particle),y(:,particle),z(:,particle), ...
        vx(:,particle),vy(:,particle),vz(:,particle),handoffZ);
    if handoffFound
        rows(end+1,:)=canonical_state_row(source.particle_id(particle),'handoff','transmitted','none', ...
            handoffState,source.birth_time_s(particle),frequencyHz,phaseRad,massKg,maxRodRadius); %#ok<AGROW>
    end
    crossing=valid(find(z(valid,particle)>=censusPlaneZ,1,'first')); terminal=valid(end);
    status='lost'; reason='electrode';
    if ~isempty(crossing)&&radius(crossing,particle)<=censusRadius&&maxRodRadius<usableRadius
        terminal=crossing;status='transmitted';reason='acceptance_surface';
    elseif z(terminal,particle)<source.z_mm(particle),reason='backward_escape';
    end
    terminalState=struct('t_s',pd.t(terminal),'x_mm',x(terminal,particle),'y_mm',y(terminal,particle), ...
        'z_mm',z(terminal,particle),'vx_m_s',vx(terminal,particle),'vy_m_s',vy(terminal,particle), ...
        'vz_m_s',vz(terminal,particle));
    rows(end+1,:)=canonical_state_row(source.particle_id(particle),'terminal',status,reason, ...
        terminalState,source.birth_time_s(particle),frequencyHz,phaseRad,massKg,maxRodRadius); %#ok<AGROW>
end
names={'particle_id','event','status','terminal_reason','time_us','elapsed_time_us','rf_phase_rad', ...
    'axial_z_mm','transverse_x_mm','transverse_y_mm','velocity_axial_m_s','velocity_x_m_s', ...
    'velocity_y_m_s','kinetic_energy_eV','radial_position_mm','divergence_angle_deg','max_rod_radius_mm'};
writetable(cell2table(rows,'VariableNames',names),path);
end

function row=canonical_state_row(particleId,event,status,reason,state,birthTime,frequencyHz,phaseRad,massKg,maxRodRadius)
speedSquared=state.vx_m_s^2+state.vy_m_s^2+state.vz_m_s^2;
energyEv=0.5*massKg*speedSquared/1.602176634e-19;
row={particleId,event,status,reason,state.t_s*1e6,(state.t_s-birthTime)*1e6, ...
    mod(2*pi*frequencyHz*state.t_s+phaseRad,2*pi),state.z_mm,state.x_mm,state.y_mm, ...
    state.vz_m_s,state.vx_m_s,state.vy_m_s,energyEv,hypot(state.x_mm,state.y_mm), ...
    atan2d(hypot(state.vx_m_s,state.vy_m_s),state.vz_m_s),maxRodRadius};
end

function [state,found]=interpolate_particle_plane(time,x,y,z,vx,vy,vz,planeZ)
state=struct();found=false;valid=find(isfinite(x)&isfinite(y)&isfinite(z)&isfinite(vx)&isfinite(vy)&isfinite(vz));
for index=2:numel(valid)
    left=valid(index-1);right=valid(index);
    if z(left)<planeZ&&z(right)>=planeZ&&z(right)>z(left)
        fraction=(planeZ-z(left))/(z(right)-z(left));lerp=@(a,b)a+fraction*(b-a);
        state=struct('t_s',lerp(time(left),time(right)),'x_mm',lerp(x(left),x(right)), ...
            'y_mm',lerp(y(left),y(right)),'z_mm',planeZ,'vx_m_s',lerp(vx(left),vx(right)), ...
            'vy_m_s',lerp(vy(left),vy(right)),'vz_m_s',lerp(vz(left),vz(right)));
        found=true;return
    end
end
end

function [x,y,z,vx,vy,vz]=particle_arrays(pd)
if ismatrix(pd.p)&&size(pd.p,2)==3
    x=pd.p(:,1);y=pd.p(:,2);z=pd.p(:,3);vx=pd.v(:,1);vy=pd.v(:,2);vz=pd.v(:,3);
else
    x=squeeze(pd.p(:,:,1));y=squeeze(pd.p(:,:,2));z=squeeze(pd.p(:,:,3));
    vx=squeeze(pd.v(:,:,1));vy=squeeze(pd.v(:,:,2));vz=squeeze(pd.v(:,:,3));
end
if isvector(x),x=x(:);y=y(:);z=z(:);vx=vx(:);vy=vy(:);vz=vz(:);end
end

function write_transport_plot(onMetrics, zeroMetrics, onEvents, zeroEvents, ...
    onTrajectories, zeroTrajectories, path, projectId, geometry, derived,primaryCaseId,controlCaseId)
figureHandle = figure('Visible', 'off', 'Position', [100 100 1000 420], 'Color', 'w');
tiledlayout(1,2);
nexttile; hold on;
set(gca,'Color','w','XColor','k','YColor','k');
controlTrajectoryHandle=plot(zeroTrajectories.z_mm, zeroTrajectories.radius_mm, '.', ...
    'Color', [0.72 0.72 0.72], 'MarkerSize', 2);
primaryTrajectoryHandle=plot(onTrajectories.z_mm, onTrajectories.radius_mm, 'x', ...
    'Color', [0 0.447 0.698], 'MarkerSize', 2);
yLimit = geometry.working_region_radius*1.15;
draw_interface_plate(derived.entrance_aperture_plate_upstream_face_z, derived.entrance_aperture_plate_downstream_face_z, ...
    geometry.entrance_interface.aperture_radius_mm, yLimit);
draw_interface_plate(derived.exit_aperture_plate_upstream_face_z, derived.exit_aperture_plate_downstream_face_z, ...
    geometry.exit_interface.aperture_radius_mm, yLimit);
xlabel('z (mm)'); ylabel('Radius (mm)'); ylim([0 yLimit]);
trajectoryLegend=legend([controlTrajectoryHandle primaryTrajectoryHandle], ...
    {strrep(controlCaseId,'_',' '),strrep(primaryCaseId,'_',' ')},'Location','best');
set(trajectoryLegend,'Color','w','TextColor','k','EdgeColor',[0.3 0.3 0.3]);
title(sprintf('Transmission: primary %.0f%%, control %.0f%%', ...
    100*onMetrics.transmission_fraction, 100*zeroMetrics.transmission_fraction));
nexttile; hold on;
set(gca,'Color','w','XColor','k','YColor','k');
scatter(zeroEvents.terminal_x_mm, zeroEvents.terminal_y_mm, 14, [0.55 0.55 0.55], 'filled');
scatter(onEvents.terminal_x_mm, onEvents.terminal_y_mm, 18, [0 0.447 0.698], 'x');
axis equal; xlabel('Terminal x (mm)'); ylabel('Terminal y (mm)');
theta = linspace(0,2*pi,200);
plot(geometry.exit_interface.aperture_radius_mm*cos(theta), ...
    geometry.exit_interface.aperture_radius_mm*sin(theta), 'k--', 'LineWidth', 0.8, ...
    'HandleVisibility', 'off');
legendHandle=legend({strrep(controlCaseId,'_',' '),strrep(primaryCaseId,'_',' ')}, ...
    'Location', 'best');
set(legendHandle,'Color','w','TextColor','k','EdgeColor',[0.3 0.3 0.3]);
title('Terminal transverse states');
superTitle=sgtitle([strrep(projectId,'_','\_') ' — finite 3D L3']);
set(superTitle,'Color','k');
set(findall(figureHandle,'Type','text'),'Color','k');
set(figureHandle,'PaperPositionMode','auto');
print(figureHandle, path, '-dpng', '-r180'); close(figureHandle);
end

function create_native_plot(model, solutionTag, datasetTag, plotTag, label)
dataset = model.result.dataset.create(datasetTag, 'Particle');
dataset.set('solution', solutionTag);
plotGroup = model.result.create(plotTag, 'PlotGroup3D');
plotGroup.label(label); plotGroup.set('data', datasetTag);
plotGroup.create('traj', 'ParticleTrajectories'); plotGroup.run;
end

function draw_interface_plate(zMin, zMax, apertureRadius, yLimit)
patch([zMin zMax zMax zMin], [apertureRadius apertureRadius yLimit yLimit], ...
    [0.45 0.45 0.45], 'FaceAlpha', 0.35, 'EdgeColor', 'none', ...
    'HandleVisibility', 'off');
end

function voltage = static_boundary_voltage(contract, rectangularReference, name)
if rectangularReference
    assert(strcmp(contract.role,'rectangular_reference_static_electrodes'), ...
        'Static-electrode contract differs from the rectangular enclosure.');
    if any(strcmp(name,{'entrance','connIn'}))
        voltage=contract.entrance_aperture_plate_and_connector_V;
    elseif any(strcmp(name,{'exit_enclosure','connOut'}))
        voltage=contract.exit_outer_enclosure_and_connector_V;
    elseif strcmp(name,'physical_detector')
        voltage=contract.physical_detector_V;
    else
        error('No canonical static voltage for rectangular boundary %s.',name);
    end
else
    assert(strcmp(contract.role,'cylindrical_shield_static_electrodes'), ...
        'Static-electrode contract differs from the cylindrical enclosure.');
    if any(strcmp(name,{'shield','outerIn','capIn','connIn'}))
        voltage=contract.shield_entrance_outer_endcap_aperture_plate_connector_V;
    elseif any(strcmp(name,{'outerOut','capOut','connOut'}))
        voltage=contract.exit_outer_endcap_aperture_plate_connector_V;
    else
        error('No canonical static voltage for cylindrical boundary %s.',name);
    end
end
end
