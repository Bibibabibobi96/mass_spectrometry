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

settings=struct('detector_z',detector_z,'freeze_tolerance_mm',freeze_tolerance_mm, ...
 'approach_window_mm',approach_window_mm,'detector_x',detector_x,'detector_y',detector_y,'active_radius_mm',active_radius_mm);
state=oatof_detector_arrival_reducer('init',[],settings,size(z,2));
if ~isempty(t)
 state=oatof_detector_arrival_reducer('survey',state,t,x,y,z,1);
 state=oatof_detector_arrival_reducer('begin_observation',state);
 state=oatof_detector_arrival_reducer('observe',state,t,x,y,z,1);
end
[~,result]=oatof_detector_arrival_reducer('finish',state);
end
