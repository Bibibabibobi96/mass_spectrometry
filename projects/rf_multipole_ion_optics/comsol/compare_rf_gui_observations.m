function report=compare_rf_gui_observations(saved,current,savedOutcomes,currentOutcomes)
%COMPARE_RF_GUI_OBSERVATIONS Diagnose shared stored states without inventing a tolerance.
% Inputs are the existing extract_rf_particle_records observation envelopes:
% position_mm in mm, velocity_m_s in m/s, time_s on the same absolute clock.
% Use load(snapshot).observation for MAT-only analysis; no COMSOL API is used.
% Optional project outcomes come from the caller's existing physics classifier.
% With two arguments only, outcome comparison is explicitly not computable.
% Source transport precision is not an integration or repeated-solve budget.
assert(nargin==2||nargin==4,'rfquad:GuiObservation','Provide two observations and optionally both project outcome arrays.');
outcomesAvailable=nargin==4;
if outcomesAvailable
 assert(iscell(savedOutcomes)&&iscell(currentOutcomes)&&numel(savedOutcomes)==numel(saved.records)&& ...
  numel(currentOutcomes)==numel(current.records),'rfquad:GuiObservation','Both project outcome arrays must cover the complete mother population.');
else
 savedOutcomes={};currentOutcomes={};
end
assert(all(isfinite(saved.time_s))&&all(diff(saved.time_s)>0)&&all(isfinite(current.time_s))&&all(diff(current.time_s)>0), ...
 'rfquad:GuiObservation','Each actual stored clock must be finite and strictly increasing.');
common=intersect(saved.time_s,current.time_s);
assert(numel(saved.records)==numel(current.records)&&~isempty(saved.records), ...
 'rfquad:GuiParityIds','GUI complete original mother population differs.');
maxPosition=[];maxVelocity=[];sumP=0;sumV=0;components=0;states=0;
ids=zeros(1,numel(saved.records));details=cell(1,numel(ids));
activeDifferences=0;terminalDifferences=0;outcomeDifferences=0;
for index=1:numel(saved.records)
 a=saved.records{index};b=current.records{index};ids(index)=a.particle_id;
 validateGuiObservationRecord(a,saved.time_s);validateGuiObservationRecord(b,current.time_s);
 assert(a.particle_id==b.particle_id,'rfquad:GuiParityIds','GUI reordered or replaced original IDs.');
 [activeA,ia]=ismember(common,a.time_s);[activeB,ib]=ismember(common,b.time_s);
 paired=activeA&activeB;changedMask=nnz(activeA~=activeB);activeDifferences=activeDifferences+changedMask;
 terminalChanged=~isequaln(a.terminal_observation,b.terminal_observation);
 outcomeChanged=[];
 if outcomesAvailable,outcomeChanged=~isequaln(savedOutcomes{index},currentOutcomes{index});outcomeDifferences=outcomeDifferences+outcomeChanged;end
 terminalDifferences=terminalDifferences+terminalChanged;
 item=struct('particle_id',a.particle_id,'shared_finite_state_count',nnz(paired), ...
  'active_mask_difference_count',changedMask,'terminal_observation_changed',terminalChanged, ...
  'project_outcome_changed',outcomeChanged,'maximum_position_error_mm',[],'maximum_velocity_error_m_s',[]);
 if any(paired)
  dp=a.position_mm(ia(paired),:)-b.position_mm(ib(paired),:);
  dv=a.velocity_m_s(ia(paired),:)-b.velocity_m_s(ib(paired),:);
  item.maximum_position_error_mm=max(abs(dp),[],'all');item.maximum_velocity_error_m_s=max(abs(dv),[],'all');
  maxPosition=max([maxPosition item.maximum_position_error_mm]);maxVelocity=max([maxVelocity item.maximum_velocity_error_m_s]);
  sumP=sumP+sum(dp.^2,'all');sumV=sumV+sum(dv.^2,'all');components=components+numel(dp);states=states+nnz(paired);
 end
 details{index}=item;
end
assert(numel(unique(ids))==numel(ids),'rfquad:GuiParityIds','Original particle IDs must be unique.');
if ~outcomesAvailable,outcomeDifferences=[];end
rmsP=[];rmsV=[];if components>0,rmsP=sqrt(sumP/components);rmsV=sqrt(sumV/components);end
report=struct('status','DIAGNOSTIC_ONLY','scientific_result','NOT_EVALUATED', ...
 'observed_state_parity_verified',false,'numerical_equivalence_status','NOT_EVALUATED', ...
 'particle_ids',ids,'particles',numel(ids),'common_stored_time_count',numel(common), ...
 'compared_finite_state_count',states,'maximum_position_error_mm',maxPosition, ...
 'maximum_velocity_error_m_s',maxVelocity,'rms_position_component_error_mm',rmsP, ...
 'rms_velocity_component_error_m_s',rmsV,'active_mask_difference_count',activeDifferences, ...
 'terminal_observation_difference_count',terminalDifferences,'project_outcome_difference_count',outcomeDifferences,'project_outcomes_compared',outcomesAvailable, ...
 'observation_window_equal',isequal(saved.time_s([1 end]),current.time_s([1 end])), ...
 'stored_time_count_before',numel(saved.time_s),'stored_time_count_after',numel(current.time_s), ...
 'per_particle_diagnostics',{details},'terminal_outcomes',{currentOutcomes});
end

function validateGuiObservationRecord(record,inventory)
rows=numel(record.time_s);
assert(rows>0&&all(isfinite(record.time_s))&&all(diff(record.time_s)>0)&& ...
 all(ismember(record.time_s,inventory))&&isequal(size(record.position_mm),[rows 3])&& ...
 isequal(size(record.velocity_m_s),[rows 3])&&all(isfinite(record.position_mm),'all')&& ...
 all(isfinite(record.velocity_m_s),'all'),'rfquad:GuiObservation','A stored original-ID observation has invalid clock or complete finite6D.');
terminal=record.terminal_observation;
assert(terminal.solution_end_time_s==inventory(end)&&terminal.last_finite_time_s==record.time_s(end)&& ...
 terminal.finite_at_solution_end==(record.time_s(end)==inventory(end))&& ...
 ~(terminal.finite_at_solution_end&&terminal.finite_track_ended), ...
 'rfquad:GuiObservation','Within-run terminal observation contradicts its own stored clock.');
end
