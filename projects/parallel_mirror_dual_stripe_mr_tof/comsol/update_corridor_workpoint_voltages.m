function receipt = update_corridor_workpoint_voltages(model, source, target)
%UPDATE_CORRIDOR_WORKPOINT_VOLTAGES Update absolute mirror/P/S V0 on a C0 mesh.
% COMSOL 6.4 ElectricPotential V0 API; no geometry, mesh or solver changes.
arguments
    model
    source (1,1) struct
    target (1,1) struct
end
original = double(source.analyzer_electrode_voltages_v(:));
desired = double(target.analyzer_electrode_voltages_v(:));
validateattributes(original, {'double'}, {'numel',20,'real','finite'});
validateattributes(desired, {'double'}, {'numel',20,'real','finite'});
allowed = [1:14,16,17]; % Both mirrors, S1 pair, S2 pair, P1, P2 IDs.
fixed = setdiff(1:20, allowed);
assert(isequal(original(fixed),desired(fixed)) && ...
    isequaln(source.component_voltages_v,target.component_voltages_v) && ...
    isequaln(source.assembly,target.assembly), 'MRTOF:FixedAuthority', ...
    'A same-mesh update cannot change ground shields, OA, detector or assembly.');
assert(isequal(desired(1:5),desired(6:10)) && desired(1)==0, ...
    'MRTOF:MirrorPair', 'Both mirrors require the same absolute voltages and grounded first electrode.');
assert(desired(11)==desired(12) && desired(13)==desired(14), ...
    'MRTOF:StripePair', 'Each Stripe pair must share its prescribed voltage.');
es = model.component('comp1').physics('es');
physicalIds = [1:18,20]; % id19 has no physical solid in this frozen analyzer.
for id = physicalIds
    actual = sscanf(char(es.feature(sprintf('mrc_e%d_potential',id)).getString('V0')),'%f',1);
    assert(isscalar(actual) && isfinite(actual) && abs(actual-original(id))<1e-8, ...
        'MRTOF:SourceVoltage', 'Saved MPH does not match source analyzer authority.');
end
for j = 1:numel(source.component_voltages_v)
    rows = source.component_voltages_v;
    if iscell(rows), row = rows{j}; else, row = rows(j); end
    tag = sprintf('mrc_%s_e%d_potential',row.component_namespace,row.component_electrode_id);
    actual = sscanf(char(es.feature(tag).getString('V0')),'%f',1);
    assert(isscalar(actual) && isfinite(actual) && abs(actual-row.voltage_v)<1e-8, ...
        'MRTOF:ComponentVoltage', 'Saved MPH does not match fixed component authority.');
end
for id = allowed
    es.feature(sprintf('mrc_e%d_potential',id)).set('V0',sprintf('%.17g[V]',desired(id)));
end
actual = zeros(20,1);
for id = physicalIds
    actual(id) = sscanf(char(es.feature(sprintf('mrc_e%d_potential',id)).getString('V0')),'%f',1);
end
actual(19) = desired(19); % Inactive contract slot, not a queried electrode.
assert(all(abs(actual-desired)<1e-8),'MRTOF:CandidateVoltage','Candidate V0 readback differs.');
receipt = struct('changed_physical_ids',allowed,'source_voltages_v',original.', ...
    'actual_voltages_v',actual.','geometry_mesh_solver_changed',false);
end
