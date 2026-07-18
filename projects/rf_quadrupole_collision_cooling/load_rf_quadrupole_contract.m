function contract = load_rf_quadrupole_contract()
%LOAD_RF_QUADRUPOLE_CONTRACT Load and validate the generated design release.

projectRoot = fileparts(mfilename('fullpath'));
contractPath = fullfile(projectRoot,'config','resolved_geometry.json');
assert(isfile(contractPath),'rfquad:MissingResolvedContract', ...
    'Missing resolved_geometry.json; run analysis/resolve_contract.py --write.');
contract = jsondecode(fileread(contractPath));
assert(contract.schema_version==1 && ...
    strcmp(contract.role,'rf_quadrupole_resolved_official_contract_do_not_edit'), ...
    'rfquad:ResolvedSchema','Unsupported resolved contract schema.');
g=contract.geometry_mm;
mustBeNear(g.rod_radius,g.field_radius_r0*g.rod_radius_ratio,'rod radius');
mustBeNear(g.rod_length,g.rod_z_max-g.rod_z_min,'rod length');
mustBeNear(g.exit_enclosure_front_wall_end_z-g.exit_enclosure_z_min,0.8,'exit front-wall thickness');
mustBeNear(contract.coordinate_convention.detector_plane_z_mm,g.model_z_span,'detector/model end plane');
end

function mustBeNear(actual,expected,label)
assert(abs(double(actual)-double(expected))<=1e-10,'rfquad:ResolvedDerivation', ...
    '%s is inconsistent: actual=%.17g expected=%.17g',label,actual,expected);
end
