% Solve finite 3D circular-rod fields and direct RF/zero-RF particle transport.

addpath(fullfile(fileparts(mfilename('fullpath')),'..','comsol'));

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
baselinePath = getenv('MULTIPOLE_L3_BASELINE');
familyOperatingPath = getenv('MULTIPOLE_L3_FAMILY_OPERATING');
contractPath = getenv('MULTIPOLE_L3_CONTRACT');
fieldMetricsPath = getenv('MULTIPOLE_L3_FIELD_METRICS');
roundRodGeometryPath = getenv('MULTIPOLE_L3_ROUND_ROD_GEOMETRY');
sourcePath = getenv('MULTIPOLE_L3_PARTICLE_SOURCE');
runtimeDir = getenv('MULTIPOLE_L3_RUNTIME_DIR');
eventsPath = getenv('MULTIPOLE_L3_EVENTS');
trajectoryPath = getenv('MULTIPOLE_L3_TRAJECTORIES');
metricsPath = getenv('MULTIPOLE_L3_METRICS');
plotPath = getenv('MULTIPOLE_L3_PLOT');
modelPath = getenv('MULTIPOLE_L3_MODEL');
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
    shieldOuter = d.shield_outer_radius;
    geom.feature.create('vac', 'Cylinder');
    geom.feature('vac').set('r', sprintf('%.17g[mm]', g.grounded_shield_inner_radius));
    geom.feature('vac').set('h', sprintf('%.17g[mm]', vacuumHeight));
    geom.feature('vac').set('pos', {'0','0',sprintf('%.17g[mm]', d.vacuum_z_min)});
    geom.feature('vac').set('selresult', 'on');
    geom.feature.create('workvol', 'Cylinder');
    geom.feature('workvol').set('r', sprintf('%.17g[mm]', g.working_region_radius));
    geom.feature('workvol').set('h', sprintf('%.17g[mm]', vacuumHeight));
    geom.feature('workvol').set('pos', {'0','0',sprintf('%.17g[mm]', d.vacuum_z_min)});
    geom.feature('workvol').set('selresult', 'on');
    rodTags=create_multipole_round_rods(geom,rodArray,'rod','z',[0 0 0]);
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
    if g.entrance_interface.connector_length_mm > 0
        create_comsol_apertured_plate(geom, 'connIn', shieldOuter, ...
            g.entrance_interface.aperture_radius_mm, g.entrance_interface.connector_length_mm, ...
            d.entrance_plate_z_min-g.entrance_interface.connector_length_mm);
        connectorTags{end+1} = 'connIn';
    end
    if g.exit_interface.connector_length_mm > 0
        create_comsol_apertured_plate(geom, 'connOut', shieldOuter, ...
            g.exit_interface.aperture_radius_mm, g.exit_interface.connector_length_mm, ...
            d.exit_plate_z_max);
        connectorTags{end+1} = 'connOut';
    end
    geom.run;

    groundTags = [{'shield','outerIn','outerOut','capIn','capOut'}, connectorTags];
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
    for k = 1:electrodeCount
        boundarySelection = sprintf('selb_rod%d', k);
        comp.selection.create(boundarySelection, 'Adjacent');
        comp.selection(boundarySelection).set('input', {sprintf('geom1_rod%d_dom', k)});
        potential = es.create(sprintf('pot_rod%d', k), 'ElectricPotential', 2);
        potential.selection.named(boundarySelection);
        potential.set('V0', sprintf('%d[V]', 100*(3-2*rods(k).electrode_group)));
    end
    for groundIndex = 1:numel(groundTags)
        name = groundTags{groundIndex};
        selection = ['selb_' name];
        comp.selection.create(selection, 'Adjacent');
        comp.selection(selection).set('input', {['geom1_' name '_dom']});
        potential = es.create(['pot_' name], 'ElectricPotential', 2);
        potential.selection.named(selection);
        potential.set('V0', '0[V]');
    end
    esStatic = comp.physics.create('es_static', 'Electrostatics', 'geom1');
    esStatic.label('Common-mode static field');
    esStatic.selection.named('sel_vac');
    esStatic.field('electricpotential').field('Vstatic');
    esStatic.field('electricpotential').component({'Vstatic'});
    for k = 1:electrodeCount
        potential = esStatic.create(sprintf('pot_rod%d', k), 'ElectricPotential', 2);
        potential.selection.named(sprintf('selb_rod%d', k));
        potential.set('V0', 'V_axis');
    end
    for groundIndex = 1:numel(groundTags)
        name = groundTags{groundIndex};
        potential = esStatic.create(['pot_' name], 'ElectricPotential', 2);
        potential.selection.named(['selb_' name]);
        potential.set('V0', '0[V]');
    end

    mesh = comp.mesh.create('mesh1');
    configure_comsol_mesh(mesh,'geom1',contract.mesh.global_auto_level,'geom1_workvol_dom', ...
        contract.mesh.working_region_maximum_element_size_mm);
    mesh.run;
    meshInfo = mphmeshstats(model, 'mesh1');
    assert(~meshInfo.isempty && meshInfo.iscomplete && ~meshInfo.hasproblems, ...
        'Finite 3D mesh failed.');
    studyEs = model.study.create('std_es');
    studyEs.create('stat', 'Stationary');
    solutionEs = model.sol.create('sol_es');
    solutionEs.study('std_es');
    solutionEs.createAutoSequence('std_es');
    solutionEs.attach('std_es');
    solutionEs.runAll;

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
    force.set('E', { ...
        [differentialScale '*(-d(Vdiff,x))-d(Vstatic,x)'], ...
        [differentialScale '*(-d(Vdiff,y))-d(Vstatic,y)'], ...
        [differentialScale '*(-d(Vdiff,z))-d(Vstatic,z)']});
    dt = 1/rf.frequency_Hz/contract.trajectory.rf_steps_per_period;
    timeMaximum = contract.trajectory.maximum_global_time_us*1e-6;
    [pdOn, solutionOn] = solve_particle_case(model, cpt, 'on', 1, dt, timeMaximum);
    [pdZero, solutionZero] = solve_particle_case(model, cpt, 'zero', 0, dt, timeMaximum);
    [onMetrics, onEvents, onTrajectories] = analyze_particle_case( ...
        pdOn, source, 'finite_3d_rf_on', d.detector_z, g.working_region_radius, ...
        g.rod_z_min, d.rod_z_max, d.entrance_plate_z_max, d.exit_plate_z_max, ...
        g.entrance_interface.aperture_radius_mm, g.exit_interface.aperture_radius_mm);
    [zeroMetrics, zeroEvents, zeroTrajectories] = analyze_particle_case( ...
        pdZero, source, 'zero_rf_control', d.detector_z, g.working_region_radius, ...
        g.rod_z_min, d.rod_z_max, d.entrance_plate_z_max, d.exit_plate_z_max, ...
        g.entrance_interface.aperture_radius_mm, g.exit_interface.aperture_radius_mm);
    events = [onEvents; zeroEvents];
    trajectories = [onTrajectories; zeroTrajectories];
    outputDir = fileparts(eventsPath);
    if ~isfolder(outputDir), mkdir(outputDir); end
    writetable(events, eventsPath);
    writetable(trajectories, trajectoryPath);
    improvement = onMetrics.transmission_fraction-zeroMetrics.transmission_fraction;
    checks = struct( ...
        'minimum_rf_transmission', onMetrics.transmission_fraction >= contract.functional_acceptance.minimum_rf_transmission, ...
        'minimum_improvement_over_zero_rf', improvement >= contract.functional_acceptance.minimum_improvement_over_zero_rf);
    metrics = struct('schema_version', 1, 'role', 'multipole_finite_3d_transport_metrics', ...
        'status', 'UNRESOLVED', 'project_id', contract.project_id, ...
        'model_level', 'L3', 'selected_geometry', selected, ...
        'voltage_contract', rf, ...
        'interface_geometry_mm', struct('entrance_aperture_radius', ...
        g.entrance_interface.aperture_radius_mm, 'exit_aperture_radius', ...
        g.exit_interface.aperture_radius_mm, 'source_z', d.source_z, ...
        'detector_z', d.detector_z), ...
        'cases', struct('finite_3d_rf_on', onMetrics, 'zero_rf_control', zeroMetrics), ...
        'rf_minus_zero_transmission', improvement, 'checks', checks, ...
        'mesh', struct('global_auto_level', contract.mesh.global_auto_level, ...
        'working_region_hmax_mm', contract.mesh.working_region_maximum_element_size_mm), ...
        'claim_limit', contract.claim_limit);
    if all(struct2array(checks)), metrics.status = 'PASS'; else, metrics.status = 'FAIL'; end
    metricsFid = fopen(metricsPath, 'w');
    assert(metricsFid >= 0, 'Could not create finite 3D metrics.');
    fprintf(metricsFid, '%s', jsonencode(metrics, 'PrettyPrint', true));
    fclose(metricsFid);
    write_transport_plot(onMetrics, zeroMetrics, onEvents, zeroEvents, ...
        onTrajectories, zeroTrajectories, plotPath, contract.project_id, g, d);
    create_native_plot(model, solutionOn, 'pd_on', 'pg_on', 'Finite 3D RF-on trajectories');
    create_native_plot(model, solutionZero, 'pd_zero', 'pg_zero', 'Finite 3D zero-RF control');
    model.param.set('rf_scale', '1');
    model.save(modelPath);
    assert(strcmp(metrics.status, 'PASS'), 'Finite 3D functional transport gate failed.');
    delete(fullfile(runtimeDir, 'particle_*.txt'));
    if isfolder(runtimeDir), rmdir(runtimeDir); end
    fprintf(fid, ['ELECTRODE_COUNT=%d\nRF_TRANSMISSION=%.17g\n' ...
        'ZERO_RF_TRANSMISSION=%.17g\nMODEL_SAVED=true\nSTATUS=PASS\n'], ...
        electrodeCount, onMetrics.transmission_fraction, zeroMetrics.transmission_fraction);
    ModelUtil.remove(tag);
catch exception
    fprintf(fid, 'STATUS=FAIL\nERROR=%s\n', ...
        getReport(exception, 'extended', 'hyperlinks', 'off'));
    rethrow(exception)
end
clear cleanup

function [pd, solutionTag] = solve_particle_case(model, cpt, label, rfScale, dt, timeMaximum)
studyTag = ['std_' label];
stepTag = ['time_' label];
solutionTag = ['sol_' label];
model.param.set('rf_scale', sprintf('%d', rfScale));
study = model.study.create(studyTag);
time = study.create(stepTag, 'Transient');
time.set('tlist', sprintf('range(0,%.17g,%.17g)', dt, timeMaximum));
time.setEntry('activate', 'es', false);
time.setEntry('activate', 'es_static', false);
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
solution.feature('v1').set('notsolmethod', 'sol');
solution.feature('v1').set('notsol', 'sol_es');
solution.attach(studyTag);
solution.runAll;
datasetTag = ['pd_' label '_temp'];
dataset = model.result.dataset.create(datasetTag, 'Particle');
dataset.set('solution', solutionTag);
pd = mphparticle(model, 'dataset', datasetTag);
model.result.dataset.remove(datasetTag);
end

function [metrics, events, trajectories] = analyze_particle_case(pd, source, caseId, ...
    detectorZ, usableRadius, rodZMin, rodZMax, entranceCrossingZ, exitCrossingZ, ...
    entranceApertureRadius, exitApertureRadius)
x = squeeze(pd.p(:,:,1)); y = squeeze(pd.p(:,:,2)); z = squeeze(pd.p(:,:,3));
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
    if ~isempty(crossing) && maximumRodRadius(particle) < usableRadius
        transmitted(particle) = true;
        reason = 'detector_plane';
        terminal = crossing;
        exitRadii(particle) = radius(crossing,particle);
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
    'maximum_rod_radius_mm', max(maximumRodRadius));
end

function write_transport_plot(onMetrics, zeroMetrics, onEvents, zeroEvents, ...
    onTrajectories, zeroTrajectories, path, projectId, geometry, derived)
figureHandle = figure('Visible', 'off', 'Position', [100 100 1000 420]);
tiledlayout(1,2);
nexttile; hold on;
plot(zeroTrajectories.z_mm, zeroTrajectories.radius_mm, '.', 'Color', [0.72 0.72 0.72], 'MarkerSize', 2);
plot(onTrajectories.z_mm, onTrajectories.radius_mm, '.', 'Color', [0.13 0.44 0.71], 'MarkerSize', 2);
yLimit = geometry.working_region_radius*1.15;
draw_interface_plate(derived.entrance_plate_z_min, derived.entrance_plate_z_max, ...
    geometry.entrance_interface.aperture_radius_mm, yLimit);
draw_interface_plate(derived.exit_plate_z_min, derived.exit_plate_z_max, ...
    geometry.exit_interface.aperture_radius_mm, yLimit);
xlabel('z (mm)'); ylabel('Radius (mm)'); ylim([0 yLimit]);
title(sprintf('Interfaces: RF %.0f%%, 0 V %.0f%%', ...
    100*onMetrics.transmission_fraction, 100*zeroMetrics.transmission_fraction));
nexttile; hold on;
scatter(zeroEvents.terminal_x_mm, zeroEvents.terminal_y_mm, 14, [0.55 0.55 0.55], 'filled');
scatter(onEvents.terminal_x_mm, onEvents.terminal_y_mm, 14, [0.13 0.44 0.71], 'filled');
axis equal; xlabel('Terminal x (mm)'); ylabel('Terminal y (mm)');
theta = linspace(0,2*pi,200);
plot(geometry.exit_interface.aperture_radius_mm*cos(theta), ...
    geometry.exit_interface.aperture_radius_mm*sin(theta), 'k--', 'LineWidth', 0.8, ...
    'HandleVisibility', 'off');
legend({'0 V control','RF on'}, 'Location', 'best'); title('Terminal transverse states');
sgtitle([strrep(projectId,'_','\_') ' — finite 3D L3']);
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
