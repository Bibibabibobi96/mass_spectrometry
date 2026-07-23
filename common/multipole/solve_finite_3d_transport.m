% Solve finite 3D circular-rod fields and direct RF/zero-RF particle transport.

addpath(fileparts(mfilename('fullpath')));
addpath(fullfile(fileparts(mfilename('fullpath')),'..','comsol'));

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
baselinePath = getenv('MULTIPOLE_L3_BASELINE');
familyOperatingPath = getenv('MULTIPOLE_L3_FAMILY_OPERATING');
contractPath = getenv('MULTIPOLE_L3_CONTRACT');
fieldMetricsPath = getenv('MULTIPOLE_L3_FIELD_METRICS');
roundRodGeometryPath = getenv('MULTIPOLE_L3_ROUND_ROD_GEOMETRY');
axialAccelerationPath = getenv('MULTIPOLE_L3_AXIAL_ACCELERATION');
endplateAccelerationPath = getenv('MULTIPOLE_L3_ENDPLATE_ACCELERATION');
sourcePath = getenv('MULTIPOLE_L3_PARTICLE_SOURCE');
runtimeDir = getenv('MULTIPOLE_L3_RUNTIME_DIR');
eventsPath = getenv('MULTIPOLE_L3_EVENTS');
trajectoryPath = getenv('MULTIPOLE_L3_TRAJECTORIES');
metricsPath = getenv('MULTIPOLE_L3_METRICS');
plotPath = getenv('MULTIPOLE_L3_PLOT');
modelPath = getenv('MULTIPOLE_L3_MODEL');
canonicalStatePath = getenv('MULTIPOLE_L3_CANONICAL_STATE');
required = {reportPath, baselinePath, familyOperatingPath, contractPath, fieldMetricsPath, roundRodGeometryPath, sourcePath, ...
    runtimeDir, eventsPath, trajectoryPath, metricsPath, plotPath, modelPath};
assert(all(~cellfun(@isempty, required)), 'Finite 3D multipole environment is incomplete.');
assert(isfile(baselinePath) && isfile(familyOperatingPath) && isfile(contractPath) && isfile(fieldMetricsPath) && isfile(roundRodGeometryPath) && ...
    isfile(sourcePath), 'Finite 3D multipole inputs are missing.');
if ~isfolder(runtimeDir), mkdir(runtimeDir); end

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not create the finite 3D transport report.');
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, 'TASK=MULTIPOLE_FINITE_3D_TRANSPORT\n');

try
    baseline = jsondecode(fileread(baselinePath));
    familyOperating = jsondecode(fileread(familyOperatingPath));
    contract = jsondecode(fileread(contractPath));
    fieldMetrics = jsondecode(fileread(fieldMetricsPath));
    roundRodGeometry = jsondecode(fileread(roundRodGeometryPath));
    axialAccelerationEnabled = ~isempty(axialAccelerationPath);
    endplateAccelerationEnabled = ~isempty(endplateAccelerationPath);
    assert(~(axialAccelerationEnabled && endplateAccelerationEnabled), ...
        'Only one multipole acceleration mode may be enabled.');
    accelerationEnabled = axialAccelerationEnabled || endplateAccelerationEnabled;
    if axialAccelerationEnabled
        assert(isfile(axialAccelerationPath), 'Resolved axial-acceleration contract is missing.');
        axialAcceleration = jsondecode(fileread(axialAccelerationPath));
        assert(strcmp(axialAcceleration.role,'multipole_axial_acceleration_resolved_contract') && ...
            strcmp(axialAcceleration.project_id,contract.project_id), ...
            'Axial-acceleration contract identity differs.');
    else
        axialAcceleration = struct();
    end
    if endplateAccelerationEnabled
        assert(isfile(endplateAccelerationPath), 'Resolved endplate-acceleration contract is missing.');
        endplateAcceleration=jsondecode(fileread(endplateAccelerationPath));
        assert(strcmp(endplateAcceleration.role,'multipole_endplate_acceleration_resolved_contract') && ...
            strcmp(endplateAcceleration.project_id,contract.project_id), ...
            'Endplate-acceleration contract identity differs.');
    else
        endplateAcceleration=struct();
    end
    if axialAccelerationEnabled
        acceleration=axialAcceleration;
    elseif endplateAccelerationEnabled
        acceleration=endplateAcceleration;
    else
        acceleration=struct();
    end
    if accelerationEnabled, claimLimit=acceleration.claim_limit; else, claimLimit=contract.claim_limit; end
    source = readtable(sourcePath);
    n = familyOperating.identity.radial_order_n;
    electrodeCount = familyOperating.identity.electrode_count;
    assert(electrodeCount == 2*n && electrodeCount == baseline.multipole.electrode_count, ...
        'Finite 3D multipole identities differ.');
    selected = fieldMetrics.selected_candidate;
    r0 = familyOperating.geometry_mm.r0;
    rodArray = roundRodGeometry.array_mm;
    rods = rodArray.rods;
    assert(roundRodGeometry.identity.electrode_count == electrodeCount && numel(rods) == electrodeCount, ...
        'Shared round-rod geometry identity differs from the operating contract.');
    assert(abs(rodArray.rod_radius-selected.rod_radius_mm) < 1e-12 && ...
        abs(rodArray.rod_center_radius-selected.rod_center_radius_mm) < 1e-12, ...
        'Shared round-rod geometry differs from the selected field-screen candidate.');
    g = contract.geometry_mm;
    d = contract.derived_geometry_mm;
    geometryModel = 'cylindrical_grounded_shield_v1';
    if isfield(contract,'geometry_model'), geometryModel=contract.geometry_model; end
    rectangularReference = strcmp(geometryModel,'rectangular_reference_enclosure_v1');
    assert(rectangularReference || strcmp(geometryModel,'cylindrical_grounded_shield_v1'), ...
        'Unsupported shared finite-3D geometry model.');
    detectorRadius=g.working_region_radius;
    if isfield(g,'detector_radius_mm'), detectorRadius=g.detector_radius_mm; end
    assert(abs(d.rod_length-familyOperating.geometry_mm.effective_length) < 1e-12, ...
        'Finite 3D rod length differs from the baseline.');
    assert(all(abs(source.z_mm-d.source_z) < 1e-12), 'Particle source plane differs from the L3 contract.');
    rf = familyOperating.voltage;
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
    model.param.set('m_ion', sprintf('%.17g[kg]', baseline.particle_source.mass_amu*1.66053906660e-27));
    comp = model.component.create('comp1', true);
    geom = comp.geom.create('geom1', 3);
    geom.lengthUnit('mm');
    vacuumHeight = d.vacuum_z_max-d.vacuum_z_min;
    if rectangularReference
        enclosure=g.reference_enclosure;
        shieldOuter=enclosure.outer_half_width_mm;
        geom.feature.create('vac', 'Block');
        geom.feature('vac').set('size',{sprintf('%.17g[mm]',2*shieldOuter), ...
            sprintf('%.17g[mm]',2*shieldOuter),sprintf('%.17g[mm]',vacuumHeight)});
        geom.feature('vac').set('pos',{sprintf('%.17g[mm]',-shieldOuter), ...
            sprintf('%.17g[mm]',-shieldOuter),sprintf('%.17g[mm]',d.vacuum_z_min)});
    else
        shieldOuter = d.shield_outer_radius;
        geom.feature.create('vac', 'Cylinder');
        geom.feature('vac').set('r', sprintf('%.17g[mm]', g.grounded_shield_inner_radius));
        geom.feature('vac').set('h', sprintf('%.17g[mm]', vacuumHeight));
        geom.feature('vac').set('pos', {'0','0',sprintf('%.17g[mm]', d.vacuum_z_min)});
    end
    geom.feature('vac').set('selresult', 'on');
    geom.feature.create('workvol', 'Cylinder');
    geom.feature('workvol').set('r', sprintf('%.17g[mm]', g.working_region_radius));
    geom.feature('workvol').set('h', sprintf('%.17g[mm]', vacuumHeight));
    geom.feature('workvol').set('pos', {'0','0',sprintf('%.17g[mm]', d.vacuum_z_min)});
    geom.feature('workvol').set('selresult', 'on');
    if axialAccelerationEnabled
        [rodTags,rodMetadata]=create_multipole_segmented_round_rods( ...
            geom,rodArray,axialAcceleration,'rod');
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
        create_rectangular_reference_enclosure(geom,g,d);
        connectorTags={}; enclosure=g.reference_enclosure;
        if create_comsol_grounded_connector(geom,'connIn',g.entrance_interface.connector_shape, ...
                enclosure.outer_half_width_mm,g.entrance_interface.aperture_radius_mm, ...
                g.entrance_interface.connector_length_mm, ...
                d.entrance_plate_z_min-g.entrance_interface.connector_length_mm)
            connectorTags{end+1}='connIn';
        end
        if create_comsol_grounded_connector(geom,'connOut',g.exit_interface.connector_shape, ...
                enclosure.inner_half_width_mm,g.exit_interface.aperture_radius_mm, ...
                g.exit_interface.connector_length_mm,d.exit_plate_z_max)
            connectorTags{end+1}='connOut';
        end
        groundTags=[{'entrance','exit_enclosure','detector'},connectorTags];
    else
        create_comsol_cylindrical_shell(geom,'shield',g.grounded_shield_inner_radius,shieldOuter,vacuumHeight,d.vacuum_z_min);
        create_comsol_cylinder(geom, 'outerIn', shieldOuter, g.grounded_outer_end_cap_thickness, d.vacuum_z_min);
        create_comsol_cylinder(geom, 'outerOut', shieldOuter, g.grounded_outer_end_cap_thickness, ...
            d.exit_outer_ground_inner_z);
        create_comsol_apertured_plate(geom, 'capIn', shieldOuter, ...
            g.entrance_interface.aperture_radius_mm, g.entrance_interface.plate_thickness_mm, ...
            d.entrance_plate_z_min);
        create_comsol_apertured_plate(geom, 'capOut', shieldOuter, ...
            g.exit_interface.aperture_radius_mm, g.exit_interface.plate_thickness_mm, ...
            d.exit_plate_z_min);
        connectorTags = {};
        if create_comsol_grounded_connector(geom,'connIn',g.entrance_interface.connector_shape, ...
                shieldOuter,g.entrance_interface.aperture_radius_mm, ...
                g.entrance_interface.connector_length_mm, ...
                d.entrance_plate_z_min-g.entrance_interface.connector_length_mm)
            connectorTags{end+1} = 'connIn';
        end
        if create_comsol_grounded_connector(geom,'connOut',g.exit_interface.connector_shape, ...
                shieldOuter,g.exit_interface.aperture_radius_mm, ...
                g.exit_interface.connector_length_mm,d.exit_plate_z_max)
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
    assert(~isempty(comp.selection('sel_vac').entities()), 'Finite 3D vacuum selection is empty.');
    material = model.material.create('mat_vac', 'Common');
    material.selection.named('sel_vac');
    material.propertyGroup('def').set('relpermittivity', {'1'});
    es = comp.physics.create('es', 'Electrostatics', 'geom1');
    es.label('Differential RF/DC unit field');
    es.selection.named('sel_vac');
    es.field('electricpotential').field('Vdiff');
    es.field('electricpotential').component({'Vdiff'});
    if accelerationEnabled, model.param.set('field_case','1'); end
    for k = 1:numel(rodTags)
        boundarySelection = ['selb_' rodTags{k}];
        comp.selection.create(boundarySelection, 'Adjacent');
        comp.selection(boundarySelection).set('input', {['geom1_' rodTags{k} '_dom']});
        potential = es.create(sprintf('pot_rod%d', k), 'ElectricPotential', 2);
        potential.selection.named(boundarySelection);
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
        staticVoltage=0;
        if accelerationEnabled && any(strcmp(name,{'outerOut','capOut','connOut','exit_enclosure','detector'}))
            staticVoltage=acceleration.output_reference_V;
        elseif accelerationEnabled && rectangularReference && strcmp(name,'entrance') && ...
                isfield(acceleration,'entrance_plate_V')
            staticVoltage=acceleration.entrance_plate_V;
        end
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
        for k = 1:numel(rodTags)
            potential = esStatic.create(sprintf('pot_rod%d', k), 'ElectricPotential', 2);
            potential.selection.named(['selb_' rodTags{k}]);
            potential.set('V0', sprintf('%.17g[V]',rodMetadata(k).common_mode_V));
        end
        for groundIndex = 1:numel(groundTags)
            name = groundTags{groundIndex};
            potential = esStatic.create(['pot_' name], 'ElectricPotential', 2);
            potential.selection.named(['selb_' name]);
            potential.set('V0', '0[V]');
        end
    end

    mesh = comp.mesh.create('mesh1');
    workingHmax=contract.mesh.working_region_maximum_element_size_mm;
    if isempty(workingHmax), workingHmax=NaN; end
    if isfinite(workingHmax) && workingHmax>0
        configure_comsol_mesh(mesh,'geom1',contract.mesh.global_auto_level,'geom1_workvol_dom',workingHmax);
    else
        configure_comsol_mesh(mesh,'geom1',contract.mesh.global_auto_level,'',workingHmax);
    end
    mesh.run;
    meshInfo = mphmeshstats(model, 'mesh1');
    assert(~meshInfo.isempty && meshInfo.iscomplete && ~meshInfo.hasproblems, ...
        'Finite 3D mesh failed.');
    fprintf(fid,'CHECKPOINT=MESH_COMPLETE\n');
    if accelerationEnabled
        studyDiff=model.study.create('std_es_diff');
        statDiff=studyDiff.create('stat','Stationary');
        statDiff.setEntry('activate','es',true);
        solutionDiff=model.sol.create('sol_es_diff');
        solutionDiff.study('std_es_diff');
        solutionDiff.createAutoSequence('std_es_diff');
        configure_comsol_stationary_direct_solver(solutionDiff);
        solutionDiff.attach('std_es_diff');
        solutionDiff.runAll;
        fprintf(fid,'CHECKPOINT=DIFFERENTIAL_FIELD_COMPLETE\n');
        model.param.set('field_case','0');
        studyStatic=model.study.create('std_es_static');
        statStatic=studyStatic.create('stat','Stationary');
        statStatic.setEntry('activate','es',true);
        solutionStatic=model.sol.create('sol_es_static');
        solutionStatic.study('std_es_static');
        solutionStatic.createAutoSequence('std_es_static');
        configure_comsol_stationary_direct_solver(solutionStatic);
        solutionStatic.attach('std_es_static');
        solutionStatic.runAll;
        model.param.set('field_case','1');
    else
        studyEs = model.study.create('std_es');
        studyEs.create('stat', 'Stationary');
        solutionEs = model.sol.create('sol_es');
        solutionEs.study('std_es');
        solutionEs.createAutoSequence('std_es');
        solutionEs.attach('std_es');
        solutionEs.runAll;
    end
    fprintf(fid,'CHECKPOINT=STATIONARY_FIELDS_COMPLETE\n');

    cpt = comp.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
    cpt.selection.named('sel_vac');
    cpt.feature('pp1').set('mp', 'm_ion');
    cpt.feature('pp1').set('Z', sprintf('%d', baseline.particle_source.charge_state));
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
    dt = 1/rf.frequency_Hz/contract.trajectory.rf_steps_per_period;
    timeMaximum = contract.trajectory.maximum_global_time_us*1e-6;
    if accelerationEnabled, stationarySolutionTag=''; else, stationarySolutionTag='sol_es'; end
    if accelerationEnabled
        if axialAccelerationEnabled
            primaryCaseId='axial_acceleration_rf_on'; controlCaseId='zero_axial_drop_rf_on';
        else
            primaryCaseId='endplate_acceleration_rf_on'; controlCaseId='zero_endplate_drop_rf_on';
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
    massKg=baseline.particle_source.mass_amu*1.66053906660e-27;
    [onMetrics, onEvents, onTrajectories] = analyze_particle_case( ...
        pdOn, source, primaryCaseId, d.detector_z, g.working_region_radius, detectorRadius, ...
        g.rod_z_min, d.rod_z_max, d.entrance_plate_z_max, d.exit_plate_z_max, ...
        g.entrance_interface.aperture_radius_mm, g.exit_interface.aperture_radius_mm,massKg);
    [zeroMetrics, zeroEvents, zeroTrajectories] = analyze_particle_case( ...
        pdZero, source, controlCaseId, d.detector_z, g.working_region_radius, detectorRadius, ...
        g.rod_z_min, d.rod_z_max, d.entrance_plate_z_max, d.exit_plate_z_max, ...
        g.entrance_interface.aperture_radius_mm, g.exit_interface.aperture_radius_mm,massKg);
    events = [onEvents; zeroEvents];
    trajectories = [onTrajectories; zeroTrajectories];
    outputDir = fileparts(eventsPath);
    if ~isfolder(outputDir), mkdir(outputDir); end
    writetable(events, eventsPath);
    writetable(trajectories, trajectoryPath);
    if ~isempty(canonicalStatePath)
        write_canonical_particle_state(pdOn,source,canonicalStatePath,d.rod_z_max, ...
            d.exit_plate_z_max,d.detector_z,g.working_region_radius,detectorRadius, ...
            massKg,rf.frequency_Hz,rf.phase_rad);
    end
    improvement = onMetrics.transmission_fraction-zeroMetrics.transmission_fraction;
    if accelerationEnabled
        expectedEnergy=acceleration.derived.predicted_output_energy_eV;
        energyGain=onMetrics.mean_output_energy_eV-zeroMetrics.mean_output_energy_eV;
        checks=struct('minimum_transmission',onMetrics.transmission_fraction >= acceleration.functional_acceptance.minimum_transmission, ...
            'minimum_mean_energy_gain_eV',energyGain >= acceleration.functional_acceptance.minimum_mean_energy_gain_eV, ...
            'maximum_mean_output_energy_error_eV',abs(onMetrics.mean_output_energy_eV-expectedEnergy) <= acceleration.functional_acceptance.maximum_mean_output_energy_error_eV);
    else
        expectedEnergy=NaN; energyGain=NaN;
        checks = struct( ...
            'minimum_rf_transmission', onMetrics.transmission_fraction >= contract.functional_acceptance.minimum_rf_transmission, ...
            'minimum_improvement_over_zero_rf', improvement >= contract.functional_acceptance.minimum_improvement_over_zero_rf);
    end
    metrics = struct('schema_version', 1, 'role', 'multipole_finite_3d_transport_metrics', ...
        'status', 'UNRESOLVED', 'project_id', contract.project_id, ...
        'model_level', 'L3', 'selected_geometry', selected, ...
        'voltage_contract', rf, ...
        'interface_geometry_mm', struct('entrance_aperture_radius', ...
        g.entrance_interface.aperture_radius_mm, 'exit_aperture_radius', ...
        g.exit_interface.aperture_radius_mm, 'source_z', d.source_z, ...
        'detector_z', d.detector_z), ...
        'primary_case_id',primaryCaseId,'control_case_id',controlCaseId, ...
        'cases', struct(primaryCaseId, onMetrics, controlCaseId, zeroMetrics), ...
        'rf_minus_zero_transmission', improvement, 'checks', checks, ...
        'axial_acceleration_enabled',axialAccelerationEnabled, ...
        'endplate_acceleration_enabled',endplateAccelerationEnabled, ...
        'predicted_output_energy_eV',expectedEnergy,'mean_energy_gain_eV',energyGain, ...
        'mesh', struct('global_auto_level', contract.mesh.global_auto_level, ...
        'working_region_hmax_mm', contract.mesh.working_region_maximum_element_size_mm), ...
        'claim_limit', claimLimit);
    if all(struct2array(checks)), metrics.status = 'PASS'; else, metrics.status = 'FAIL'; end
    metricsFid = fopen(metricsPath, 'w');
    assert(metricsFid >= 0, 'Could not create finite 3D metrics.');
    fprintf(metricsFid, '%s', jsonencode(metrics, 'PrettyPrint', true));
    fclose(metricsFid);
    write_transport_plot(onMetrics, zeroMetrics, onEvents, zeroEvents, ...
        onTrajectories, zeroTrajectories, plotPath, contract.project_id, g, d, ...
        primaryCaseId,controlCaseId);
    create_native_plot(model, solutionOn, 'pd_on', 'pg_on', strrep(primaryCaseId,'_',' '));
    create_native_plot(model, solutionZero, 'pd_zero', 'pg_zero', strrep(controlCaseId,'_',' '));
    model.param.set('rf_scale', '1');
    model.save(modelPath);
    assert(strcmp(metrics.status, 'PASS'), 'Finite 3D functional transport gate failed.');
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
    detectorZ, usableRadius, detectorRadius, rodZMin, rodZMax, entranceCrossingZ, exitCrossingZ, ...
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
    crossing = valid(find(z(valid,particle) >= detectorZ, 1, 'first'));
    entranceCrossing = valid(find(z(valid,particle) >= entranceCrossingZ, 1, 'first'));
    exitCrossing = valid(find(z(valid,particle) >= exitCrossingZ, 1, 'first'));
    if ~isempty(entranceCrossing), entranceRadii(particle) = radius(entranceCrossing,particle); end
    if ~isempty(exitCrossing), exitRadiiAtPlate(particle) = radius(exitCrossing,particle); end
    if ~isempty(crossing) && maximumRodRadius(particle) < usableRadius && ...
            radius(crossing,particle) <= detectorRadius
        transmitted(particle) = true;
        reason = 'detector_plane';
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

function create_rectangular_reference_enclosure(geom,g,d)
enclosure=g.reference_enclosure; outer=enclosure.outer_half_width_mm;
entranceThickness=d.entrance_plate_z_max-d.entrance_plate_z_min;
geom.feature.create('ent_outer','Block');
geom.feature('ent_outer').set('size',{sprintf('%.17g[mm]',2*outer),sprintf('%.17g[mm]',2*outer),sprintf('%.17g[mm]',entranceThickness)});
geom.feature('ent_outer').set('pos',{sprintf('%.17g[mm]',-outer),sprintf('%.17g[mm]',-outer),sprintf('%.17g[mm]',d.entrance_plate_z_min)});
geom.feature.create('ent_hole','Cylinder'); geom.feature('ent_hole').set('r',sprintf('%.17g[mm]',g.entrance_interface.aperture_radius_mm));
geom.feature('ent_hole').set('h',sprintf('%.17g[mm]',entranceThickness)); geom.feature('ent_hole').set('pos',{'0','0',sprintf('%.17g[mm]',d.entrance_plate_z_min)});
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
geom.feature.create('detector','Cylinder'); geom.feature('detector').set('r',sprintf('%.17g[mm]',g.detector_radius_mm));
geom.feature('detector').set('h',sprintf('%.17g[mm]',enclosure.detector_thickness_mm)); geom.feature('detector').set('pos',{'0','0',sprintf('%.17g[mm]',d.detector_z)}); geom.feature('detector').set('selresult','on');
end

function write_canonical_particle_state(pd,source,path,rodExitZ,handoffZ,detectorZ, ...
    usableRadius,detectorRadius,massKg,frequencyHz,phaseRad)
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
    crossing=valid(find(z(valid,particle)>=detectorZ,1,'first')); terminal=valid(end);
    status='lost'; reason='electrode';
    if ~isempty(crossing)&&radius(crossing,particle)<=detectorRadius&&maxRodRadius<usableRadius
        terminal=crossing;status='transmitted';reason='acceptance_detector';
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
plot(zeroTrajectories.z_mm, zeroTrajectories.radius_mm, '.', 'Color', [0.72 0.72 0.72], 'MarkerSize', 2);
plot(onTrajectories.z_mm, onTrajectories.radius_mm, 'x', 'Color', [0 0.447 0.698], 'MarkerSize', 2);
yLimit = geometry.working_region_radius*1.15;
draw_interface_plate(derived.entrance_plate_z_min, derived.entrance_plate_z_max, ...
    geometry.entrance_interface.aperture_radius_mm, yLimit);
draw_interface_plate(derived.exit_plate_z_min, derived.exit_plate_z_max, ...
    geometry.exit_interface.aperture_radius_mm, yLimit);
xlabel('z (mm)'); ylabel('Radius (mm)'); ylim([0 yLimit]);
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
