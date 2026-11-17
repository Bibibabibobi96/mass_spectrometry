function [state,result]=oatof_detector_arrival_reducer(action,state,varargin)
%OATOF_DETECTOR_ARRIVAL_REDUCER Two-pass sufficient statistics for detector events.
% Fixed project scientific algorithm; no solver, file, workflow or sampling policy.
result=[];
switch action
 case 'init'
  settings=varargin{1};n=varargin{2};state=initialState(settings,n);
 case 'survey'
  [state,rows]=checkBlock(state,varargin{:},'survey');
  x=varargin{2};y=varargin{3};z=varargin{4};first=varargin{5};
  for row=rows
   j=first+row-1;pos=[x(row,:)' y(row,:)' z(row,:)'];finiteZ=isfinite(pos(:,3));
   if j==1,state.initial_xyz=pos;end
   state.last_raw_xyz=pos;
   state.started=state.started|finiteZ;
   bad=any(~isfinite(pos),2);state.pending_bad=state.pending_bad|(state.started&bad);
   state.invalid(finiteZ)=state.invalid(finiteZ)|state.pending_bad(finiteZ);
   state.pending_bad(finiteZ)=false;
   born=finiteZ&isnan(state.first_valid);state.first_valid(born)=j;
   state.last_valid(finiteZ)=j;state.final_xyz(finiteZ,:)=pos(finiteZ,:);
   higher=finiteZ&(isnan(state.maximum_z)|pos(:,3)>state.maximum_z);
   state.maximum_z(higher)=pos(higher,3);state.turn_index(higher)=j;
   good=all(isfinite(pos),2);state.coordinate_scale(good,:)=max(state.coordinate_scale(good,:),abs(pos(good,:)));
   raw=~isnan(pos(:,3))&(isnan(state.raw_maximum_z)|pos(:,3)>state.raw_maximum_z);
   state.raw_maximum_z(raw)=pos(raw,3);
  end
 case 'begin_observation'
  state.coordinate_roundoff=128*eps(state.coordinate_scale);
  state.suffix_start=state.turn_index;
 case 'observe'
  [state,rows]=checkBlock(state,varargin{:},'observe');
  t=varargin{1};x=varargin{2};y=varargin{3};z=varargin{4};first=varargin{5};
  for row=rows
   j=first+row-1;pos=[x(row,:)' y(row,:)' z(row,:)'];
   active=~state.invalid&j>=state.turn_index&j<=state.last_valid;
   matches=all(abs(pos-state.final_xyz)<=state.coordinate_roundoff,2);
   reset=active&~matches;state.suffix_start(reset)=j+1;
   starts=active&matches&state.suffix_start==j;state.suffix_time(starts)=t(row);
   state.near=state.near|(active&abs(pos(:,3)-state.settings.detector_z)<=state.settings.freeze_tolerance_mm);
   after=active&j>state.turn_index;
   negative=pos(:,3)<state.settings.detector_z;positive=pos(:,3)>state.settings.detector_z;
   confirmed=after&state.pending_zero&negative&~state.cross_found;
   state.cross_pair(confirmed,:)=state.pending_pair(confirmed,:);
   state.cross_end(confirmed)=state.pending_end(confirmed);state.cross_found(confirmed)=true;
   state.pending_zero(after&(negative|positive))=false;
   crossing=after&~state.cross_found&state.previous_xyz(:,3)>state.settings.detector_z&pos(:,3)<=state.settings.detector_z;
   pair=[repmat(state.previous_time,state.n,1),repmat(t(row),state.n,1),state.previous_xyz,pos];
   direct=crossing&negative;state.cross_pair(direct,:)=pair(direct,:);state.cross_end(direct)=j;state.cross_found(direct)=true;
   pending=crossing&~negative;state.pending_pair(pending,:)=pair(pending,:);state.pending_end(pending)=j;state.pending_zero(pending)=true;
   approach=after&~state.approach_found&pos(:,3)<=state.settings.detector_z+state.settings.approach_window_mm&pos(:,3)<state.previous_xyz(:,3);
   state.approach_pair(approach,:)=pair(approach,:);state.approach_end(approach)=j;state.approach_found(approach)=true;
   state.previous_xyz=pos;state.previous_time=t(row);
  end
 case 'finish'
  assert(state.survey_last==state.observe_last,'oatof:DetectorPass','Observation pass lacks original rows.');
  result=classify(state);
 otherwise
  error('oatof:DetectorReducerAction','Unknown detector algorithm phase.');
end
end
function state=initialState(settings,n)
state=struct('settings',settings,'n',n,'started',false(n,1),'pending_bad',false(n,1), ...
 'invalid',false(n,1),'first_valid',nan(n,1),'last_valid',nan(n,1), ...
 'maximum_z',nan(n,1),'raw_maximum_z',nan(n,1),'turn_index',nan(n,1), ...
 'final_xyz',nan(n,3),'initial_xyz',nan(n,3),'last_raw_xyz',nan(n,3), ...
 'coordinate_scale',repmat(max(ones(1,3),abs([settings.detector_x settings.detector_y settings.detector_z])),n,1), ...
 'coordinate_roundoff',nan(n,3),'suffix_start',nan(n,1),'suffix_time',nan(n,1), ...
 'near',false(n,1),'pending_zero',false(n,1),'pending_pair',nan(n,8),'pending_end',nan(n,1), ...
 'cross_found',false(n,1),'cross_pair',nan(n,8),'cross_end',nan(n,1), ...
 'approach_found',false(n,1),'approach_pair',nan(n,8),'approach_end',nan(n,1), ...
 'previous_xyz',nan(n,3),'previous_time',NaN, ...
 'survey_last',0,'survey_time',NaN,'survey_xyz',nan(n,3), ...
 'observe_last',0,'observe_time',NaN,'observe_xyz',nan(n,3));
end
function [state,rows]=checkBlock(state,t,x,y,z,first,phase)
assert(isequal(size(x),size(y),size(z))&&size(x,1)==numel(t)&&size(x,2)==state.n, ...
 'oatof:SavedPopulation','Particle block shape differs from the frozen population.');
assert(isreal(t)&&all(isfinite(t))&&all(diff(t)>0),'oatof:InvalidDetectorTimes','Sample times must be finite and strictly increasing.');
lastKey=[phase '_last'];timeKey=[phase '_time'];xyzKey=[phase '_xyz'];previous=state.(lastKey);
rows=1:numel(t);
if previous>0&&first==previous
 assert(t(1)==state.(timeKey)&&isequaln([x(1,:)' y(1,:)' z(1,:)'],state.(xyzKey)), ...
  'oatof:SavedOverlap','An original adjacent state changed across API blocks.');
 rows=2:numel(t);
else
 assert(first==previous+1,'oatof:DetectorBlock','Original particle rows are missing or repeated.');
 if previous>0,assert(t(1)>state.(timeKey),'oatof:InvalidDetectorTimes','Original time order changed.');end
end
state.(lastKey)=first+numel(t)-1;state.(timeKey)=t(end);state.(xyzKey)=[x(end,:)' y(end,:)' z(end,:)'];
end
function result=classify(state)
n=state.n;settings=state.settings;arrival_time=nan(n,1);arrival_x=nan(n,1);arrival_y=nan(n,1);
segment_start_index=nan(n,1);segment_end_index=nan(n,1);plateau_start_index=nan(n,1);event=strings(n,1);
for particle=1:n
 if isnan(state.first_valid(particle)),event(particle)="no_trajectory";continue;end
 if state.invalid(particle),event(particle)="invalid_trajectory";continue;end
 frozen=abs(state.final_xyz(particle,3)-settings.detector_z)<=settings.freeze_tolerance_mm&&state.suffix_start(particle)<state.last_valid(particle);
 if frozen,plateau_start_index(particle)=state.suffix_start(particle);end
 if state.cross_found(particle)&&(~frozen||state.cross_end(particle)<state.suffix_start(particle))
  [arrival_time(particle),arrival_x(particle),arrival_y(particle)]=interpolate_pair(state.cross_pair(particle,:),settings.detector_z);
  segment_end_index(particle)=state.cross_end(particle);segment_start_index(particle)=segment_end_index(particle)-1;
  event(particle)="crossing";continue;
 end
 if ~state.near(particle),event(particle)="no_detector_event";continue;end
 if frozen
  if state.approach_found(particle)&&state.approach_end(particle)<state.suffix_start(particle)
   pair=state.approach_pair(particle,:);
   segment_end_index(particle)=state.approach_end(particle);segment_start_index(particle)=segment_end_index(particle)-1;
   [arrival_time(particle),arrival_x(particle),arrival_y(particle)]=interpolate_pair(pair,settings.detector_z);
   time_roundoff=8*eps(max(abs([pair(1:2) state.suffix_time(particle)])));
   if arrival_time(particle)>=pair(2)-time_roundoff&&arrival_time(particle)<=state.suffix_time(particle)+time_roundoff
    event(particle)="frozen_on_detector";
   else
    arrival_time(particle)=NaN;arrival_x(particle)=NaN;arrival_y(particle)=NaN;event(particle)="freeze_extrapolation_outside_interval";
   end
  else,event(particle)="freeze_without_approach_segment";
  end
 else,event(particle)="near_detector_without_freeze";
 end
end
radius_mm=hypot(arrival_x-settings.detector_x,arrival_y-settings.detector_y);plane_event=isfinite(arrival_time);hit=plane_event&radius_mm<=settings.active_radius_mm;
status=event;status(plane_event&~hit)="outside_active_radius";status(hit)="detector_hit";
result=struct('time_s',arrival_time,'x_mm',arrival_x,'y_mm',arrival_y,'radius_mm',radius_mm, ...
 'plane_event',plane_event,'hit',hit,'event',event,'status',status, ...
 'segment_start_index',segment_start_index,'segment_end_index',segment_end_index,'plateau_start_index',plateau_start_index);
end
function [time,x,y]=interpolate_pair(pair,target)
% Pair: ta,tb,xa,ya,za,xb,yb,zb. Keep original scalar arithmetic order.
fraction=(target-pair(5))/(pair(8)-pair(5));
time=pair(1)+fraction*(pair(2)-pair(1));x=pair(3)+fraction*(pair(6)-pair(3));y=pair(4)+fraction*(pair(7)-pair(4));
end
