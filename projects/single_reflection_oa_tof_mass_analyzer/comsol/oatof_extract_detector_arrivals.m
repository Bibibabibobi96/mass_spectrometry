function result = oatof_extract_detector_arrivals(t,x,y,z,detector_z,freeze_tolerance_mm,approach_window_mm,detector_x,detector_y,active_radius_mm)
% Extract first downward detector-plane event after each trajectory turn.
% A clean sign crossing is interpolated. COMSOL Wall/Freeze trajectories may
% stop on either side of the plane within freeze_tolerance_mm. A terminal
% plateau takes precedence over an apparent crossing into that plateau:
% its sampled start is not the arrival time. Stationarity means the terminal
% XYZ samples agree within 128 ULP at their coordinate scales (minimum 1 mm),
% a representation allowance rather than a physical stop/error guarantee.
% Extrapolate the earlier downward
% approach instead, using two samples before the plateau. Without that
% evidence, a particle already stationary at the plane has no arrival event.
% Plane arrival and active-area acceptance are deliberately separate: event
% records the trajectory event, while status and hit apply the detector radius.
% Returned segment/plateau indices refer to the original input rows; rejected
% extrapolations retain their attempted segment indices for diagnostics.
arguments
    t (:,1) double
    x double
    y double
    z double
    detector_z (1,1) double
    freeze_tolerance_mm (1,1) double {mustBeNonnegative} = 1e-3
    approach_window_mm (1,1) double {mustBePositive} = 0.5
    detector_x (1,1) double = 0
    detector_y (1,1) double = 0
    active_radius_mm (1,1) double {mustBePositive} = Inf
end
assert(isequal(size(x),size(y),size(z)), 'Particle coordinate arrays must have equal size.');
assert(size(z,1)==numel(t), 'Coordinate rows must match the time vector.');
assert(isreal(t) && all(isfinite(t)) && all(diff(t)>0), ...
    'oatof:InvalidDetectorTimes', 'Sample times must be finite and strictly increasing.');

particle_count = size(z,2);
arrival_time = nan(particle_count,1);
arrival_x = nan(particle_count,1);
arrival_y = nan(particle_count,1);
segment_start_index = nan(particle_count,1);
segment_end_index = nan(particle_count,1);
plateau_start_index = nan(particle_count,1);
event = strings(particle_count,1);
for particle = 1:particle_count
    last_valid = find(isfinite(z(:,particle)),1,'last');
    if isempty(last_valid), event(particle) = "no_trajectory"; continue; end
    first_valid = find(isfinite(z(:,particle)),1,'first');
    valid_range = first_valid:last_valid;
    if any(~isfinite(x(valid_range,particle))) || any(~isfinite(y(valid_range,particle))) ...
            || any(~isfinite(z(valid_range,particle)))
        event(particle) = "invalid_trajectory";
        continue
    end
    [~,turn_index] = max(z(valid_range,particle));
    turn_index = first_valid+turn_index-1;
    near_index = find(abs(z(turn_index:last_valid,particle)-detector_z)<=freeze_tolerance_mm,1,'first');
    is_frozen = false;
    if abs(z(last_valid,particle)-detector_z)<=freeze_tolerance_mm
        % Being near the plane does not mean that the particle has stopped.
        % Locate a constant terminal suffix using only floating-point-scale
        % variation, independently of the physical plane-distance tolerance.
        coordinate_scale = max([ones(1,3); ...
            abs([x(valid_range,particle),y(valid_range,particle),z(valid_range,particle)]); ...
            abs([detector_x,detector_y,detector_z])],[],1);
        coordinate_roundoff = 128*eps(coordinate_scale);
        final_position = [x(last_valid,particle),y(last_valid,particle),z(last_valid,particle)];
        plateau_index = last_valid;
        while plateau_index>turn_index ...
                && all(abs([x(plateau_index-1,particle),y(plateau_index-1,particle), ...
                    z(plateau_index-1,particle)]-final_position)<=coordinate_roundoff)
            plateau_index = plateau_index-1;
        end
        is_frozen = plateau_index<last_valid;
        if is_frozen, plateau_start_index(particle) = plateau_index; end
    end
    crossing_index = [];
    for index = turn_index+1:last_valid
        if is_frozen && index>=plateau_index, break; end
        % A zero sample alone is not proof of a crossing or a freeze time.
        if z(index-1,particle)>detector_z && z(index,particle)<=detector_z
            next_side_index = index;
            while next_side_index<last_valid && z(next_side_index,particle)==detector_z
                next_side_index = next_side_index+1;
            end
            if z(next_side_index,particle)<detector_z
                crossing_index = index;
                break
            end
        end
    end
    if ~isempty(crossing_index)
        [arrival_time(particle),arrival_x(particle),arrival_y(particle)] = interpolate_event( ...
            t,x(:,particle),y(:,particle),z(:,particle),crossing_index,detector_z);
        segment_start_index(particle) = crossing_index-1;
        segment_end_index(particle) = crossing_index;
        event(particle) = "crossing";
        continue
    end

    if isempty(near_index), event(particle) = "no_detector_event"; continue; end
    if is_frozen
        % Keep the existing approach window, but never estimate velocity from
        % a segment ending at a frozen sample. This also works when the input
        % window starts inside the approach window and contains a valid slope.
        approach_indices = (turn_index+1:plateau_index-1).';
        approach_index = approach_indices(find( ...
            z(approach_indices,particle)<=detector_z+approach_window_mm ...
            & z(approach_indices,particle)<z(approach_indices-1,particle),1,'first'));
        if ~isempty(approach_index)
            segment_start_index(particle) = approach_index-1;
            segment_end_index(particle) = approach_index;
            [arrival_time(particle),arrival_x(particle),arrival_y(particle)] = interpolate_event( ...
                t,x(:,particle),y(:,particle),z(:,particle),approach_index,detector_z);
            % COMSOL time interpolation can leave a moving transition sample
            % after the approach line reaches the plane. That sample is not
            % a lower event-time bound. Require forward extrapolation from
            % the selected approach segment and arrival by the first plateau.
            % The 8 ULP endpoint allowance covers arithmetic only, not physical
            % timing error; this estimate is not a native event-time readout.
            time_roundoff = 8*eps(max(abs(t([approach_index-1,approach_index,plateau_index]))));
            if arrival_time(particle)>=t(approach_index)-time_roundoff ...
                    && arrival_time(particle)<=t(plateau_index)+time_roundoff
                event(particle) = "frozen_on_detector";
            else
                arrival_time(particle) = NaN;
                arrival_x(particle) = NaN;
                arrival_y(particle) = NaN;
                event(particle) = "freeze_extrapolation_outside_interval";
            end
        else
            event(particle) = "freeze_without_approach_segment";
        end
    else
        event(particle) = "near_detector_without_freeze";
    end
end
radius_mm = hypot(arrival_x-detector_x,arrival_y-detector_y);
plane_event = isfinite(arrival_time);
hit = plane_event & radius_mm<=active_radius_mm;
status = event;
status(plane_event & ~hit) = "outside_active_radius";
status(hit) = "detector_hit";
result = struct('time_s',arrival_time,'x_mm',arrival_x,'y_mm',arrival_y, ...
    'radius_mm',radius_mm,'plane_event',plane_event,'hit',hit, ...
    'event',event,'status',status, ...
    'segment_start_index',segment_start_index,'segment_end_index',segment_end_index, ...
    'plateau_start_index',plateau_start_index);
end

function [event_time,event_x,event_y] = interpolate_event(t,x,y,z,index,target)
fraction = (target-z(index-1))/(z(index)-z(index-1));
event_time = t(index-1)+fraction*(t(index)-t(index-1));
event_x = x(index-1)+fraction*(x(index)-x(index-1));
event_y = y(index-1)+fraction*(y(index)-y(index-1));
end
