function result = build_and_solve_axisymmetric_gas_flow(projectRoot, outputDir)
%BUILD_AND_SOLVE_AXISYMMETRIC_GAS_FLOW Build the declared 2-D axisymmetric HNMF model.
% This is intentionally fail-closed: an absent license, an unsupported COMSOL
% feature/property, nonconvergence, or an invalid export raises an error.

arguments
    projectRoot (1, 1) string
    outputDir (1, 1) string
end

import com.comsol.model.*
import com.comsol.model.util.*

sciencePath = fullfile(projectRoot, "config", "gas_flow_science.json");
numericsPath = fullfile(projectRoot, "config", "comsol_solver_numerics.json");
geometryPath = fullfile(projectRoot, "config", "resolved_geometry.json");
science = readContract(sciencePath, "dual_cone_axisymmetric_gas_flow_science_contract");
numerics = readContract(numericsPath, "dual_cone_axisymmetric_gas_flow_comsol_numerics");
geometry = readContract(geometryPath, "dual_cone_tandem_quadrupole_resolved_geometry");
assert(strcmp(science.project_id, numerics.project_id) && ...
    strcmp(science.project_id, geometry.project_id), "GasFlow:Identity", ...
    "Project identities disagree.");
assert(strcmp(science.model_id, numerics.model_id), "GasFlow:Identity", ...
    "Science and numerics model identities disagree.");
assert(strcmp(science.physics.comsol_interface, "HighMachNumberFlow"), ...
    "GasFlow:Interface", "Only the declared HighMachNumberFlow interface is supported.");
if ~isfolder(outputDir)
    mkdir(outputDir);
end

g = geometry.geometry_mm;
s = science.physics.gas_species;
bc = science.boundary_conditions;
proxy = science.geometry_proxy;
n = numerics;

model = ModelUtil.create("DualConeGasFlow");
cleanup = onCleanup(@() ModelUtil.remove("DualConeGasFlow")); %#ok<NASGU>
model.label("Dual-cone axisymmetric nitrogen gas-flow screening model");
model.component.create("comp1", true);
model.component("comp1").geom.create("geom1", 2);
model.component("comp1").geom("geom1").axisymmetric(true);
model.component("comp1").geom("geom1").lengthUnit("mm");

% Every physical and numerical scalar is exposed in the saved model and comes
% from a versioned JSON contract (geometry, science, or numerics).
setParameter(model, "feed_L", proxy.upstream_feed_length_mm, "mm");
setParameter(model, "r_ap1", g.first_cone.aperture_radius_mm, "mm");
setParameter(model, "z_ap1", g.first_cone.aperture_reference_z_mm, "mm");
setParameter(model, "r_ap2", g.second_cone.aperture_radius_mm, "mm");
setParameter(model, "z_ap2", g.second_cone.aperture_reference_z_mm, "mm");
setParameter(model, "r_wall_at_ap2", ...
    g.nested_cone_computational_closure.first_inner_surface_radius_at_second_aperture_mm, "mm");
setParameter(model, "z_cone2_base", g.second_cone.theoretical_base_z_at_enclosure_radius_mm, "mm");
setParameter(model, "r_enclosure", g.low_pressure_enclosure.radius_mm, "mm");
setParameter(model, "z_end", g.low_pressure_enclosure.end_z_mm, "mm");
setParameter(model, "p_in_total", bc.inlet.total_pressure_pa, "Pa");
setParameter(model, "T_in_total", bc.inlet.total_temperature_k, "K");
setParameter(model, "p_out", bc.outlet.static_pressure_pa, "Pa");
setParameter(model, "M_N2", s.molar_mass_kg_per_mol, "kg/mol");
setParameter(model, "gamma_N2", s.specific_heat_ratio, "1");
setParameter(model, "Cp_N2", s.specific_heat_capacity_cp_j_per_kg_k, "J/(kg*K)");
setParameter(model, "k_N2", s.thermal_conductivity_w_per_m_k, "W/(m*K)");
setParameter(model, "mu_ref", s.dynamic_viscosity_reference_pa_s, "Pa*s");
setParameter(model, "T_mu_ref", s.dynamic_viscosity_reference_temperature_k, "K");
setParameter(model, "S_mu", s.sutherland_temperature_k, "K");
setParameter(model, "R_univ", s.universal_gas_constant_j_per_mol_k, "J/(mol*K)");

geom = model.component("comp1").geom("geom1");
try
    upstream = geom.create("poly_upstream", "Polygon");
    upstream.set("source", "table");
    upstream.set("table", [0, -proxy.upstream_feed_length_mm; ...
        g.first_cone.aperture_radius_mm, -proxy.upstream_feed_length_mm; ...
        g.first_cone.aperture_radius_mm, g.first_cone.aperture_reference_z_mm; ...
        g.nested_cone_computational_closure.first_inner_surface_radius_at_second_aperture_mm, ...
        g.second_cone.aperture_reference_z_mm; ...
        g.second_cone.aperture_radius_mm, g.second_cone.aperture_reference_z_mm; ...
        0, g.second_cone.aperture_reference_z_mm]);
    downstream = geom.create("poly_downstream", "Polygon");
    downstream.set("source", "table");
    downstream.set("table", [0, g.second_cone.aperture_reference_z_mm; ...
        g.second_cone.aperture_radius_mm, g.second_cone.aperture_reference_z_mm; ...
        g.low_pressure_enclosure.radius_mm, g.second_cone.theoretical_base_z_at_enclosure_radius_mm; ...
        g.low_pressure_enclosure.radius_mm, g.low_pressure_enclosure.end_z_mm; ...
        0, g.low_pressure_enclosure.end_z_mm]);
    unionFeature = geom.create("uni_fluid", "Union");
    unionFeature.selection("input").set({'poly_upstream', 'poly_downstream'});
    % Remove the artificial overlap boundary so the two polygons form one
    % connected fluid passage through the second aperture.
    unionFeature.set("intbnd", false);
    geom.run;
catch exception
    throwAsCaller(addCause(MException("GasFlow:GeometryAPI", ...
        "COMSOL geometry API contract failed; no result is valid."), exception));
end

% Boundary IDs are resolved geometrically, never assumed from creation order.
selectionPad = max(n.mesh.minimum_element_size_mm, eps);
inletBoundaries = mphselectbox(model, "geom1", ...
    [-selectionPad, g.first_cone.aperture_radius_mm + selectionPad; ...
    -proxy.upstream_feed_length_mm - selectionPad, -proxy.upstream_feed_length_mm + selectionPad], ...
    "boundary");
outletBoundaries = mphselectbox(model, "geom1", ...
    [-selectionPad, g.low_pressure_enclosure.radius_mm + selectionPad; ...
    g.low_pressure_enclosure.end_z_mm - selectionPad, g.low_pressure_enclosure.end_z_mm + selectionPad], ...
    "boundary");
assert(~isempty(inletBoundaries) && ~isempty(outletBoundaries), ...
    "GasFlow:BoundarySelection", "Could not resolve inlet or outlet boundary.");

try
    hmnf = model.component("comp1").physics.create("hmnf", "HighMachNumberFlow", "geom1");
    inlet = hmnf.create("hminl1", "HighMachNumberFlowInlet", 1);
    inlet.selection.set(inletBoundaries);
    inlet.set("FlowCondition", "Subsonic");
    inlet.set("InputState", "TotalConditions");
    inlet.set("p0tot", "p_in_total");
    inlet.set("T0tot", "T_in_total");
    outlet = hmnf.create("hmout1", "HighMachNumberFlowOutlet", 1);
    outlet.selection.set(outletBoundaries);
    outlet.set("FlowCondition", "Subsonic");
    outlet.set("BoundaryCondition", "Pressure");
    outlet.set("p0", "p_out");
    wall = hmnf.feature("wallbc1");
    wall.set("BoundaryCondition", "Slip");
    fluid = hmnf.feature("fluid1");
    fluid.set("Rs_mat", "userdef");
    fluid.set("Rs", "R_univ/M_N2");
    fluid.set("CpOrGammaOption", "gamma");
    fluid.set("gamma_mat", "userdef");
    fluid.set("gamma", "gamma_N2");
    fluid.set("k_mat", "userdef");
    fluid.set("k", {'k_N2', '0', '0', '0', 'k_N2', '0', '0', '0', 'k_N2'});
    fluid.set("mu_mat", "userdef");
    fluid.set("mu", "mu_ref*(T/T_mu_ref)^(3/2)*(T_mu_ref+S_mu)/(T+S_mu)");
    hmnf.feature("init1").set("u_init", {'0', '1[m/s]', '0'});
    hmnf.feature("init1").set("p_init", "p_in_total");
    hmnf.feature("init1").set("Tinit", "T_in_total");
catch exception
    throwAsCaller(addCause(MException("GasFlow:HighMachAPI", ...
        "The installed COMSOL version does not accept the declared High Mach Number Flow " + ...
        "feature/property contract at builder line %d; no fallback physics was used.", ...
        exception.stack(1).line), exception));
end

try
    mesh = model.component("comp1").mesh.create("mesh1");
    sizeFeature = mesh.feature("size");
    sizeFeature.set("custom", true);
    sizeFeature.set("hmax", n.mesh.maximum_element_size_mm);
    sizeFeature.set("hmin", n.mesh.minimum_element_size_mm);
    sizeFeature.set("hgrad", n.mesh.maximum_element_growth_rate);
    sizeFeature.set("hcurve", n.mesh.curvature_factor);
    sizeFeature.set("hnarrow", n.mesh.narrow_region_resolution);
    mesh.run;
    study = model.study.create("std1");
    study.create("stat", "Stationary");
    continuation = n.study.outlet_pressure_continuation_pa(:).';
    model.param.set("p_out", sprintf("%.17g[Pa]", continuation(1)));
    study.feature("stat").set("useparam", true);
    study.feature("stat").setIndex("pname", "p_out", 0);
    study.feature("stat").setIndex("plistarr", strjoin(string(continuation), " "), 0);
    study.feature("stat").setIndex("punit", "Pa", 0);
    study.createAutoSequences("all");
    model.sol("sol1").runAll;
catch exception
    throwAsCaller(addCause(MException("GasFlow:Solve", ...
        "Meshing, continuation, or stationary solve failed; no export was emitted."), exception));
end

artifacts = n.artifact_names;
modelPath = fullfile(outputDir, artifacts.model);
mphsave(model, modelPath);
result = exportRegularField(model, outputDir, science, numerics, geometry, ...
    inletBoundaries, outletBoundaries, sciencePath, numericsPath, geometryPath);
result.model_path = modelPath;
end

function result = exportRegularField(model, outputDir, science, numerics, geometry, inletIds, outletIds, sciencePath, numericsPath, geometryPath)
g = geometry.geometry_mm;
grid = numerics.export_grid;
rValues = grid.radial_start_mm:grid.radial_step_mm:g.low_pressure_enclosure.radius_mm;
zValues = -science.geometry_proxy.upstream_feed_length_mm:grid.axial_step_mm:g.low_pressure_enclosure.end_z_mm;
[rGrid, zGrid] = meshgrid(rValues, zValues);
query = [reshape(rGrid.', 1, []); reshape(zGrid.', 1, [])];
try
    sampled = mphinterp(model, {"p", "T", "v", "u"}, "coord", query, "ext", 0);
catch exception
    throwAsCaller(addCause(MException("GasFlow:ExportAPI", ...
        "COMSOL field interpolation failed; no export is valid."), exception));
end
p = reshape(sampled(1, :), size(rGrid.')).';
temperature = reshape(sampled(2, :), size(rGrid.')).';
uZ = reshape(sampled(3, :), size(rGrid.')).';
uR = reshape(sampled(4, :), size(rGrid.')).';
fluidMask = isfinite(p) & isfinite(temperature) & isfinite(uZ) & isfinite(uR);
s = science.physics.gas_species;
rho = p .* s.molar_mass_kg_per_mol ./ (s.universal_gas_constant_j_per_mol_k .* temperature);
soundSpeed = sqrt(s.specific_heat_ratio .* s.universal_gas_constant_j_per_mol_k ./ ...
    s.molar_mass_kg_per_mol .* temperature);
mach = hypot(uZ, uR) ./ soundSpeed;
meanFreePath = s.boltzmann_constant_j_per_k .* temperature ./ ...
    (sqrt(2) .* pi .* science.continuum_scope.n2_molecular_collision_diameter_m.^2 .* p);
knudsen = meanFreePath ./ (science.continuum_scope.characteristic_length_for_knudsen_mm * 1e-3);
fields = {p, temperature, uZ, uR, rho, mach, knudsen};
for index = 1:numel(fields)
    value = fields{index};
    value(~fluidMask) = NaN;
    fields{index} = value;
end
[p, temperature, uZ, uR, rho, mach, knudsen] = fields{:};

zIndex = repelem((0:numel(zValues)-1).', numel(rValues));
rIndex = repmat((0:numel(rValues)-1).', numel(zValues), 1);
tableOut = table(zIndex, rIndex, reshape(zGrid.', [], 1), reshape(rGrid.', [], 1), ...
    reshape(p.', [], 1), reshape(temperature.', [], 1), reshape(uZ.', [], 1), ...
    reshape(uR.', [], 1), reshape(rho.', [], 1), reshape(mach.', [], 1), ...
    reshape(knudsen.', [], 1), double(reshape(fluidMask.', [], 1)), ...
    "VariableNames", string(science.export_contract.columns));
csvPath = fullfile(outputDir, numerics.artifact_names.field_csv);
writetable(tableOut, csvPath);

try
    massIn = mphint2(model, "-2*pi*r*(p*M_N2/(R_univ*T))*v", "line", "selection", inletIds);
    massOut = mphint2(model, "2*pi*r*(p*M_N2/(R_univ*T))*v", "line", "selection", outletIds);
catch exception
    throwAsCaller(addCause(MException("GasFlow:MassBalanceAPI", ...
        "Boundary mass-flow integration failed; metadata was not emitted."), exception));
end
massError = abs(massOut - massIn) / max(abs(massIn), eps);
if ~isfinite(massError) || massError > numerics.validation.maximum_mass_balance_relative_error
    error("GasFlow:MassBalance", "Relative mass-balance error exceeds the JSON contract.");
end

metadata.schema_version = 1;
metadata.role = "dual_cone_axisymmetric_gas_field_metadata";
metadata.project_id = science.project_id;
metadata.model_id = science.model_id;
metadata.claim_scope = science.claim_scope;
metadata.field_schema_id = science.export_contract.schema_id;
metadata.coordinate_order = science.export_contract.coordinate_order;
metadata.row_count = height(tableOut);
metadata.grid.r_values_mm = rValues;
metadata.grid.z_values_mm = zValues;
metadata.field_csv_sha256 = fileSha256(csvPath);
metadata.source_contract_sha256.gas_flow_science = fileSha256(sciencePath);
metadata.source_contract_sha256.comsol_solver_numerics = fileSha256(numericsPath);
metadata.source_contract_sha256.resolved_geometry = fileSha256(geometryPath);
metadata.coordinate_frame = geometry.coordinate_frame;
metadata.solution_summary.requested_outlet_static_pressure_pa = science.boundary_conditions.outlet.static_pressure_pa;
metadata.solution_summary.inlet_mass_flow_kg_per_s = massIn;
metadata.solution_summary.outlet_mass_flow_kg_per_s = massOut;
metadata.solution_summary.mass_balance_relative_error = massError;
metadata.solution_summary.maximum_mach = max(mach(fluidMask));
metadata.solution_summary.maximum_knudsen_aperture = max(knudsen(fluidMask));
metadataPath = fullfile(outputDir, numerics.artifact_names.field_metadata);
writeJson(metadataPath, metadata);
result.field_csv_path = csvPath;
result.field_metadata_path = metadataPath;
result.mass_balance_relative_error = massError;
end

function value = readContract(path, expectedRole)
assert(isfile(path), "GasFlow:MissingInput", "Required input does not exist: %s", path);
value = jsondecode(fileread(path));
assert(value.schema_version == 1 && strcmp(value.role, expectedRole), ...
    "GasFlow:Contract", "Unsupported contract at %s", path);
end

function setParameter(model, name, value, unit)
model.param.set(name, sprintf("%.17g[%s]", value, unit));
end

function digest = fileSha256(path)
stream = java.io.FileInputStream(java.io.File(path));
cleanup = onCleanup(@() stream.close()); %#ok<NASGU>
md = java.security.MessageDigest.getInstance("SHA-256");
buffer = zeros(1, 8192, "int8");
while true
    count = stream.read(buffer, 0, numel(buffer));
    if count < 0
        break;
    end
    md.update(buffer(1:count));
end
digest = lower(reshape(dec2hex(typecast(md.digest(), "uint8"), 2).', 1, []));
end

function writeJson(path, value)
text = jsonencode(value, PrettyPrint=true);
handle = fopen(path, "w", "n", "UTF-8");
assert(handle >= 0, "GasFlow:MetadataWrite", "Cannot create %s", path);
cleanup = onCleanup(@() fclose(handle)); %#ok<NASGU>
fwrite(handle, text, "char");
fwrite(handle, newline, "char");
end
