% Solve finite 3D circular-rod fields and direct RF/zero-RF particle transport.

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
baselinePath = getenv('MULTIPOLE_L3_BASELINE');
contractPath = getenv('MULTIPOLE_L3_CONTRACT');
fieldMetricsPath = getenv('MULTIPOLE_L3_FIELD_METRICS');
sourcePath = getenv('MULTIPOLE_L3_PARTICLE_SOURCE');
runtimeDir = getenv('MULTIPOLE_L3_RUNTIME_DIR');
eventsPath = getenv('MULTIPOLE_L3_EVENTS');
trajectoryPath = getenv('MULTIPOLE_L3_TRAJECTORIES');
metricsPath = getenv('MULTIPOLE_L3_METRICS');
plotPath = getenv('MULTIPOLE_L3_PLOT');
modelPath = getenv('MULTIPOLE_L3_MODEL');
required = {reportPath, baselinePath, contractPath, fieldMetricsPath, sourcePath, ...
    runtimeDir, eventsPath, trajectoryPath, metricsPath, plotPath, modelPath};
assert(all(~cellfun(@isempty, required)), 'Finite 3D multipole environment is incomplete.');
assert(isfile(baselinePath) && isfile(contractPath) && isfile(fieldMetricsPath) && ...
    isfile(sourcePath), 'Finite 3D multipole inputs are missing.');
if ~isfolder(runtimeDir), mkdir(runtimeDir); end

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not create the finite 3D transport report.');
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, 'TASK=MULTIPOLE_FINITE_3D_TRANSPORT\n');

try
    baseline = jsondecode(fileread(baselinePath));
    contract = jsondecode(fileread(contractPath));
    fieldMetrics = jsondecode(fileread(fieldMetricsPath));
    source = readtable(sourcePath);
    n = contract.multipole.radial_order_n;
    electrodeCount = contract.multipole.electrode_count;
    assert(electrodeCount == 2*n && electrodeCount == baseline.multipole.electrode_count, ...
        'Finite 3D multipole identities differ.');
    selected = fieldMetrics.selected_candidate;
    r0 = baseline.geometry_mm.inscribed_radius_r0;
    rodRadius = selected.rod_radius_mm;
    centerRadius = selected.rod_center_radius_mm;
    g = contract.geometry_mm;
    assert(abs(g.rod_length-baseline.geometry_mm.effective_length) < 1e-12, ...
        'Finite 3D rod length differs from the baseline.');
    assert(all(abs(source.z_mm-g.source_z) < 1e-12), 'Particle source plane differs from the L3 contract.');
    rf = baseline.rf;
    import com.comsol.model.*
    import com.comsol.model.util.*
    tag = sprintf('MULTIPOLE_FINITE_3D_%d', electrodeCount);
    if any(strcmp(cell(ModelUtil.tags()), tag)), ModelUtil.remove(tag); end
    model = ModelUtil.create(tag);
    model.label(sprintf('%d-pole finite 3D circular-rod L3 transport', electrodeCount));
    model.param.set('V_rf', sprintf('%.17g[V]', rf.amplitude_V_peak));
    model.param.set('f_rf', sprintf('%.17g[Hz]', rf.frequency_Hz));
    model.param.set('rf_scale', '1');
    model.param.set('m_ion', sprintf('%.17g[kg]', baseline.particle_source.mass_amu*1.66053906660e-27));
    comp = model.component.create('comp1', true);
    geom = comp.geom.create('geom1', 3);
    geom.lengthUnit('mm');
    vacuumHeight = g.vacuum_z_max-g.vacuum_z_min;
    shieldOuter = g.grounded_shield_inner_radius+g.grounded_shield_wall_thickness;
    geom.feature.create('vac', 'Cylinder');
    geom.feature('vac').set('r', sprintf('%.17g[mm]', g.grounded_shield_inner_radius));
    geom.feature('vac').set('h', sprintf('%.17g[mm]', vacuumHeight));
    geom.feature('vac').set('pos', {'0','0',sprintf('%.17g[mm]', g.vacuum_z_min)});
    geom.feature('vac').set('selresult', 'on');
    geom.feature.create('workvol', 'Cylinder');
    geom.feature('workvol').set('r', sprintf('%.17g[mm]', g.working_region_radius));
    geom.feature('workvol').set('h', sprintf('%.17g[mm]', vacuumHeight));
    geom.feature('workvol').set('pos', {'0','0',sprintf('%.17g[mm]', g.vacuum_z_min)});
    geom.feature('workvol').set('selresult', 'on');
    rodTags = cell(1, electrodeCount);
    for k = 1:electrodeCount
        rodTags{k} = sprintf('rod%d', k);
        angle = (k-1)*360/electrodeCount;
        geom.feature.create(rodTags{k}, 'Cylinder');
        geom.feature(rodTags{k}).set('r', sprintf('%.17g[mm]', rodRadius));
        geom.feature(rodTags{k}).set('h', sprintf('%.17g[mm]', g.rod_length));
        geom.feature(rodTags{k}).set('pos', { ...
            sprintf('%.17g[mm]', centerRadius*cosd(angle)), ...
            sprintf('%.17g[mm]', centerRadius*sind(angle)), ...
            sprintf('%.17g[mm]', g.rod_z_min)});
        geom.feature(rodTags{k}).set('selresult', 'on');
    end
    geom.feature.create('shieldO', 'Cylinder');
    geom.feature('shieldO').set('r', sprintf('%.17g[mm]', shieldOuter));
    geom.feature('shieldO').set('h', sprintf('%.17g[mm]', vacuumHeight));
    geom.feature('shieldO').set('pos', {'0','0',sprintf('%.17g[mm]', g.vacuum_z_min)});
    geom.feature.create('shieldH', 'Cylinder');
    geom.feature('shieldH').set('r', sprintf('%.17g[mm]', g.grounded_shield_inner_radius));
    geom.feature('shieldH').set('h', sprintf('%.17g[mm]', vacuumHeight));
    geom.feature('shieldH').set('pos', {'0','0',sprintf('%.17g[mm]', g.vacuum_z_min)});
    geom.feature.create('shield', 'Difference');
    geom.feature('shield').selection('input').set({'shieldO'});
    geom.feature('shield').selection('input2').set({'shieldH'});
    geom.feature('shield').set('selresult', 'on');
    for cap = {'capIn','capOut'}
        name = cap{1};
        z = g.vacuum_z_min;
        if strcmp(name, 'capOut'), z = g.vacuum_z_max-g.grounded_end_cap_thickness; end
        geom.feature.create(name, 'Cylinder');
        geom.feature(name).set('r', sprintf('%.17g[mm]', shieldOuter));
        geom.feature(name).set('h', sprintf('%.17g[mm]', g.grounded_end_cap_thickness));
        geom.feature(name).set('pos', {'0','0',sprintf('%.17g[mm]', z)});
        geom.feature(name).set('selresult', 'on');
    end
    geom.run;

    electrodeTags = [rodTags, {'shield','capIn','capOut'}];
    electrodeDomains = cellfun(@(name) ['geom1_' name '_dom'], electrodeTags, ...
        'UniformOutput', false);
    comp.selection.create('sel_vac', 'Complement');
    comp.selection('sel_vac').set('input', electrodeDomains);
    assert(~isempty(comp.selection('sel_vac').entities()), 'Finite 3D vacuum selection is empty.');
    material = model.material.create('mat_vac', 'Common');
    material.selection.named('sel_vac');
    material.propertyGroup('def').set('relpermittivity', {'1'});
    es = comp.physics.create('es', 'Electrostatics', 'geom1');
    es.selection.named('sel_vac');
    for k = 1:electrodeCount
        boundarySelection = sprintf('selb_rod%d', k);
        comp.selection.create(boundarySelection, 'Adjacent');
        comp.selection(boundarySelection).set('input', {sprintf('geom1_rod%d_dom', k)});
        potential = es.create(sprintf('pot_rod%d', k), 'ElectricPotential', 2);
        potential.selection.named(boundarySelection);
        potential.set('V0', sprintf('%d[V]', 100*(-1)^(k+1)));
    end
    for groundName = {'shield','capIn','capOut'}
        name = groundName{1};
        selection = ['selb_' name];
        comp.selection.create(selection, 'Adjacent');
        comp.selection(selection).set('input', {['geom1_' name '_dom']});
        potential = es.create(['pot_' name], 'ElectricPotential', 2);
        potential.selection.named(selection);
        potential.set('V0', '0[V]');
    end

    mesh = comp.mesh.create('mesh1');
    mesh.feature('size').set('hauto', contract.mesh.global_auto_level);
    mesh.feature.create('szwork', 'Size');
    mesh.feature('szwork').selection.geom('geom1', 3);
    mesh.feature('szwork').selection.named('geom1_workvol_dom');
    mesh.feature('szwork').set('custom', 'on');
    mesh.feature('szwork').set('hmaxactive', true);
    mesh.feature('szwork').set('hmax', sprintf('%.17g[mm]', ...
        contract.mesh.working_region_maximum_element_size_mm));
    mesh.feature.create('ftet1', 'FreeTet');
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
    force.set('E', { ...
        'rf_scale*(V_rf/100[V])*es.Ex*cos(2*pi*f_rf*t)', ...
        'rf_scale*(V_rf/100[V])*es.Ey*cos(2*pi*f_rf*t)', ...
        'rf_scale*(V_rf/100[V])*es.Ez*cos(2*pi*f_rf*t)'});
    dt = 1/rf.frequency_Hz/contract.trajectory.rf_steps_per_period;
    timeMaximum = contract.trajectory.maximum_global_time_us*1e-6;
    [pdOn, solutionOn] = solve_particle_case(model, cpt, 'on', 1, dt, timeMaximum);
    [pdZero, solutionZero] = solve_particle_case(model, cpt, 'zero', 0, dt, timeMaximum);
    [onMetrics, onEvents, onTrajectories] = analyze_particle_case( ...
        pdOn, source, 'finite_3d_rf_on', g.detector_z, g.working_region_radius, ...
        g.rod_z_min, g.rod_z_min+g.rod_length);
    [zeroMetrics, zeroEvents, zeroTrajectories] = analyze_particle_case( ...
        pdZero, source, 'zero_rf_control', g.detector_z, g.working_region_radius, ...
        g.rod_z_min, g.rod_z_min+g.rod_length);
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
    write_transport_plot(onMetrics, zeroMetrics, onEvents, zeroEvents, plotPath, contract.project_id);
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

function [metrics, events, trajectories] = analyze_particle_case(pd, source, caseId, detectorZ, usableRadius, rodZMin, rodZMax)
x = squeeze(pd.p(:,:,1)); y = squeeze(pd.p(:,:,2)); z = squeeze(pd.p(:,:,3));
if isvector(x), x = x(:); y = y(:); z = z(:); end
radius = sqrt(x.^2+y.^2);
particleCount = size(z,2);
eventRows = cell(particleCount, 11);
trajectoryRows = cell(0, 7);
transmitted = false(1, particleCount);
exitRadii = nan(1, particleCount);
maximumRodRadius = nan(1, particleCount);
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
    if ~isempty(crossing) && maximumRodRadius(particle) < usableRadius
        transmitted(particle) = true;
        reason = 'detector_plane';
        terminal = crossing;
        exitRadii(particle) = radius(crossing,particle);
    else
        terminal = valid(end);
        if maximumRodRadius(particle) >= usableRadius
            reason = 'usable_radius_exceeded';
        else
            reason = 'electrode_or_timeout';
        end
    end
    status = 'lost'; if transmitted(particle), status = 'transmitted'; end
    eventRows(particle,:) = {caseId, source.particle_id(particle), status, reason, ...
        source.birth_time_s(particle), pd.t(terminal), x(terminal,particle), ...
        y(terminal,particle), z(terminal,particle), radius(terminal,particle), ...
        maximumRodRadius(particle)};
    sampled = unique([valid(1:20:end); valid(end)]);
    for sample = sampled'
        trajectoryRows(end+1,:) = {caseId, source.particle_id(particle), pd.t(sample), ...
            x(sample,particle), y(sample,particle), z(sample,particle), radius(sample,particle)}; %#ok<AGROW>
    end
end
events = cell2table(eventRows, 'VariableNames', {'case_id','particle_id','status', ...
    'terminal_reason','birth_time_s','terminal_time_s','terminal_x_mm','terminal_y_mm', ...
    'terminal_z_mm','terminal_radius_mm','maximum_rod_radius_mm'});
trajectories = cell2table(trajectoryRows, 'VariableNames', {'case_id','particle_id', ...
    'time_s','x_mm','y_mm','z_mm','radius_mm'});
metrics = struct('particles', particleCount, 'transmitted', sum(transmitted), ...
    'transmission_fraction', mean(transmitted), ...
    'exit_rms_radius_mm', sqrt(mean(exitRadii(transmitted).^2)), ...
    'maximum_rod_radius_mm', max(maximumRodRadius));
end

function write_transport_plot(onMetrics, zeroMetrics, onEvents, zeroEvents, path, projectId)
figureHandle = figure('Visible', 'off', 'Position', [100 100 1000 420]);
tiledlayout(1,2);
nexttile; bar([zeroMetrics.transmission_fraction,onMetrics.transmission_fraction]);
set(gca, 'XTickLabel', {'0 V control','RF on'}); ylim([0 1.05]); ylabel('Transmission fraction');
title('Finite 3D functional control');
nexttile; hold on;
scatter(zeroEvents.terminal_x_mm, zeroEvents.terminal_y_mm, 14, [0.55 0.55 0.55], 'filled');
scatter(onEvents.terminal_x_mm, onEvents.terminal_y_mm, 14, [0.13 0.44 0.71], 'filled');
axis equal; xlabel('Terminal x (mm)'); ylabel('Terminal y (mm)');
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
