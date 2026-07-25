function result = ms_rf_quadrupole_interface_transport()
%MS_RF_QUADRUPOLE_INTERFACE_TRANSPORT Run the dedicated interface workflow.

projectRoot=fileparts(fileparts(mfilename('fullpath')));
addpath(projectRoot);
runConfigPath=getenv('RFQUAD_RUN_CONFIG');
assert(~isempty(runConfigPath) && isfile(runConfigPath), ...
    'RFQUAD_RUN_CONFIG must identify a frozen run config.');
runConfig=jsondecode(fileread(runConfigPath));
assert(strcmp(requiredText(runConfig,'role'),'rf_quadrupole_comsol_run_config'), ...
    'Interface run-config role mismatch.');
assert(strcmp(requiredText(runConfig,'workflow_id'),'transport_interface_readiness'), ...
    'Dedicated interface entry rejects other workflows.');
assert(strcmp(requiredText(runConfig,'project'),'rf_quadrupole_collision_cooling'), ...
    'Interface run-config project mismatch.');

inputs=requiredStruct(runConfig,'inputs');
modePath=requiredFile(inputs,'scientific_mode');
resolvedPath=requiredFile(inputs,'resolved_design');
requiredFile(inputs,'interface_contract');
requiredFile(inputs,'particle_table');
mode=jsondecode(fileread(modePath));
resolved=load_rf_quadrupole_contract(resolvedPath);
spec=requiredStruct(runConfig,'compiled_scientific_spec');

assert(strcmp(requiredText(spec,'role'), ...
    'rf_quadrupole_comsol_interface_scientific_spec'), ...
    'Compiled interface scientific-spec role mismatch.');
assert(strcmp(requiredText(spec,'workflow_id'),'transport_interface_readiness'), ...
    'Compiled interface scientific-spec workflow mismatch.');
assert(strcmp(requiredText(mode,'mode'),'transport_interface_readiness'), ...
    'Frozen scientific mode mismatch.');
physics=requiredStruct(mode,'physics');
assert(strcmp(requiredText(physics,'collision_model'),'none'), ...
    'Interface transport requires collision_model=none.');
assert(requiredLogical(physics,'mass_filter_dc')==false, ...
    'Interface transport requires mass_filter_dc=false.');
assert(requiredLogical(physics,'space_charge')==false, ...
    'Interface transport requires space_charge=false.');
assert(strcmp(requiredText(spec,'collision_model'),'none') && ...
    requiredLogical(spec,'mass_filter_dc')==false && ...
    requiredLogical(spec,'space_charge')==false, ...
    'Compiled scientific physics does not match the dedicated interface workflow.');

drive=requiredStruct(resolved,'drive');
assert(requiredFinite(drive,'dc_amplitude_V_per_group')==0 && ...
    requiredFinite(drive,'common_mode_offset_V')==0, ...
    'Interface resolved design must be RF-only.');
staticElectrodes=requiredStruct(resolved,'static_electrodes_V');
assert(requiredFinite(staticElectrodes,'entrance_plate_and_connector')==0 && ...
    requiredFinite(staticElectrodes,'exit_enclosure_and_connector')==0 && ...
    requiredFinite(staticElectrodes,'detector')==0, ...
    'Interface resolved design must not add static end fields.');

targets=requiredStruct(mode,'candidate_acceptance_targets');
minimumTransmission=requiredFinite(targets,'minimum_transmission');
maximumRadiusFraction=requiredFinite(targets,'maximum_allowed_radius_fraction_r0');
assert(minimumTransmission>=0 && minimumTransmission<=1, ...
    'Interface minimum_transmission must be in [0, 1].');
assert(maximumRadiusFraction>0, ...
    'Interface maximum_allowed_radius_fraction_r0 must be positive.');
assert(requiredFinite(spec,'minimum_transmission')==minimumTransmission && ...
    requiredFinite(spec,'maximum_allowed_radius_fraction_r0')==maximumRadiusFraction && ...
    requiredFinite(spec,'source_axial_offset_mm')==0, ...
    'Compiled interface thresholds or source placement differ from the frozen scientific mode.');

result=ms_rf_quadrupole_no_collision(runConfig);
r0=requiredFinite(requiredStruct(resolved,'geometry_mm'),'inscribed_radius_r0');
if result.transmission<minimumTransmission || ...
        result.max_hit_rod_radius_mm>=maximumRadiusFraction*r0
    error(['COMSOL interface transport gate failed: transmission=%.6g ' ...
        'maxHitRodRadius=%.6g'],result.transmission,result.max_hit_rod_radius_mm);
end
end

function value=requiredStruct(parent,fieldName)
assert(isstruct(parent) && isfield(parent,fieldName) && ...
    isstruct(parent.(fieldName)) && isscalar(parent.(fieldName)), ...
    '%s must be a scalar struct.',fieldName);
value=parent.(fieldName);
end

function value=requiredText(parent,fieldName)
assert(isstruct(parent) && isfield(parent,fieldName), '%s is required.',fieldName);
raw=parent.(fieldName);
assert((ischar(raw) || (isstring(raw) && isscalar(raw))) && ...
    ~isempty(strtrim(char(raw))), '%s must be non-empty text.',fieldName);
value=char(raw);
end

function path=requiredFile(parent,fieldName)
path=requiredText(parent,fieldName);
assert(isfile(path), '%s does not identify a frozen file: %s',fieldName,path);
end

function value=requiredFinite(parent,fieldName)
assert(isstruct(parent) && isfield(parent,fieldName), '%s is required.',fieldName);
value=parent.(fieldName);
assert(isnumeric(value) && isscalar(value) && isfinite(value), ...
    '%s must be one finite numeric scalar.',fieldName);
value=double(value);
end

function value=requiredLogical(parent,fieldName)
assert(isstruct(parent) && isfield(parent,fieldName), '%s is required.',fieldName);
value=parent.(fieldName);
assert(islogical(value) && isscalar(value), ...
    '%s must be one logical scalar.',fieldName);
end
