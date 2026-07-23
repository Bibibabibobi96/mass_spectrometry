function contract = load_rf_quadrupole_contract(contractPath)
%LOAD_RF_QUADRUPOLE_CONTRACT Load and validate the generated design release.

projectRoot = fileparts(mfilename('fullpath'));
if nargin<1 || isempty(contractPath)
    contractPath = fullfile(projectRoot,'config','resolved_design_official.json');
end
assert(isfile(contractPath),'rfquad:MissingResolvedContract', ...
    'Missing resolved contract: %s. Run analysis/resolve_contract.py --write.',contractPath);
contract = jsondecode(fileread(contractPath));
assert(contract.schema_version==1 && ...
    strcmp(contract.role,'multipole_resolved_design_do_not_edit'), ...
    'rfquad:ResolvedSchema','Unsupported resolved contract schema.');
assert(strcmp(contract.identity.project_id,'rf_quadrupole_collision_cooling') && ...
    contract.identity.radial_order_n==2 && contract.identity.electrode_count==4, ...
    'rfquad:ResolvedIdentity','Resolved contract is not the governed RF quadrupole design.');
g=contract.geometry_mm;
array=g.rod_array;
interfaces=contract.interfaces_mm;
enclosure=g.enclosure;
assert(numel(array.rods)==contract.identity.electrode_count, ...
    'rfquad:ResolvedRodArray','Resolved rod count differs from multipole identity.');
mustBeNear(array.inscribed_radius_r0,g.inscribed_radius_r0,'rod-array r0');
mustBeNear(array.rod_radius,g.rod_radius,'rod-array radius');
mustBeNear(array.rod_center_radius,g.rod_center_radius,'rod-array center radius');
mustBeNear(array.rod_length,g.rod_length,'rod-array length');
mustBeNear(interfaces.exit.plate_z_min_mm,enclosure.exit_enclosure_z_min_mm, ...
    'exit plate z-min');
mustBeNear(interfaces.exit.plate_z_max_mm,enclosure.exit_front_wall_end_z_mm, ...
    'exit plate z-max');
mustBeNear(interfaces.exit.particle_plane_z_mm,enclosure.vacuum_z_max_mm, ...
    'observation plane');
end

function mustBeNear(actual,expected,label)
assert(abs(double(actual)-double(expected))<=1e-10,'rfquad:ResolvedDerivation', ...
    '%s is inconsistent: actual=%.17g expected=%.17g',label,actual,expected);
end
