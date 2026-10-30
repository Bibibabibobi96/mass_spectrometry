function [particles,receipt]=extract_rf_particle_records(model,solutionTag,datasetTag,physicsIdentifier,particleIds,planesMm,rodBoundsMm,trajectoryStride,windowSamples)
%EXTRACT_RF_PARTICLE_RECORDS Preserve event brackets, maxima and requested traces.
% Retained scientific samples are drawn from the original solved time inventory.
% Original particle IDs remain the caller's frozen source-row mapping; pidx is
% checked against that solver release order, never substituted as a new ID.
arguments
 model
 solutionTag (1,:) char
 datasetTag (1,:) char
 physicsIdentifier (1,:) char
 particleIds (1,:) double {mustBeInteger,mustBePositive}
 planesMm (1,:) double
 rodBoundsMm double
 trajectoryStride (1,1) double {mustBeInteger,mustBePositive}
 windowSamples (1,1) double {mustBeInteger,mustBeGreaterThanOrEqual(windowSamples,2)}
end
particleCount=numel(particleIds);
assert(particleCount>0&&all(isfinite(particleIds))&&numel(unique(particleIds))==particleCount, ...
 'rf:ParticleIds','Frozen source IDs must be nonempty and unique.');
lastWindow=cell(1,particleCount);
seenActive=false(1,particleCount);ended=false(1,particleCount);
finalInventoryIndex=0;finalInventoryTime=NaN;
assert(size(rodBoundsMm,2)==2&&(size(rodBoundsMm,3)==1||size(rodBoundsMm,3)==particleCount), ...
 'rf:ParticleRegions','Rod regions must have two bounds and either shared or per-particle pages.');
particles=cell(1,particleCount);seenValid=zeros(1,particleCount);
for index=1:particleCount
 particles{index}=struct('particle_id',particleIds(index),'solution_index',zeros(0,1),'time_s',zeros(0,1), ...
  'position_mm',zeros(0,3),'velocity_m_s',zeros(0,3),'trajectory_solution_index',zeros(0,1));
end
receipt=visit_rf_particle_windows(model,solutionTag,datasetTag,physicsIdentifier,windowSamples,@consume);
assert(finalInventoryIndex==receipt.original_time_rows&&isfinite(finalInventoryTime), ...
 'rf:ParticleInventory','Final original solution inventory was not observed.');
receipt.solution_end_time_s=finalInventoryTime;
for index=1:particleCount
 record=particles{index};assert(~isempty(record.solution_index),'rf:ParticleActiveState','Particle has no finite trajectory samples.');
 [record.solution_index,keep]=unique(record.solution_index,'sorted');
 record.time_s=record.time_s(keep);record.position_mm=record.position_mm(keep,:);record.velocity_m_s=record.velocity_m_s(keep,:);
 record.trajectory_solution_index=unique([record.trajectory_solution_index;record.solution_index(end)]);
 record.terminal_observation=struct('solution_end_index',receipt.original_time_rows, ...
  'solution_end_time_s',finalInventoryTime,'last_finite_solution_index',record.solution_index(end), ...
  'last_finite_time_s',record.time_s(end), ...
  'finite_at_solution_end',logical(record.solution_index(end)==receipt.original_time_rows), ...
  'finite_track_ended',logical(ended(index)),'native_termination_cause','not_observed');
 particles{index}=record;
end
receipt.retained_samples=sum(cellfun(@(p)numel(p.time_s),particles));
receipt.retained_particle_count=particleCount;
 function consume(window)
  finalInventoryIndex=window.last_solution_index;finalInventoryTime=window.time_s(end);
  assert(size(window.x_mm,2)==particleCount,'Solved mother particle count differs from frozen source.');
  globalIndices=(window.first_solution_index:window.last_solution_index)';
  assigned=false(1,particleCount);
  for column=1:particleCount
   p=[window.x_mm(:,column),window.y_mm(:,column),window.z_mm(:,column)];
   v=[window.vx_m_s(:,column),window.vy_m_s(:,column),window.vz_m_s(:,column)];
   ids=window.particle_index(:,column);
   active=all(isfinite(p),2);
   inactive=all(isnan(p),2);
   assert(all(isfinite(p(:))|isnan(p(:)))&&all(isfinite(v(:))|isnan(v(:)))&& ...
    all(active|inactive)&&all(active==all(isfinite(v),2))&& ...
    all(inactive==all(isnan(v),2))&& ...
    all(isfinite(ids(active))), 'rf:ParticleActiveState', ...
    'Every active position must have finite complete position, velocity and native ID.');
   nativeIds=ids(isfinite(ids));
   if isempty(nativeIds)
    assert(~any(active),'rf:ParticleIndex','An active particle has no native ID.');continue;
   end
   particle=nativeIds(1);
   assert(particle==fix(particle)&&particle>=1&&particle<=particleCount&& ...
    all(nativeIds==particle)&&~assigned(particle), 'rf:ParticleIndex', ...
    'Native particle IDs must uniquely map to the frozen release order.');
   assigned(particle)=true;
   previouslyActive=seenActive(particle);
   for row=(window.overlap_rows+1):numel(active)
    if active(row)
     assert(~ended(particle),'rf:ParticleLifecycleGap', ...
      'An active state resumed after missing positions; interpolation across that gap is unknown.');
     seenActive(particle)=true;
    elseif seenActive(particle)
     ended(particle)=true;
    end
   end
   if window.overlap_rows
    previous=lastWindow{particle};
    unbornOverlap=isempty(previous)&&~previouslyActive&& ...
     all(isnan(p(1,:)))&&all(isnan(v(1,:)));
    assert(unbornOverlap||(~isempty(previous)&&previous.index==globalIndices(1)&& ...
     isequaln(previous.position,p(1,:))&&isequaln(previous.velocity,v(1,:))&& ...
     isequaln(previous.native_id,ids(1))&&previous.time==window.time_s(1)), ...
     'rf:ParticleOverlap','Cross-window adjacent state changed.');
   end
   lastWindow{particle}=struct('index',globalIndices(end),'position',p(end,:), ...
    'velocity',v(end,:),'native_id',ids(end),'time',window.time_s(end));
   finite=all(isfinite(p),2);valid=find(finite);
   if isempty(valid),continue;end
   chosen=[valid(1);valid(end)];
   % Whole-solution maxima are among window maxima, so retaining each is exact.
   page=min(particle,size(rodBoundsMm,3));regions=rodBoundsMm(:,:,page);
   for region=1:size(regions,1)
    rod=valid(p(valid,3)>=regions(region,1)&p(valid,3)<=regions(region,2));
    if ~isempty(rod)
     [~,maximum]=max(sqrt(p(rod,1).^2+p(rod,2).^2));chosen=[chosen;rod(maximum)]; %#ok<AGROW>
    end
   end
   crossingValid=find(finite&all(isfinite(v),2));
   for plane=planesMm
    for step=2:numel(crossingValid)
     a=crossingValid(step-1);b=crossingValid(step);
     if b~=a+1,continue;end % Missing lifecycle samples are not an interpolation bracket.
     if (p(a,3)<plane&&p(b,3)>=plane)||(p(a,3)>plane&&p(b,3)<=plane)
      chosen=[chosen;a;b]; %#ok<AGROW>
     end
    end
    % Existing census logic uses first >= plane, distinct from interpolation.
    firstAbove=valid(find(p(valid,3)>=plane,1));chosen=[chosen;firstAbove]; %#ok<AGROW>
   end
   fresh=valid(valid>window.overlap_rows);
   ordinals=seenValid(particle)+(1:numel(fresh));
   sampled=fresh(mod(ordinals-1,trajectoryStride)==0);
   seenValid(particle)=seenValid(particle)+numel(fresh);
   chosen=unique([chosen;sampled]);
   record=particles{particle};record.solution_index=[record.solution_index;globalIndices(chosen)];
   record.time_s=[record.time_s;window.time_s(chosen)];record.position_mm=[record.position_mm;p(chosen,:)];
   record.velocity_m_s=[record.velocity_m_s;v(chosen,:)];
   record.trajectory_solution_index=[record.trajectory_solution_index;globalIndices(sampled)];
   particles{particle}=record;
  end
  ended(~assigned&seenActive)=true;
 end
end
