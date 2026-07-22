% Solve the two no-pulse S2 field bases on the shared passive-connector geometry.

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
metricsPath = getenv('RF_OATOF_S2_FIELD_METRICS');
samplesPath = getenv('RF_OATOF_S2_FIELD_SAMPLES');
contractPath = getenv('RF_OATOF_S2_CONTRACT');
s1ContractPath = getenv('RF_OATOF_S2_S1_CONTRACT');
rfResolvedPath = getenv('RF_OATOF_S2_RF_RESOLVED');
oaBaselinePath = getenv('RF_OATOF_S2_OA_BASELINE');
oaComsolDir = getenv('RF_OATOF_S2_OA_COMSOL_DIR');
particleInputPath = getenv('RF_OATOF_S2_PARTICLE_INPUT');
particleOutputPath = getenv('RF_OATOF_S2_PARTICLE_OUTPUT');
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
    assert(~contract.field_ownership.oa_extraction_pulse_included, ...
        'The no-pulse S2 field task cannot include an oa extraction pulse.');
    particleEnabled = ~isempty(particleInputPath);
    if particleEnabled
        assert(contract.permissions.particle_runtime_allowed, ...
            'The S2 contract does not authorize particle runtime.');
        assert(isfile(particleInputPath) && ~isempty(particleOutputPath), ...
            'S2 particle input or output is missing.');
    end

    import com.comsol.model.util.*
    tag = 'RFOATOF_S2_FIELD';
    [model, comp, context, geometryInfo, meshElementCounts] = ...
        prepare_s2_joint_field_model(contract, s1, rf, oa, oaComsolDir, tag);

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

    particleInputCount = 0;
    oatofEntryCrossings = 0;
    connectorLosses = 0;
    if particleEnabled
        particleEvents = track_connector_particles( ...
            model, comp, particleInputPath, fileparts(particleOutputPath), contract, rf);
        writetable(particleEvents, particleOutputPath);
        particleInputCount = height(particleEvents);
        oatofEntryCrossings = nnz(string(particleEvents.event) == "oatof_entry");
        connectorLosses = nnz(string(particleEvents.status) == "lost");
        assert(oatofEntryCrossings >= contract.functional_candidate.minimum_oatof_entry_crossings, ...
            'S2 particle runtime did not meet the minimum oa-entry crossing count.');
    end

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
        'particle_runtime_executed', particleEnabled, ...
        'particle_input_count', particleInputCount, ...
        'oatof_entry_crossings', oatofEntryCrossings, ...
        'connector_losses', connectorLosses, ...
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
        'FIELD_BASES=2\nPROBE_ROWS=%d\nFINITE_PROBES=true\nPARTICLE_RUNTIME=%s\n' ...
        'PARTICLE_INPUT=%d\nOATOF_ENTRY_CROSSINGS=%d\nCONNECTOR_LOSSES=%d\n' ...
        'OA_PULSE=false\nMODEL_SAVED=false\nSTATUS=PASS\n'], ...
        context.gap_mm, geometryInfo.Ndomains, meshElementTotal, height(samples), ...
        char(lower(string(particleEnabled))), particleInputCount, oatofEntryCrossings, connectorLosses);
    ModelUtil.remove(tag);
catch exception
    fprintf(fid, 'STATUS=FAIL\nERROR=%s\n', ...
        getReport(exception, 'extended', 'hyperlinks', 'off'));
    rethrow(exception)
end
clear cleanup

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

function events = track_connector_particles(model, comp, inputPath, runtimeDir, contract, rf)
ions = readtable(inputPath, 'VariableNamingRule', 'preserve');
required = {'particle_id','frame_id','clock_epoch_id','instrument_time_us', ...
    'lineage_age_us','particle_age_us','mass_amu','charge_state', ...
    'position_x_mm','position_y_mm','position_z_mm', ...
    'velocity_x_m_s','velocity_y_m_s','velocity_z_m_s'};
assert(all(ismember(required, ions.Properties.VariableNames)), ...
    'S2 canonical particle columns are incomplete.');
candidate = contract.functional_candidate;
assert(height(ions) == candidate.source_particles, ...
    'S2 particle count differs from the frozen source contract.');
assert(numel(unique(ions.mass_amu)) == 1 && numel(unique(ions.charge_state)) == 1, ...
    'S2 minimal particle runtime requires one mass and charge state.');
registration = contract.nominal_registration;
sourceCenter = registration.source_exit_center_instrument_mm(:).';
targetCenter = registration.target_entry_center_instrument_mm(:).';
assert(all(string(ions.frame_id) == string(registration.instrument_frame)), ...
    'S2 particle frame differs from the registered instrument frame.');
assert(all(string(ions.clock_epoch_id) == string(candidate.clock_epoch_id)), ...
    'S2 particle clock epoch differs from the candidate contract.');
assert(all(abs(ions.position_x_mm-sourceCenter(1)) <= 1e-12), ...
    'S2 particles must begin on the physical RF exit plane.');
assert(all(ions.velocity_x_m_s > 0), ...
    'S2 particles must move from the RF exit toward the oa entry.');
radial = hypot(ions.position_y_mm-sourceCenter(2), ions.position_z_mm-sourceCenter(3));
assert(all(radial <= contract.passive_connector_geometry.upstream_clear_aperture.radius_mm+1e-12), ...
    'S2 particle source exceeds the RF exit aperture.');
if ~isfolder(runtimeDir), mkdir(runtimeDir); end

cpt = comp.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
cpt.label('S2 passive connector shared-clock N=100');
cpt.selection.named('sel_vac');
cpt.feature('pp1').set('mp', sprintf('%.17g[kg]', ions.mass_amu(1)*1.66053906660e-27));
cpt.feature('pp1').set('Z', sprintf('%d', round(ions.charge_state(1))));
releaseOffset = contract.no_pulse_field_candidate.boundary_probe_inset_mm;
directMating = abs(contract.nominal_registration.connector_gap_mm) <= 1e-12;
aperture = contract.passive_connector_geometry.downstream_entry_aperture;
insidePhysicalAperture = ...
    abs(ions.position_y_mm-targetCenter(2)) <= aperture.full_width_y_mm/2+1e-12 & ...
    abs(ions.position_z_mm-targetCenter(3)) <= aperture.full_height_z_mm/2+1e-12;
if directMating
    releaseIndices = find(insidePhysicalAperture);
else
    releaseIndices = (1:height(ions)).';
end
releaseColumnByIon = zeros(height(ions), 1);
releaseTimeUs = ions.instrument_time_us;
for releaseColumn = 1:numel(releaseIndices)
    index = releaseIndices(releaseColumn);
    releaseColumnByIon(index) = releaseColumn;
    restartDtS = 0;
    if directMating
        restartDtS = releaseOffset*1e-3/ions.velocity_x_m_s(index);
    end
    releaseTimeUs(index) = ions.instrument_time_us(index)+restartDtS*1e6;
    releaseData = [ions.position_x_mm(index)+releaseOffset, ...
        ions.position_y_mm(index)+ions.velocity_y_m_s(index)*restartDtS*1e3, ...
        ions.position_z_mm(index)+ions.velocity_z_m_s(index)*restartDtS*1e3, ...
        ions.velocity_x_m_s(index), ions.velocity_y_m_s(index), ions.velocity_z_m_s(index)];
    releasePath = fullfile(runtimeDir, sprintf('s2_connector_particle_%03d.txt', ions.particle_id(index)));
    writematrix(releaseData, releasePath, 'Delimiter', 'tab');
    release = cpt.create(sprintf('rel%03d', releaseColumn), 'ReleaseFromDataFile', -1);
    release.set('Filename', releasePath);
    release.set('icolp', '0');
    release.set('VelocitySpecification', 'SpecifyVelocity');
    release.set('InitialVelocity', 'FromFile');
    release.set('icolv', '3');
    release.set('rt', sprintf('%.17g[us]', releaseTimeUs(index)));
    release.importData();
end

rfScale = rf.mode.rf.amplitude_V_peak / ...
    contract.no_pulse_field_candidate.rf_unit_voltage_V;
frequency = rf.mode.rf.frequency_Hz;
phase = rf.mode.rf.phase_rad;
electricForce = cpt.create('ef1', 'ElectricForce', 3);
electricForce.selection.named('sel_vac');
electricForce.set('E_src', 'userdef');
electricForce.set('E', { ...
    sprintf('(-d(V,x))+%.17g*(-d(Vrf,x))*sin(2*pi*%.17g[Hz]*t+%.17g)', rfScale, frequency, phase), ...
    sprintf('(-d(V,y))+%.17g*(-d(Vrf,y))*sin(2*pi*%.17g[Hz]*t+%.17g)', rfScale, frequency, phase), ...
    sprintf('(-d(V,z))+%.17g*(-d(Vrf,z))*sin(2*pi*%.17g[Hz]*t+%.17g)', rfScale, frequency, phase)});
timeStep = 1 / frequency / candidate.rf_steps_per_period;
minimumVx = min(ions.velocity_x_m_s);
transitEstimate = contract.nominal_registration.connector_gap_mm*1e-3/minimumVx;
timeStart = max(0, min(releaseTimeUs(releaseIndices))*1e-6-timeStep);
timeEnd = max(releaseTimeUs(releaseIndices))*1e-6 + max(timeStep, ...
    candidate.connector_transit_time_margin_factor*transitEstimate);
study = model.study.create('std2');
time = study.create('time1', 'Transient');
time.set('tlist', sprintf('range(%.17g,%.17g,%.17g)', timeStart, timeStep, timeEnd));
time.setEntry('activate', 'es_static', false);
time.setEntry('activate', 'es_rf', false);
time.setEntry('activate', 'cpt', true);
for releaseColumn = 1:numel(releaseIndices)
    cpt.feature(sprintf('rel%03d', releaseColumn)).set('StudyStep', 'std2/time1');
end
cpt.feature('pp1').set('StudyStep', 'std2/time1');
solution = model.sol.create('sol2');
solution.study('std2');
solution.createAutoSequence('std2');
solution.feature('v1').set('notsolmethod', 'sol');
solution.feature('v1').set('notsol', 'sol1');
solution.attach('std2');
solution.runAll;

dataset = model.result.dataset.create('pdset1', 'Particle');
dataset.set('solution', 'sol2');
particles = mphparticle(model, 'dataset', 'pdset1');
x = squeeze(particles.p(:,:,1)); y = squeeze(particles.p(:,:,2)); z = squeeze(particles.p(:,:,3));
vx = squeeze(particles.v(:,:,1)); vy = squeeze(particles.v(:,:,2)); vz = squeeze(particles.v(:,:,3));
if isvector(x)
    x=x(:); y=y(:); z=z(:); vx=vx(:); vy=vy(:); vz=vz(:);
end
assert(size(x,2) == numel(releaseIndices), 'S2 solved particle count differs from released particles.');
rows = cell(height(ions), 22);
for index = 1:height(ions)
    if directMating
        state = struct('t_s', ions.instrument_time_us(index)*1e-6, ...
            'x_mm', targetCenter(1), 'y_mm', ions.position_y_mm(index), ...
            'z_mm', ions.position_z_mm(index), 'vx_m_s', ions.velocity_x_m_s(index), ...
            'vy_m_s', ions.velocity_y_m_s(index), 'vz_m_s', ions.velocity_z_m_s(index));
        crossed = true;
    else
        column = releaseColumnByIon(index);
        [state, crossed] = interpolate_x_plane(particles.t, x(:,column), y(:,column), z(:,column), ...
            vx(:,column), vy(:,column), vz(:,column), targetCenter(1));
    end
    insideAperture = crossed && ...
        abs(state.y_mm-targetCenter(2)) <= aperture.full_width_y_mm/2+1e-12 && ...
        abs(state.z_mm-targetCenter(3)) <= aperture.full_height_z_mm/2+1e-12;
    if insideAperture
        event = 'oatof_entry'; status = 'transmitted'; reason = 'none';
    elseif crossed
        event = 'downstream_entry_wall'; status = 'lost'; reason = 'outside_rectangular_oatof_entry';
    else
        column = releaseColumnByIon(index);
        valid = find(isfinite(x(:,column)) & isfinite(y(:,column)) & isfinite(z(:,column)) & ...
            isfinite(vx(:,column)) & isfinite(vy(:,column)) & isfinite(vz(:,column)));
        assert(~isempty(valid), 'S2 released particle has no finite state.');
        last = valid(end);
        state = struct('t_s', particles.t(last), 'x_mm', x(last,column), ...
            'y_mm', y(last,column), 'z_mm', z(last,column), ...
            'vx_m_s', vx(last,column), 'vy_m_s', vy(last,column), 'vz_m_s', vz(last,column));
        event = 'terminal'; status = 'lost'; reason = 'no_oatof_entry_before_end_or_boundary';
    end
    elapsedUs = max(0, state.t_s*1e6-ions.instrument_time_us(index));
    speedSquared = state.vx_m_s^2+state.vy_m_s^2+state.vz_m_s^2;
    energyEv = 0.5*ions.mass_amu(index)*1.66053906660e-27*speedSquared/1.602176634e-19;
    rows(index,:) = {ions.particle_id(index), event, status, reason, ...
        string(ions.frame_id(index)), string(ions.clock_epoch_id(index)), ...
        ions.instrument_time_us(index), state.t_s*1e6, ...
        ions.lineage_age_us(index)+elapsedUs, ions.particle_age_us(index)+elapsedUs, elapsedUs, ...
        ions.mass_amu(index), ions.charge_state(index), ...
        state.x_mm, state.y_mm, state.z_mm, state.vx_m_s, state.vy_m_s, state.vz_m_s, ...
        energyEv, mod(2*pi*frequency*state.t_s+phase, 2*pi), insideAperture};
end
events = cell2table(rows, 'VariableNames', {'particle_id','event','status','terminal_reason', ...
    'frame_id','clock_epoch_id','entry_instrument_time_us','instrument_time_us', ...
    'lineage_age_us','particle_age_us','last_component_elapsed_time_us', ...
    'mass_amu','charge_state','position_x_mm','position_y_mm','position_z_mm', ...
    'velocity_x_m_s','velocity_y_m_s','velocity_z_m_s','kinetic_energy_eV', ...
        'rf_phase_rad','first_forward_oatof_entry'});
end

function [state, found] = interpolate_x_plane(timeS, x, y, z, vx, vy, vz, planeMm)
state = struct();
found = false;
valid = find(isfinite(x) & isfinite(y) & isfinite(z) & ...
    isfinite(vx) & isfinite(vy) & isfinite(vz));
for index = 2:numel(valid)
    left = valid(index-1);
    right = valid(index);
    if x(left) < planeMm && x(right) >= planeMm && x(right) > x(left)
        fraction = (planeMm-x(left))/(x(right)-x(left));
        lerp = @(a,b) a+fraction*(b-a);
        state = struct('t_s', lerp(timeS(left),timeS(right)), ...
            'x_mm', planeMm, 'y_mm', lerp(y(left),y(right)), ...
            'z_mm', lerp(z(left),z(right)), 'vx_m_s', lerp(vx(left),vx(right)), ...
            'vy_m_s', lerp(vy(left),vy(right)), 'vz_m_s', lerp(vz(left),vz(right)));
        found = true;
        return
    end
end
end
