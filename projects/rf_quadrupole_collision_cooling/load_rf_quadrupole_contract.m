function contract = load_rf_quadrupole_contract(contractPath)
%LOAD_RF_QUADRUPOLE_CONTRACT Load and validate the generated design release.

projectRoot = fileparts(mfilename('fullpath'));
if nargin<1 || isempty(contractPath)
    contractPath = fullfile(projectRoot,'config','resolved_geometry.json');
end
assert(isfile(contractPath),'rfquad:MissingResolvedContract', ...
    'Missing resolved contract: %s. Run analysis/resolve_contract.py --write.',contractPath);
contract = jsondecode(fileread(contractPath));
allowedRoles={'rf_quadrupole_resolved_official_contract_do_not_edit', ...
    'rf_quadrupole_resolved_interface_readiness_contract_do_not_edit', ...
    'rf_quadrupole_resolved_mass_filter_contract_do_not_edit'};
assert(contract.schema_version==1 && any(strcmp(contract.role,allowedRoles)), ...
    'rfquad:ResolvedSchema','Unsupported resolved contract schema.');
g=contract.geometry_mm;
array=contract.rod_array_mm;
interfaces=contract.interface_layout_mm;
mustBeNear(g.rod_radius,g.field_radius_r0*g.rod_radius_ratio,'rod radius');
mustBeNear(g.rod_length,g.rod_z_max-g.rod_z_min,'rod length');
assert(numel(array.rods)==contract.multipole.electrode_count, ...
    'rfquad:ResolvedRodArray','Resolved rod count differs from multipole identity.');
mustBeNear(array.inscribed_radius_r0,g.field_radius_r0,'rod-array r0');
mustBeNear(array.rod_radius,g.rod_radius,'rod-array radius');
mustBeNear(array.rod_center_radius,g.rod_center_radius,'rod-array center radius');
mustBeNear(array.rod_length,g.rod_length,'rod-array length');
mustBeNear(interfaces.entrance.plate_z_min_mm,g.entrance_plate_z_min,'entrance plate z-min');
mustBeNear(interfaces.entrance.plate_z_max_mm,g.entrance_plate_z_max,'entrance plate z-max');
mustBeNear(interfaces.entrance.particle_plane_z_mm,g.release_z,'release plane');
mustBeNear(interfaces.exit.plate_z_min_mm,g.exit_enclosure_z_min,'exit plate z-min');
mustBeNear(interfaces.exit.plate_z_max_mm,g.exit_enclosure_front_wall_end_z,'exit plate z-max');
mustBeNear(interfaces.exit.particle_plane_z_mm,g.model_z_span,'observation plane');
mustBeNear(g.exit_enclosure_front_wall_end_z-g.exit_enclosure_z_min,0.8,'exit front-wall thickness');
mustBeNear(contract.coordinate_convention.detector_plane_z_mm,g.model_z_span,'detector/model end plane');
end

function mustBeNear(actual,expected,label)
assert(abs(double(actual)-double(expected))<=1e-10,'rfquad:ResolvedDerivation', ...
    '%s is inconsistent: actual=%.17g expected=%.17g',label,actual,expected);
end
