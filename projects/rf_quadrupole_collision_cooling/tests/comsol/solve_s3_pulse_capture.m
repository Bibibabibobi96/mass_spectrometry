% Track the RF-exit population through S2 geometry under one shared finite pulse.

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
metricsPath = getenv('RF_OATOF_S3_METRICS');
terminalPath = getenv('RF_OATOF_S3_TERMINAL_OUTPUT');
capturePath = getenv('RF_OATOF_S3_CAPTURE_OUTPUT');
localExitPath = getenv('RF_OATOF_S3_LOCAL_EXIT_OUTPUT');
s3Path = getenv('RF_OATOF_S3_CONTRACT');
s2Path = getenv('RF_OATOF_S3_S2_CONTRACT');
s1Path = getenv('RF_OATOF_S3_S1_CONTRACT');
rfPath = getenv('RF_OATOF_S3_RF_RESOLVED');
oaPath = getenv('RF_OATOF_S3_OA_BASELINE');
schedulePath = getenv('RF_OATOF_S3_PULSE_SCHEDULE');
particlePath = getenv('RF_OATOF_S3_PARTICLE_INPUT');
oaComsolDir = getenv('RF_OATOF_S3_OA_COMSOL_DIR');
requiredFiles = {s3Path,s2Path,s1Path,rfPath,oaPath,schedulePath,particlePath};
assert(~isempty(reportPath) && ~isempty(metricsPath) && ...
    ~isempty(terminalPath) && ~isempty(capturePath) && ~isempty(localExitPath), ...
    'S3 output paths are incomplete.');
assert(all(cellfun(@isfile, requiredFiles)) && isfolder(oaComsolDir), ...
    'S3 frozen inputs are incomplete.');

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not create the S3 task report.');
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, 'TASK=S3_SHARED_CLOCK_PULSE_CAPTURE\n');

try
    s3 = jsondecode(fileread(s3Path));
    s2 = jsondecode(fileread(s2Path));
    s1 = jsondecode(fileread(s1Path));
    rf = jsondecode(fileread(rfPath));
    oa = jsondecode(fileread(oaPath));
    schedule = jsondecode(fileread(schedulePath));
    assert(s3.permissions.nominal_particle_runtime_allowed && ...
        ~s3.permissions.s3_stage_pass_allowed, ...
        'S3 runtime authorization or qualification boundary differs.');
    assert(strcmp(schedule.role, 'rf_to_oatof_s3_centroid_pulse_schedule') && ...
        strcmp(schedule.status, 'PASS'), 'S3 pulse schedule is invalid.');

    import com.comsol.model.util.*
    tag = 'RFOATOF_S3_PULSE';
    [model, comp, context, geometryInfo, meshElementCounts] = ...
        prepare_s2_joint_field_model(s2, s1, rf, oa, oaComsolDir, tag);
    [terminal, capture, localExit] = track_pulsed_particles( ...
        model, comp, particlePath, fileparts(terminalPath), ...
        s3, s2, rf, oa, schedule, context);
    writetable(terminal, terminalPath);
    writetable(capture, capturePath);
    writetable(localExit, localExitPath);

    entryCount = nnz(string(terminal.oatof_entry_status) == "transmitted");
    activeCount = height(capture);
    localExitCount = height(localExit);
    assert(activeCount >= s3.runtime.minimum_active_at_pulse, ...
        'S3 runtime has no active particle at the shared pulse.');
    assert(localExitCount >= s3.runtime.minimum_local_accelerator_exit, ...
        'S3 runtime has no local accelerator exit state.');
    metrics = struct( ...
        'schema_version', 1, ...
        'role', 'rf_to_oatof_s3_pulse_capture_metrics', ...
        'status', 'PASS', ...
        'source_particles', height(terminal), ...
        'oatof_entry_crossings', entryCount, ...
        'active_at_pulse', activeCount, ...
        'inside_ideal_reference_volume_at_pulse', ...
            nnz(capture.inside_oatof_ideal_reference_volume), ...
        'local_accelerator_exit', localExitCount, ...
        'pulse_time_us', schedule.derived_pulse_time_us, ...
        'pulse_width_us', schedule.pulse_width_us, ...
        'predicted_timing_cohort', ...
            schedule.population_counts.predicted_finite_wall_survivors, ...
        'geometry_domains', geometryInfo.Ndomains, ...
        'mesh_element_counts_by_type', meshElementCounts, ...
        'mesh_elements_total', sum(meshElementCounts), ...
        'dense_trajectories_saved', false, ...
        'pulse_time_convergence_claimed', false, ...
        'time_step_convergence_claimed', false, ...
        's2_stage_passed', false, ...
        's3_stage_passed', false, ...
        'formal_gate_passed', false);
    metricsFid = fopen(metricsPath, 'w');
    assert(metricsFid >= 0, 'Could not create S3 metrics.');
    fprintf(metricsFid, '%s', jsonencode(metrics, 'PrettyPrint', true));
    fclose(metricsFid);
    fprintf(fid, ['SOURCE_PARTICLES=%d\nOATOF_ENTRY=%d\nACTIVE_AT_PULSE=%d\n' ...
        'IDEAL_REFERENCE_AT_PULSE=%d\nLOCAL_ACCELERATOR_EXIT=%d\n' ...
        'PULSE_TIME_US=%.17g\nPULSE_WIDTH_US=%.17g\n' ...
        'MODEL_SAVED=false\nSTATUS=PASS\n'], height(terminal), entryCount, ...
        activeCount, nnz(capture.inside_oatof_ideal_reference_volume), ...
        localExitCount, schedule.derived_pulse_time_us, schedule.pulse_width_us);
    ModelUtil.remove(tag);
catch exception
    fprintf(fid, 'STATUS=FAIL\nERROR=%s\n', ...
        getReport(exception, 'extended', 'hyperlinks', 'off'));
    rethrow(exception)
end
clear cleanup

function [events, capture, localExit] = track_pulsed_particles( ...
    model, comp, inputPath, runtimeDir, s3, s2, rf, oa, schedule, context)
ions = readtable(inputPath, 'VariableNamingRule', 'preserve');
required = {'particle_id','frame_id','clock_epoch_id','instrument_time_us', ...
    'lineage_age_us','particle_age_us','mass_amu','charge_state', ...
    'parent_particle_id','generation','lineage_birth_time_us','particle_birth_time_us', ...
    'mass_to_charge_Th', ...
    'position_x_mm','position_y_mm','position_z_mm', ...
    'velocity_x_m_s','velocity_y_m_s','velocity_z_m_s'};
assert(all(ismember(required, ions.Properties.VariableNames)), ...
    'S3 canonical particle columns are incomplete.');
assert(height(ions) == s3.source.source_particles, ...
    'S3 source particle count differs from the contract.');
assert(numel(unique(ions.mass_amu)) == 1 && numel(unique(ions.charge_state)) == 1, ...
    'S3 minimal runtime requires one mass and charge state.');
sourceCenter = s2.nominal_registration.source_exit_center_instrument_mm(:).';
targetCenter = s2.nominal_registration.target_entry_center_instrument_mm(:).';
assert(all(string(ions.frame_id) == string(s2.nominal_registration.instrument_frame)), ...
    'S3 particle frame differs from S2.');
assert(all(string(ions.clock_epoch_id) == string(s3.source.clock_epoch_id)), ...
    'S3 particle clock epoch differs.');
assert(all(abs(ions.position_x_mm-sourceCenter(1)) <= 1e-12), ...
    'S3 particles must start on the physical RF exit plane.');
assert(all(ions.velocity_x_m_s > 0), 'S3 particles must move toward oaTOF.');
if ~isfolder(runtimeDir), mkdir(runtimeDir); end

cpt = comp.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
cpt.label('S3 shared-clock finite pulse N=100');
cpt.selection.named('sel_vac');
cpt.feature('pp1').set('mp', sprintf('%.17g[kg]', ions.mass_amu(1)*1.66053906660e-27));
cpt.feature('pp1').set('Z', sprintf('%d', round(ions.charge_state(1))));
releaseOffset = s2.no_pulse_field_candidate.boundary_probe_inset_mm;
directMating = abs(s2.nominal_registration.connector_gap_mm) <= 1e-12;
aperture = s2.passive_connector_geometry.downstream_entry_aperture;
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
    releasePath = fullfile(runtimeDir, sprintf('s3_particle_%03d.txt', ions.particle_id(index)));
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

rfScale = rf.mode.rf.amplitude_V_peak / s2.no_pulse_field_candidate.rf_unit_voltage_V;
frequency = rf.mode.rf.frequency_Hz;
phase = rf.mode.rf.phase_rad;
pulseTimeUs = schedule.derived_pulse_time_us;
pulseWidthUs = schedule.pulse_width_us;
gate = sprintf('if(t>=%.17g[us]&&t<%.17g[us],1,0)', ...
    pulseTimeUs, pulseTimeUs+pulseWidthUs);
electricForce = cpt.create('ef1', 'ElectricForce', 3);
electricForce.selection.named('sel_vac');
electricForce.set('E_src', 'userdef');
electricForce.set('E', { ...
    sprintf('%.17g*(-d(Vrf,x))*sin(2*pi*%.17g[Hz]*t+%.17g)+(%s)*(-d(V,x))', rfScale, frequency, phase, gate), ...
    sprintf('%.17g*(-d(Vrf,y))*sin(2*pi*%.17g[Hz]*t+%.17g)+(%s)*(-d(V,y))', rfScale, frequency, phase, gate), ...
    sprintf('%.17g*(-d(Vrf,z))*sin(2*pi*%.17g[Hz]*t+%.17g)+(%s)*(-d(V,z))', rfScale, frequency, phase, gate)});
timeStep = 1/frequency/s2.functional_candidate.rf_steps_per_period;
timeStart = max(0, min(releaseTimeUs(releaseIndices))*1e-6-timeStep);
timeEnd = (pulseTimeUs+pulseWidthUs+s3.waveform.post_pulse_tracking_time_us)*1e-6;
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
x=squeeze(particles.p(:,:,1)); y=squeeze(particles.p(:,:,2)); z=squeeze(particles.p(:,:,3));
vx=squeeze(particles.v(:,:,1)); vy=squeeze(particles.v(:,:,2)); vz=squeeze(particles.v(:,:,3));
if isvector(x), x=x(:); y=y(:); z=z(:); vx=vx(:); vy=vy(:); vz=vz(:); end
assert(size(x,2) == numel(releaseIndices), 'S3 solved particle count differs from released particles.');
localPlane = oa.geometry_mm.accelerator_grid2_z+context.oatof_downstream_buffer_mm-releaseOffset;
eventRows = cell(height(ions), 25);
captureRows = cell(height(ions), 10); captureCount = 0;
exitRows = cell(height(ions), 25); exitCount = 0;
for index = 1:height(ions)
    if directMating
        entryState = make_state(ions.instrument_time_us(index)*1e-6, targetCenter(1), ...
            ions.position_y_mm(index), ions.position_z_mm(index), ...
            ions.velocity_x_m_s(index), ions.velocity_y_m_s(index), ions.velocity_z_m_s(index));
        crossed = true;
    else
        column = releaseColumnByIon(index);
        [entryState, crossed] = interpolate_x_plane(particles.t, x(:,column), y(:,column), z(:,column), ...
            vx(:,column), vy(:,column), vz(:,column), targetCenter(1));
    end
    insideEntry = crossed && ...
        abs(entryState.y_mm-targetCenter(2)) <= aperture.full_width_y_mm/2+1e-12 && ...
        abs(entryState.z_mm-targetCenter(3)) <= aperture.full_height_z_mm/2+1e-12;
    pulseFound = false; activeAtPulse = false;
    if insideEntry
        column = releaseColumnByIon(index);
        [pulseState, pulseFound] = interpolate_time(particles.t, x(:,column), y(:,column), z(:,column), ...
            vx(:,column), vy(:,column), vz(:,column), pulseTimeUs*1e-6);
        activeAtPulse = pulseFound && trajectory_active_at_time( ...
            particles.t, x(:,column), y(:,column), z(:,column), pulseTimeUs*1e-6);
    end
    if activeAtPulse
        source = oa.particle_source;
        insideReference = ...
            abs(pulseState.x_mm-source.center_x_mm) <= source.size_x_mm/2+1e-12 && ...
            abs(pulseState.y_mm-source.center_y_mm) <= source.size_y_mm/2+1e-12 && ...
            abs(pulseState.z_mm-source.center_z_mm) <= source.size_z_mm/2+1e-12;
        captureCount = captureCount+1;
        captureRows(captureCount,:) = {ions.particle_id(index), pulseState.t_s*1e6, ...
            pulseState.x_mm,pulseState.y_mm,pulseState.z_mm,pulseState.vx_m_s, ...
            pulseState.vy_m_s,pulseState.vz_m_s,insideReference,true};
    end
    exited = false;
    if insideEntry
        column = releaseColumnByIon(index);
        [exitState, exited] = interpolate_z_plane(particles.t, x(:,column), y(:,column), z(:,column), ...
            vx(:,column), vy(:,column), vz(:,column), localPlane);
    end
    if exited
        state=exitState; event='local_accelerator_exit'; status='transmitted'; reason='none';
    elseif crossed && ~insideEntry
        state=entryState; event='downstream_entry_wall'; status='lost'; reason='outside_rectangular_oatof_entry';
    else
        column = releaseColumnByIon(index);
        valid = find(isfinite(x(:,column)) & isfinite(y(:,column)) & isfinite(z(:,column)) & ...
            isfinite(vx(:,column)) & isfinite(vy(:,column)) & isfinite(vz(:,column)));
        assert(~isempty(valid), 'S3 released particle has no finite state.');
        last=valid(end); state=make_state(particles.t(last),x(last,column),y(last,column),z(last,column), ...
            vx(last,column),vy(last,column),vz(last,column));
        event='terminal'; status='lost';
        if crossed, reason='accelerator_electrode_or_boundary'; else, reason='connector_wall_or_no_entry'; end
    end
    elapsedUs=max(0,state.t_s*1e6-ions.instrument_time_us(index));
    speedSquared=state.vx_m_s^2+state.vy_m_s^2+state.vz_m_s^2;
    energyEv=0.5*ions.mass_amu(index)*1.66053906660e-27*speedSquared/1.602176634e-19;
    entryLabel='not_reached'; if crossed && insideEntry, entryLabel='transmitted'; elseif crossed, entryLabel='wall_loss'; end
    eventRows(index,:)={ions.particle_id(index),event,status,reason,entryLabel, ...
        string(ions.frame_id(index)),string(ions.clock_epoch_id(index)), ...
        ions.instrument_time_us(index),state.t_s*1e6,ions.lineage_age_us(index)+elapsedUs, ...
        ions.particle_age_us(index)+elapsedUs,elapsedUs,ions.mass_amu(index),ions.charge_state(index), ...
        state.x_mm,state.y_mm,state.z_mm,state.vx_m_s,state.vy_m_s,state.vz_m_s,energyEv, ...
        mod(2*pi*frequency*state.t_s+phase,2*pi),insideEntry,activeAtPulse,exited};
    if exited
        exitCount=exitCount+1;
        exitRows(exitCount,:)={ions.particle_id(index),ions.parent_particle_id(index), ...
            ions.generation(index),'rf_quadrupole_to_oatof_s3', ...
            'oatof_analyzer','local_accelerator_exit',string(ions.frame_id(index)), ...
            string(ions.clock_epoch_id(index)),state.t_s*1e6, ...
            ions.lineage_age_us(index)+elapsedUs,ions.particle_age_us(index)+elapsedUs,elapsedUs, ...
            ions.lineage_birth_time_us(index),ions.particle_birth_time_us(index), ...
            ions.mass_to_charge_Th(index),ions.mass_amu(index),ions.charge_state(index), ...
            state.x_mm,state.y_mm,state.z_mm,state.vx_m_s,state.vy_m_s,state.vz_m_s, ...
            energyEv,mod(2*pi*frequency*state.t_s+phase,2*pi)};
    end
end
events=cell2table(eventRows,'VariableNames',{'particle_id','event','status','terminal_reason', ...
    'oatof_entry_status','frame_id','clock_epoch_id','entry_instrument_time_us','instrument_time_us', ...
    'lineage_age_us','particle_age_us','last_component_elapsed_time_us','mass_amu','charge_state', ...
    'x_mm','y_mm','z_mm','vx_m_s','vy_m_s','vz_m_s','kinetic_energy_eV','rf_phase_rad', ...
    'first_forward_oatof_entry','active_at_pulse','local_accelerator_exit'});
capture=cell2table(captureRows(1:captureCount,:),'VariableNames',{'particle_id','instrument_time_us', ...
    'x_mm','y_mm','z_mm','vx_m_s','vy_m_s','vz_m_s','inside_oatof_ideal_reference_volume','active_at_pulse'});
exitRows=exitRows(1:exitCount,:);
localExit=cell2table(exitRows,'VariableNames',{'particle_id','parent_particle_id','generation', ...
    'source_component_id','target_component_id','state_event','frame_id','clock_epoch_id', ...
    'instrument_time_us','lineage_age_us','particle_age_us','last_component_elapsed_time_us', ...
    'lineage_birth_time_us','particle_birth_time_us','mass_to_charge_Th','mass_amu','charge_state', ...
    'position_x_mm','position_y_mm','position_z_mm','velocity_x_m_s','velocity_y_m_s','velocity_z_m_s', ...
    'kinetic_energy_eV','source_rf_phase_rad'});
end

function active = trajectory_active_at_time(timeS, x, y, z, targetTimeS)
valid=find(isfinite(x)&isfinite(y)&isfinite(z)); active=false;
right=valid(find(timeS(valid)>=targetTimeS,1,'first'));
if isempty(right), return, end
future=valid(valid>=right);
if numel(future)<2, return, end
motion=hypot(diff(x(future)),hypot(diff(y(future)),diff(z(future))));
active=any(motion>1e-12);
end

function [state,found]=interpolate_time(timeS,x,y,z,vx,vy,vz,targetTimeS)
state=struct();found=false;valid=find(isfinite(x)&isfinite(y)&isfinite(z)&isfinite(vx)&isfinite(vy)&isfinite(vz));
if isempty(valid)||targetTimeS<timeS(valid(1))||targetTimeS>timeS(valid(end)),return,end
right=valid(find(timeS(valid)>=targetTimeS,1,'first'));left=valid(find(timeS(valid)<=targetTimeS,1,'last'));
if isempty(left)||isempty(right),return,end
if left==right,fraction=0;else,fraction=(targetTimeS-timeS(left))/(timeS(right)-timeS(left));end
state=interpolate_state(timeS,left,right,fraction,x,y,z,vx,vy,vz);found=true;
end

function [state,found]=interpolate_x_plane(timeS,x,y,z,vx,vy,vz,planeMm)
[state,found]=interpolate_plane(timeS,x,y,z,vx,vy,vz,planeMm,'x');
end

function [state,found]=interpolate_z_plane(timeS,x,y,z,vx,vy,vz,planeMm)
[state,found]=interpolate_plane(timeS,x,y,z,vx,vy,vz,planeMm,'z');
end

function [state,found]=interpolate_plane(timeS,x,y,z,vx,vy,vz,planeMm,axisName)
state=struct();found=false;valid=find(isfinite(x)&isfinite(y)&isfinite(z)&isfinite(vx)&isfinite(vy)&isfinite(vz));
coordinate=x;if axisName=='z',coordinate=z;end
for index=2:numel(valid)
    left=valid(index-1);right=valid(index);
    if coordinate(left)<planeMm&&coordinate(right)>=planeMm&&coordinate(right)>coordinate(left)
        fraction=(planeMm-coordinate(left))/(coordinate(right)-coordinate(left));
        state=interpolate_state(timeS,left,right,fraction,x,y,z,vx,vy,vz);
        if axisName=='x',state.x_mm=planeMm;else,state.z_mm=planeMm;end
        found=true;return
    end
end
end

function state=interpolate_state(timeS,left,right,fraction,x,y,z,vx,vy,vz)
lerp=@(values) values(left)+fraction*(values(right)-values(left));
state=make_state(lerp(timeS),lerp(x),lerp(y),lerp(z),lerp(vx),lerp(vy),lerp(vz));
end

function state=make_state(timeS,x,y,z,vx,vy,vz)
state=struct('t_s',timeS,'x_mm',x,'y_mm',y,'z_mm',z, ...
    'vx_m_s',vx,'vy_m_s',vy,'vz_m_s',vz);
end
