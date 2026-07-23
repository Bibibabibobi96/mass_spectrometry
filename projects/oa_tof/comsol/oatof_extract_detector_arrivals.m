function result = oatof_extract_detector_arrivals(t,x,y,z,detector_z,freeze_tolerance_mm,approach_window_mm,detector_x,detector_y,active_radius_mm)
% Extract first downward detector-plane event after each trajectory turn.
% A clean sign crossing is preferred.  COMSOL Wall/Freeze trajectories may
% stop within a tight tolerance above the plane; those are accepted only when
% the remaining samples form a stationary plateau at the same location.
% Plane arrival and active-area acceptance are deliberately separate: event
% records the trajectory event, while status and hit apply the detector radius.
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

particle_count = size(z,2);
arrival_time = nan(particle_count,1);
arrival_x = nan(particle_count,1);
arrival_y = nan(particle_count,1);
event = strings(particle_count,1);
for particle = 1:particle_count
    last_valid = find(isfinite(z(:,particle)),1,'last');
    if isempty(last_valid), event(particle) = "no_trajectory"; continue; end
    [~,turn_index] = max(z(1:last_valid,particle));
    crossing_index = [];
    for index = turn_index+1:last_valid
        if z(index-1,particle)>=detector_z && z(index,particle)<=detector_z
            crossing_index = index;
            break
        end
    end
    if ~isempty(crossing_index)
        [arrival_time(particle),arrival_x(particle),arrival_y(particle)] = interpolate_event( ...
            t,x(:,particle),y(:,particle),z(:,particle),crossing_index,detector_z);
        event(particle) = "crossing";
        continue
    end

    near_index = find(abs(z(turn_index:last_valid,particle)-detector_z)<=freeze_tolerance_mm,1,'first');
    if isempty(near_index), event(particle) = "no_detector_event"; continue; end
    near_index = turn_index+near_index-1;
    tail = z(near_index:last_valid,particle);
    if all(abs(tail-tail(1))<=freeze_tolerance_mm)
        approach_index = find(z(turn_index:near_index,particle)<=detector_z+approach_window_mm,1,'first');
        approach_index = turn_index+approach_index-1;
        if approach_index>turn_index
            [arrival_time(particle),arrival_x(particle),arrival_y(particle)] = interpolate_event( ...
                t,x(:,particle),y(:,particle),z(:,particle),approach_index,detector_z);
            event(particle) = "frozen_on_detector";
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
    'event',event,'status',status);
end

function [event_time,event_x,event_y] = interpolate_event(t,x,y,z,index,target)
if z(index)==z(index-1)
    fraction = 1;
else
    fraction = (target-z(index-1))/(z(index)-z(index-1));
end
event_time = t(index-1)+fraction*(t(index)-t(index-1));
event_x = x(index-1)+fraction*(x(index)-x(index-1));
event_y = y(index-1)+fraction*(y(index)-y(index-1));
end
