function receipt=export_finite_3d_particle_outputs(model,source,sourceMetadata,context,fid)
%EXPORT_FINITE_3D_PARTICLE_OUTPUTS Extract existing solutions and publish CSV only.
% No solve, parameter mutation, model save or release reconstruction occurs here.
g=validate_finite_extraction_context(source,sourceMetadata,context);
d=context.geometry;censusRadius=context.census_radius_mm;
rf=context.drive;nativeOrder=context.native_order(:)';
primaryCaseId=context.primary_case_id;controlCaseId=context.control_case_id;
eventsPath=context.outputs.events;trajectoryPath=context.outputs.trajectories;
canonicalStatePath=context.outputs.canonical;
primaryCanonicalStatePath=context.outputs.primary_canonical;controlCanonicalStatePath=context.outputs.control_canonical;
primaryTrajectoryPath=context.outputs.primary_trajectories;controlTrajectoryPath=context.outputs.control_trajectories;
    planes=[d.census_plane_z d.rod_z_max d.handoff_plane_z d.entrance_port_plane_z d.exit_port_plane_z];
    regions=zeros(2,2,height(source));
    for particle=1:height(source)
      regions(:,:,particle)=[d.rod_z_min d.rod_z_max;min(source.z_mm(particle),d.rod_z_max) d.rod_z_max];
    end
    [nativeOn,onExtraction]=extract_rf_particle_records(model,context.solution_on,context.dataset_on,'cpt',source.particle_id(nativeOrder)',planes,regions(:,:,nativeOrder),20,256);
    pdOn=cell(size(nativeOn));pdOn(nativeOrder)=nativeOn;
    [nativeZero,zeroExtraction]=extract_rf_particle_records(model,context.solution_zero,context.dataset_zero,'cpt',source.particle_id(nativeOrder)',planes,regions(:,:,nativeOrder),20,256);
    pdZero=cell(size(nativeZero));pdZero(nativeOrder)=nativeZero;
    fprintf(fid,'TIMING_EXTRACT_SECONDS=%.9g RETAINED_SAMPLES=%d\n', ...
      onExtraction.extract_seconds+zeroExtraction.extract_seconds,onExtraction.retained_samples+zeroExtraction.retained_samples);
    massKg=sourceMetadata.mass_amu*1.66053906660e-27;
    [onEvents, onTrajectories] = analyze_particle_case( ...
        pdOn, source, primaryCaseId, d.census_plane_z, g.working_region_radius, censusRadius, ...
        d.rod_z_min, d.rod_z_max, d.entrance_port_plane_z, d.exit_port_plane_z, ...
        g.entrance_interface.aperture_radius_mm, g.exit_interface.aperture_radius_mm,massKg);
    [zeroEvents, zeroTrajectories] = analyze_particle_case( ...
        pdZero, source, controlCaseId, d.census_plane_z, g.working_region_radius, censusRadius, ...
        d.rod_z_min, d.rod_z_max, d.entrance_port_plane_z, d.exit_port_plane_z, ...
        g.entrance_interface.aperture_radius_mm, g.exit_interface.aperture_radius_mm,massKg);
    events = [onEvents; zeroEvents];
    trajectories = [onTrajectories; zeroTrajectories];
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
receipt=struct('primary',onExtraction,'control',zeroExtraction,'native_solves',0);
end

function [events, trajectories] = analyze_particle_case(pd, source, caseId, ...
    censusPlaneZ, usableRadius, censusRadius, rodZMin, rodZMax, entranceCrossingZ, exitCrossingZ, ...
    entrancePortRadius, exitPortRadius,massKg)
particleCount=numel(pd);
eventRows = cell(particleCount, 15);
trajectoryRows = cell(0, 7);
transmitted = false(1, particleCount);
maximumRodRadius = nan(1, particleCount);
entranceRadii = nan(1, particleCount);
exitPortRadii = nan(1, particleCount);
for particle = 1:particleCount
    record=pd{particle};t=record.time_s;x=record.position_mm(:,1);y=record.position_mm(:,2);z=record.position_mm(:,3);
    radius=sqrt(x.^2+y.^2);
    valid = find(isfinite(x) & isfinite(y) & isfinite(z));
    assert(~isempty(valid), 'A finite 3D particle has no trajectory samples.');
    rodSamples = valid(z(valid) >= rodZMin & z(valid) <= rodZMax);
    if isempty(rodSamples)
        maximumRodRadius(particle) = radius(valid(1));
    else
        maximumRodRadius(particle) = max(radius(rodSamples));
    end
    crossing = valid(find(z(valid) >= censusPlaneZ, 1, 'first'));
    entranceCrossing = valid(find(z(valid) >= entranceCrossingZ, 1, 'first'));
    exitCrossing = valid(find(z(valid) >= exitCrossingZ, 1, 'first'));
    if ~isempty(entranceCrossing), entranceRadii(particle) = radius(entranceCrossing); end
    if ~isempty(exitCrossing), exitPortRadii(particle) = radius(exitCrossing); end
    rejectionReason='';
    if ~isempty(crossing) && maximumRodRadius(particle) < usableRadius && ...
            radius(crossing) <= censusRadius
        transmitted(particle) = true;
        terminal = crossing;
    else
        terminal = valid(end);
        if ~isempty(entranceCrossing) && entranceRadii(particle) > entrancePortRadius
            rejectionReason = 'entrance_port_envelope_loss';
        elseif maximumRodRadius(particle) >= usableRadius
            rejectionReason = 'usable_radius_exceeded';
        elseif ~isempty(exitCrossing) && exitPortRadii(particle) > exitPortRadius
            rejectionReason = 'exit_port_envelope_loss';
        elseif ~isempty(crossing) && radius(crossing) > censusRadius
            rejectionReason = 'census_acceptance_radius_exceeded';
        end
    end
    outcome=classify_finite_particle_terminal(record,transmitted(particle),rejectionReason);
    status=outcome.status;reason=outcome.reason;
    if transmitted(particle),reason='near_interface_census_plane';end
    eventRows(particle,:) = {caseId, source.particle_id(particle), status, reason, ...
        source.birth_time_s(particle), t(terminal), x(terminal), ...
        y(terminal), z(terminal), radius(terminal), ...
        maximumRodRadius(particle), entranceRadii(particle), exitPortRadii(particle), ...
        outcome.acceptance_status,outcome.acceptance_reason};
    sampled=find(ismember(record.solution_index,record.trajectory_solution_index));
    for sample = sampled'
        trajectoryRows(end+1,:) = {caseId, source.particle_id(particle), t(sample), ...
            x(sample), y(sample), z(sample), radius(sample)}; %#ok<AGROW>
    end
end

events = cell2table(eventRows, 'VariableNames', {'case_id','particle_id','status','terminal_reason', ...
    'birth_time_s','terminal_time_s','terminal_x_mm','terminal_y_mm','terminal_z_mm', ...
    'terminal_radius_mm','maximum_rod_radius_mm','entrance_port_radius_mm', ...
    'exit_port_radius_mm','acceptance_status','acceptance_reason'});
trajectories = cell2table(trajectoryRows, 'VariableNames', {'case_id','particle_id', ...
    'time_s','x_mm','y_mm','z_mm','radius_mm'});
end


function write_canonical_particle_state(pd,source,path,rodExitZ,handoffZ,censusPlaneZ, ...
    usableRadius,censusRadius,massKg,frequencyHz,phaseRad)
rows=cell(0,19);
for particle=1:numel(pd)
    record=pd{particle};t=record.time_s;x=record.position_mm(:,1);y=record.position_mm(:,2);z=record.position_mm(:,3);
    vx=record.velocity_m_s(:,1);vy=record.velocity_m_s(:,2);vz=record.velocity_m_s(:,3);radius=sqrt(x.^2+y.^2);
    valid=find(isfinite(x(:))&isfinite(y(:))&isfinite(z(:)));
    rodSamples=valid(z(valid)>=min(source.z_mm(particle),rodExitZ)&z(valid)<=rodExitZ);
    if isempty(rodSamples), maxRodRadius=radius(valid(1)); else, maxRodRadius=max(radius(rodSamples)); end
    sourceState=struct('t_s',source.birth_time_s(particle),'x_mm',source.x_mm(particle), ...
        'y_mm',source.y_mm(particle),'z_mm',source.z_mm(particle),'vx_m_s',source.vx_m_s(particle), ...
        'vy_m_s',source.vy_m_s(particle),'vz_m_s',source.vz_m_s(particle));
    rows(end+1,:)=canonical_state_row(source.particle_id(particle),'source','alive','none', ...
        sourceState,source.birth_time_s(particle),frequencyHz,phaseRad,massKg,maxRodRadius); %#ok<AGROW>
    [rodState,rodFound]=interpolate_particle_plane(t,x(:),y(:),z(:), ...
        vx(:),vy(:),vz(:),rodExitZ);
    if rodFound
        rows(end+1,:)=canonical_state_row(source.particle_id(particle),'rod_exit','alive','none', ...
            rodState,source.birth_time_s(particle),frequencyHz,phaseRad,massKg,maxRodRadius); %#ok<AGROW>
    end
    [handoffState,handoffFound]=interpolate_particle_plane(t,x(:),y(:),z(:), ...
        vx(:),vy(:),vz(:),handoffZ);
    if handoffFound
        rows(end+1,:)=canonical_state_row(source.particle_id(particle),'handoff','transmitted','none', ...
            handoffState,source.birth_time_s(particle),frequencyHz,phaseRad,massKg,maxRodRadius); %#ok<AGROW>
    end
    crossing=valid(find(z(valid)>=censusPlaneZ,1,'first')); terminal=valid(end);
    accepted=~isempty(crossing)&&radius(crossing)<=censusRadius&&maxRodRadius<usableRadius;
    rejectionReason='';
    if accepted
        terminal=crossing;
    elseif maxRodRadius>=usableRadius
        rejectionReason='usable_radius_exceeded';
    elseif ~isempty(crossing)&&radius(crossing)>censusRadius
        rejectionReason='census_acceptance_radius_exceeded';
    end
    outcome=classify_finite_particle_terminal(record,accepted,rejectionReason);
    status=outcome.status;reason=outcome.reason;
    terminalState=struct('t_s',t(terminal),'x_mm',x(terminal),'y_mm',y(terminal), ...
        'z_mm',z(terminal),'vx_m_s',vx(terminal),'vy_m_s',vy(terminal), ...
        'vz_m_s',vz(terminal));
    rows(end+1,:)=canonical_state_row(source.particle_id(particle),'terminal',status,reason, ...
        terminalState,source.birth_time_s(particle),frequencyHz,phaseRad,massKg,maxRodRadius, ...
        outcome.acceptance_status,outcome.acceptance_reason); %#ok<AGROW>
end
names={'particle_id','event','status','terminal_reason','time_us','elapsed_time_us','rf_phase_rad', ...
    'axial_z_mm','transverse_x_mm','transverse_y_mm','velocity_axial_m_s','velocity_x_m_s', ...
    'velocity_y_m_s','kinetic_energy_eV','radial_position_mm','divergence_angle_deg','max_rod_radius_mm', ...
    'acceptance_status','acceptance_reason'};
writetable(cell2table(rows,'VariableNames',names),path);
end

function row=canonical_state_row(particleId,event,status,reason,state,birthTime,frequencyHz,phaseRad,massKg,maxRodRadius,acceptanceStatus,acceptanceReason)
if nargin<11,acceptanceStatus='not_evaluated';acceptanceReason='none';end
speedSquared=state.vx_m_s^2+state.vy_m_s^2+state.vz_m_s^2;
energyEv=0.5*massKg*speedSquared/1.602176634e-19;
row={particleId,event,status,reason,state.t_s*1e6,(state.t_s-birthTime)*1e6, ...
    mod(2*pi*frequencyHz*state.t_s+phaseRad,2*pi),state.z_mm,state.x_mm,state.y_mm, ...
    state.vz_m_s,state.vx_m_s,state.vy_m_s,energyEv,hypot(state.x_mm,state.y_mm), ...
    atan2d(hypot(state.vx_m_s,state.vy_m_s),state.vz_m_s),maxRodRadius,acceptanceStatus,acceptanceReason};
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
