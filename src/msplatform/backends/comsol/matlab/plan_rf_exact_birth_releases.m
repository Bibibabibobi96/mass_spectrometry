function [groups,nativeToSource] = plan_rf_exact_birth_releases(birthSeconds,positionVelocity,particleIds,massAmu,chargeState,weights)
% Pure draft for existing homogeneous-species RF ReleaseFromDataFile contract.
% No COMSOL calls, resampling, rounding, clock shift, file I/O or new registry.
birthSeconds=birthSeconds(:);particleIds=particleIds(:);massAmu=massAmu(:);chargeState=chargeState(:);weights=weights(:);
n=numel(birthSeconds);
assert(n>0&&isequal(size(positionVelocity),[n 6]),'rf:ReleaseShape','Expected N-by-6 Cartesian state.');
assert(all(isfinite(birthSeconds))&&all(birthSeconds>=0)&&all(isfinite(positionVelocity),'all'),'rf:ReleaseFinite','Birth and 6D must be finite.');
assert(isreal(particleIds)&&numel(particleIds)==n&&all(isfinite(particleIds))&&all(particleIds>0)&&all(particleIds<=flintmax)&&all(particleIds==fix(particleIds))&&numel(unique(particleIds))==n,'rf:ReleaseIds','Original IDs must be unique finite values.');
assert(isreal(massAmu)&&isreal(chargeState)&&numel(massAmu)==n&&numel(chargeState)==n&&all(isfinite(massAmu))&&all(massAmu>0)&&all(isfinite(chargeState))&&all(chargeState~=0)&&all(chargeState==fix(chargeState)),'rf:ReleaseSpecies','Invalid species facts.');
assert(all(massAmu==massAmu(1))&&all(chargeState==chargeState(1)),'rf:ReleaseSpecies','Current RF physics requires one homogeneous species.');
assert(numel(weights)==n&&all(isnan(weights)|(isfinite(weights)&weights>=0)),'rf:ReleaseWeights','Weights must remain authoritative or unknown.');
groups=struct('source_rows',{},'particle_ids',{},'birth_s',{},'release_time_expression',{},'mass_amu',{},'charge_state',{},'weights',{},'position_velocity',{},'release_text',{});
assigned=false(n,1);nativeToSource=zeros(n,1);offset=0;
for row=1:n
 if assigned(row),continue;end
 rows=find(~assigned&birthSeconds==birthSeconds(row));assigned(rows)=true;
 group=struct('source_rows',rows,'particle_ids',particleIds(rows),'birth_s',birthSeconds(row), ...
  'release_time_expression',sprintf('%.17g[s]',birthSeconds(row)),'mass_amu',massAmu(row),'charge_state',chargeState(row), ...
  'weights',weights(rows),'position_velocity',positionVelocity(rows,:), ...
  'release_text',sprintf('%.17g\t%.17g\t%.17g\t%.17g\t%.17g\t%.17g\n',positionVelocity(rows,:)'));
 groups(end+1)=group;nativeToSource(offset+(1:numel(rows)))=rows;offset=offset+numel(rows);
end
assert(offset==n&&isequal(sort(nativeToSource),(1:n)'),'rf:ReleaseClosure','Mother population is not closed.');
end
