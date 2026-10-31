function receipt=visit_rf_particle_windows(model,solutionTag,datasetTag,physicsIdentifier,windowSamples,consume)
%VISIT_RF_PARTICLE_WINDOWS Read original solution times in bounded windows.
% No trajectory is solved here. Consumer keeps one cross-window adjacent state;
% the first row of later windows overlaps and must not be counted twice.
arguments
 model
 solutionTag (1,:) char
 datasetTag (1,:) char
 physicsIdentifier (1,:) char
 windowSamples (1,1) double {mustBeInteger,mustBeGreaterThanOrEqual(windowSamples,2)}
 consume (1,1) function_handle
end
assert(~isempty(regexp(physicsIdentifier,'^[A-Za-z][A-Za-z0-9_]*$','once')), ...
 'rf:ParticlePhysicsIdentifier','An explicit actual physics variable identifier is required.');
info=mphsolinfo(model,'soltag',solutionTag);
assert(strcmp(info.soltype,'Time'),'RF extraction requires a time-dependent solution.');
times=info.solvals(:);
assert(~isempty(times)&&all(isfinite(times))&&all(diff(times)>0),'Original solution times must be finite and strictly ordered.');
expressions={[physicsIdentifier '.pidx'],'x/1[mm]','y/1[mm]','z/1[mm]', ...
 [physicsIdentifier '.vx/1[m/s]'],[physicsIdentifier '.vy/1[m/s]'],[physicsIdentifier '.vz/1[m/s]']};
timer=tic;windows=0;maxBytes=0;uniqueRows=0;
mphparticleSeconds=0;consumeSeconds=0;
for first=1:windowSamples:numel(times)
 last=min(first+windowSamples-1,numel(times));
 overlap=double(first>1);selected=max(1,first-overlap):last;
 apiTimer=tic;
 data=mphparticle(model,'dataset',datasetTag,'expr',expressions,'t',times(selected)','dataonly','on');
 mphparticleSeconds=mphparticleSeconds+toc(apiTimer);
 assert(isstruct(data)&&all(isfield(data,{'d1','d2','d3','d4','d5','d6','d7'})), ...
  'rf:ParticleShape','Particle expression result lacks the explicit seven arrays.');
 window=struct('time_s',times(selected),'first_solution_index',selected(1), ...
  'last_solution_index',selected(end),'overlap_rows',overlap,'particle_index',data.d1, ...
  'x_mm',data.d2,'y_mm',data.d3,'z_mm',data.d4,'vx_m_s',data.d5, ...
  'vy_m_s',data.d6,'vz_m_s',data.d7);
 shape=size(window.particle_index);
 assert(isnumeric(window.particle_index)&&isreal(window.particle_index)&&ismatrix(window.particle_index)&& ...
  ~isempty(window.particle_index)&&shape(1)==numel(selected), ...
  'rf:ParticleShape','Particle expression time axis differs from requested original times.');
 for key={'x_mm','y_mm','z_mm','vx_m_s','vy_m_s','vz_m_s'}
  assert(isnumeric(window.(key{1}))&&isreal(window.(key{1}))&&ismatrix(window.(key{1}))&& ...
   isequal(size(window.(key{1})),shape),'rf:ParticleShape','Particle expression dimensions differ.');
 end
 bytes=whos('window');maxBytes=max(maxBytes,bytes.bytes);
 consumeTimer=tic;consume(window);consumeSeconds=consumeSeconds+toc(consumeTimer);
 windows=windows+1;uniqueRows=uniqueRows+numel(selected)-overlap;
end
assert(uniqueRows==numel(times),'Window extraction dropped or repeated original time rows.');
receipt=struct('windows',windows,'original_time_rows',numel(times), ...
 'physics_identifier',physicsIdentifier,'window_samples',windowSamples,'maximum_window_bytes',maxBytes,'extract_seconds',toc(timer), ...
 'mphparticle_seconds',mphparticleSeconds,'consume_seconds',consumeSeconds, ...
 'mphparticle_calls',windows,'consumed_time_rows',uniqueRows);
end
