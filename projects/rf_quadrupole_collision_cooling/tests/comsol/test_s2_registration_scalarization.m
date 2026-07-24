% Regression for scalar, full-3D S2 registration predicates without COMSOL.
testDir = fileparts(mfilename('fullpath'));
projectRoot = fileparts(fileparts(testDir));
contract = jsondecode(fileread(fullfile( ...
    projectRoot,'config','rf_to_oatof_s2_passive_connector.json')));
spatial = jsondecode(fileread(fullfile( ...
    projectRoot,'config','resolved_rf_to_oatof_s2_spatial_registration.json')));
registration = contract.nominal_registration;

[sourceMatches,targetMatches,gapMatches] = registration_predicates(registration,spatial);
assert(isscalar(sourceMatches) && isscalar(targetMatches) && isscalar(gapMatches), ...
    'S2 registration predicates must be scalar logical values.');
assert(sourceMatches && targetMatches && gapMatches, ...
    'The authoritative S2 registration must satisfy every 3D predicate.');

changed = spatial;
changed.resolved_surfaces.source_exit.in_instrument_frame.center_mm(2) = ...
    changed.resolved_surfaces.source_exit.in_instrument_frame.center_mm(2)+0.1;
[sourceMatches,~,gapMatches] = registration_predicates(registration,changed);
assert(~sourceMatches && ~gapMatches, ...
    'A transverse source-center drift must fail the center and 3D gap predicates.');

changed = registration;
changed.source_component_pose.rotation_component_to_instrument(:,3) = [0.0;1.0;0.0];
[~,~,gapMatches] = registration_predicates(changed,spatial);
assert(~gapMatches, 'A source-axis drift must fail the 3D gap predicate.');

changed = spatial;
changed.project_semantics.connector_gap_mm = ...
    changed.project_semantics.connector_gap_mm+0.1;
[~,~,gapMatches] = registration_predicates(registration,changed);
assert(~gapMatches, 'A connector-gap drift must fail the 3D gap predicate.');

fprintf('S2_REGISTRATION_SCALARIZATION=PASS\n');

function [sourceMatches,targetMatches,gapMatches] = ...
    registration_predicates(registration,spatial)
sourceCenter = spatial.resolved_surfaces.source_exit.in_instrument_frame.center_mm;
targetCenter = spatial.resolved_surfaces.target_entry.in_instrument_frame.center_mm;
gapMm = spatial.project_semantics.connector_gap_mm;
sourceAxis = registration.source_component_pose.rotation_component_to_instrument*[0.0;0.0;1.0];
sourceMatches = all(abs(sourceCenter(:)- ...
    registration.source_exit_center_instrument_mm(:)) <= 1e-12,'all');
targetMatches = all(abs(targetCenter(:)- ...
    registration.target_entry_center_instrument_mm(:)) <= 1e-12,'all');
gapMatches = all(abs(targetCenter(:)-sourceCenter(:)- ...
    gapMm*sourceAxis(:)) <= 1e-12,'all');
end
