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
transport = science.physics.transport_model;
bc = science.boundary_conditions;
proxy = science.geometry_proxy;
n = numerics;

resumeModelPath = string(getenv("DUAL_CONE_GAS_FLOW_RESUME_MODEL"));
if strlength(resumeModelPath) > 0
    assert(isfile(resumeModelPath), "GasFlow:ResumeModel", ...
        "The requested converged COMSOL model is missing: %s", resumeModelPath);
    model = mphload(resumeModelPath, "DualConeGasFlowResume");
    cleanup = onCleanup(@() ModelUtil.remove("DualConeGasFlowResume")); %#ok<NASGU>
    [storedNames, storedValues] = lastStoredParameterTuple(model);
    pressureIndex = find(storedNames == "p_out", 1);
    diffusionIndex = find(storedNames == "iso_diff", 1);
    assert(~isempty(pressureIndex) && ...
        abs(storedValues(pressureIndex) - science.boundary_conditions.outlet.static_pressure_pa) <= ...
        eps(science.boundary_conditions.outlet.static_pressure_pa), ...
        "GasFlow:ResumeModel", "The resumed solution outlet pressure differs from the contract.");
    assert(~isempty(diffusionIndex) && ...
        abs(storedValues(diffusionIndex) - numerics.study.accepted_terminal_isotropic_diffusion) <= ...
        eps(numerics.study.accepted_terminal_isotropic_diffusion), ...
        "GasFlow:ResumeModel", "The resumed solution stabilization differs from the contract.");
    selectionPad = max(numerics.mesh.minimum_element_size_mm, eps);
    inletBoundaries = mphselectbox(model, "geom1", ...
        [-selectionPad, science.geometry_proxy.upstream_plenum_radius_mm + selectionPad; ...
        -science.geometry_proxy.upstream_feed_length_mm - selectionPad, ...
        -science.geometry_proxy.upstream_feed_length_mm + selectionPad], "boundary");
    outletBoundaries = mphselectbox(model, "geom1", ...
        [-selectionPad, geometry.geometry_mm.low_pressure_enclosure.radius_mm + selectionPad; ...
        geometry.geometry_mm.downstream_aperture_plate.downstream_observation_end_z_mm - selectionPad, ...
        geometry.geometry_mm.downstream_aperture_plate.downstream_observation_end_z_mm + selectionPad], "boundary");
    assert(~isempty(inletBoundaries) && ~isempty(outletBoundaries), ...
        "GasFlow:ResumeModel", "Could not recover inlet or outlet boundary from the resumed model.");
    result = exportRegularField(model, outputDir, science, numerics, geometry, ...
        inletBoundaries, outletBoundaries, sciencePath, numericsPath, geometryPath);
    result.model_path = char(resumeModelPath);
    return
end

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
setParameter(model, "r_plenum", proxy.upstream_plenum_radius_mm, "mm");
setParameter(model, "first_bore_L", proxy.first_aperture_axial_channel_length_mm, "mm");
setParameter(model, "second_bore_L", proxy.second_aperture_axial_channel_length_mm, "mm");
setParameter(model, "r_ap1", g.first_cone.aperture_radius_mm, "mm");
setParameter(model, "z_ap1", g.first_cone.aperture_reference_z_mm, "mm");
setParameter(model, "r_ap2", g.second_cone.aperture_radius_mm, "mm");
setParameter(model, "z_ap2", g.second_cone.aperture_reference_z_mm, "mm");
setParameter(model, "r_wall_at_ap2", ...
    g.nested_cone_computational_closure.first_inner_surface_radius_at_second_aperture_mm, "mm");
setParameter(model, "z_cone2_base", g.second_cone.theoretical_base_z_at_enclosure_radius_mm, "mm");
setParameter(model, "r_enclosure", g.low_pressure_enclosure.radius_mm, "mm");
setParameter(model, "z_plate_up", g.downstream_aperture_plate.upstream_face_z_mm, "mm");
setParameter(model, "z_plate_down", g.downstream_aperture_plate.downstream_face_z_mm, "mm");
setParameter(model, "r_plate_ap", g.downstream_aperture_plate.aperture_radius_mm, "mm");
setParameter(model, "z_end", g.downstream_aperture_plate.downstream_observation_end_z_mm, "mm");
setParameter(model, "p_in", bc.inlet.static_pressure_pa, "Pa");
setParameter(model, "T_in", bc.inlet.temperature_k, "K");
setParameter(model, "p_out", bc.outlet.static_pressure_pa, "Pa");
setParameter(model, "M_N2", s.molar_mass_kg_per_mol, "kg/mol");
setParameter(model, "gamma_N2", s.specific_heat_ratio, "1");
setParameter(model, "Cp_N2", s.specific_heat_capacity_cp_j_per_kg_k, "J/(kg*K)");
setParameter(model, "k_num", transport.thermal_conductivity_w_per_m_k, "W/(m*K)");
setParameter(model, "mu_num", transport.dynamic_viscosity_pa_s, "Pa*s");
setParameter(model, "R_univ", s.universal_gas_constant_j_per_mol_k, "J/(mol*K)");
setParameter(model, "iso_diff", n.study.isotropic_diffusion_continuation(1), "1");
setParameter(model, "u_init_cavity", n.study.initial_axial_velocity_m_per_s, "m/s");

geom = model.component("comp1").geom("geom1");
try
    % One polygon represents the complete connected passage.  Splitting the
    % passage at z_ap2 creates two domains that only touch along the aperture
    % line; the resulting union can leave an isolated boundary vertex in the
    % thermal equation.  A single contour has identical physical walls and no
    % artificial internal interface.
    fluidPolygon = geom.create("poly_fluid", "Polygon");
    fluidPolygon.set("source", "table");
    fluidPolygon.set("table", [0, -proxy.upstream_feed_length_mm; ...
        proxy.upstream_plenum_radius_mm, -proxy.upstream_feed_length_mm; ...
        proxy.upstream_plenum_radius_mm, -proxy.first_aperture_axial_channel_length_mm; ...
        g.first_cone.aperture_radius_mm, -proxy.first_aperture_axial_channel_length_mm; ...
        g.first_cone.aperture_radius_mm, g.first_cone.aperture_reference_z_mm; ...
        g.nested_cone_computational_closure.first_inner_surface_radius_at_second_aperture_mm, ...
        g.second_cone.aperture_reference_z_mm; ...
        g.second_cone.aperture_radius_mm, g.second_cone.aperture_reference_z_mm; ...
        g.second_cone.aperture_radius_mm, ...
        g.second_cone.aperture_reference_z_mm + proxy.second_aperture_axial_channel_length_mm; ...
        g.low_pressure_enclosure.radius_mm, ...
        g.second_cone.theoretical_base_z_at_enclosure_radius_mm + proxy.second_aperture_axial_channel_length_mm; ...
        g.low_pressure_enclosure.radius_mm, g.downstream_aperture_plate.downstream_observation_end_z_mm; ...
        0, g.downstream_aperture_plate.downstream_observation_end_z_mm]);
    geom.run;
catch exception
    throwAsCaller(addCause(MException("GasFlow:GeometryAPI", ...
        "COMSOL geometry API contract failed; no result is valid."), exception));
end

% Boundary IDs are resolved geometrically, never assumed from creation order.
selectionPad = max(n.mesh.minimum_element_size_mm, eps);
inletBoundaries = mphselectbox(model, "geom1", ...
    [-selectionPad, proxy.upstream_plenum_radius_mm + selectionPad; ...
    -proxy.upstream_feed_length_mm - selectionPad, -proxy.upstream_feed_length_mm + selectionPad], ...
    "boundary");
outletBoundaries = mphselectbox(model, "geom1", ...
    [-selectionPad, g.low_pressure_enclosure.radius_mm + selectionPad; ...
    g.downstream_aperture_plate.downstream_observation_end_z_mm - selectionPad, ...
    g.downstream_aperture_plate.downstream_observation_end_z_mm + selectionPad], ...
    "boundary");
assert(~isempty(inletBoundaries) && ~isempty(outletBoundaries), ...
    "GasFlow:BoundarySelection", "Could not resolve inlet or outlet boundary.");

try
    hmnf = model.component("comp1").physics.create("hmnf", "HighMachNumberFlow", "geom1");
    hmnf.prop("InconsistentStabilization").set("IsotropicDiffusion", true);
    hmnf.prop("InconsistentStabilization").set("delid", "iso_diff");
    hmnf.prop("InconsistentStabilization").set("HeatIsotropicDiffusion", true);
    hmnf.prop("InconsistentStabilization").set("delidht", "iso_diff");
    inlet = hmnf.create("hminl1", "HighMachNumberFlowInlet", 1);
    inlet.selection.set(inletBoundaries);
    % Prescribe atmospheric static pressure and temperature at the plenum
    % boundary while solving the subsonic inlet velocity.  No Mach number or
    % mass flow is supplied.
    inlet.set("FlowCondition", "Subsonic");
    inlet.set("BoundaryCondition", "Pressure");
    inlet.set("p0", "p_in");
    inlet.set("TemperatureHeatflux", "Temperature");
    inlet.set("T0", "T_in");
    outlet = hmnf.create("hmout1", "HighMachNumberFlowOutlet", 1);
    outlet.selection.set(outletBoundaries);
    outlet.set("FlowCondition", "Subsonic");
    outlet.set("BoundaryCondition", "Pressure");
    outlet.set("p0", "p_out");
    wall = hmnf.feature("wallbc1");
    wall.set("BoundaryCondition", "NoSlip");
    fluid = hmnf.feature("fluid1");
    fluid.set("Rs_mat", "userdef");
    fluid.set("Rs", "R_univ/M_N2");
    fluid.set("CpOrGammaOption", "gamma");
    fluid.set("gamma_mat", "userdef");
    fluid.set("gamma", "gamma_N2");
    fluid.set("k_mat", "userdef");
    fluid.set("k", {'k_num', '0', '0', '0', 'k_num', '0', '0', '0', 'k_num'});
    fluid.set("mu_mat", "userdef");
    fluid.set("mu", "mu_num");
    hmnf.feature("init1").set("u_init", {'0', '0', 'u_init_cavity'});
    hmnf.feature("init1").set("p_init", "p_in");
    hmnf.feature("init1").set("Tinit", "T_in");
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
    stationary = study.create("stat", "Stationary");
    continuation = n.study.outlet_pressure_continuation_pa(:).';
    diffusionContinuation = n.study.isotropic_diffusion_continuation(:).';
    terminalDiffusion = n.study.accepted_terminal_isotropic_diffusion;
    if numel(continuation) ~= numel(diffusionContinuation) || ...
            diffusionContinuation(end) ~= terminalDiffusion
        error("GasFlow:ContinuationContract", ...
            "Pressure and artificial-diffusion continuation must be paired and end at the declared stabilization.");
    end
    model.param.set("p_out", sprintf("%.17g[Pa]", continuation(1)));
    model.param.set("iso_diff", sprintf("%.17g", diffusionContinuation(1)));
    stationary.set("useparam", true);
    stationary.setIndex("pname", "p_out", 0);
    stationary.setIndex("plistarr", strjoin(string(continuation), " "), 0);
    stationary.setIndex("punit", "Pa", 0);
    stationary.setIndex("pname", "iso_diff", 1);
    stationary.setIndex("plistarr", strjoin(string(diffusionContinuation), " "), 1);
    stationary.setIndex("punit", "1", 1);
    % COMSOL calls a column-wise list of specified parameter tuples a
    % "sparse" sweep.  "filled" forms the Cartesian product and therefore
    % does not preserve the pressure/diffusion continuation path above.
    stationary.set("sweeptype", "sparse");
    stationary.set("pcontinuationmode", "no");
    stationary.set("preusesol", "yes");
    study.createAutoSequences("all");
    stationarySolver = model.sol("sol1").feature("s1");
    stationarySolver.create("se1", "Segregated");
    segregated = stationarySolver.feature("se1");
    segregated.feature.remove("ssDef");
    segregated.create("ss1", "SegregatedStep");
    segregated.feature("ss1").set("segvar", {'comp1_T', 'comp1_p', 'comp1_u'});
    segregated.feature("ss1").set("subdamp", n.solver.segregated_damping);
    assert(strcmp(n.solver.linear_solver, "comsol_iterative_multigrid_i1"), ...
        "GasFlow:SolverContract", "Unsupported declared linear solver.");
    segregated.feature("ss1").set("linsolver", "i1");
    segregated.feature("ss1").set("subadapttol", n.solver.adaptive_step_tolerance);
    segregated.set("segstabacc", "segcflcmp");
    segregated.set("segcfltech", "simple");
    segregated.set("subinitcfl", n.solver.initial_cfl);
    segregated.set("submincfl", n.solver.target_cfl);
    segregated.set("subkppid", 0.65);
    segregated.set("subkdpid", 0.05);
    segregated.set("subkipid", 0.05);
    segregated.set("subcfltol", n.solver.cfl_comparison_tolerance);
    segregated.set("segcflaa", true);
    segregated.set("segcflaacfl", 9000);
    segregated.set("segcflaafact", 1);
    segregated.set("maxsegiter", n.solver.maximum_segregated_iterations);
    assert(strcmp(n.solver.termination, "tolerance"), ...
        "GasFlow:SolverContract", "Unsupported declared segregated termination policy.");
    segregated.set("segterm", "tol");
    segregated.create("ll1", "LowerLimit");
    lowerLimits = sprintf("comp1.T %.17g comp1.p %.17g ", ...
        n.solver.iteration_lower_limits.temperature_k, ...
        n.solver.iteration_lower_limits.pressure_pa);
    segregated.feature("ll1").set("lowerlimit", lowerLimits);
    stationarySolver.feature.remove("fc1");
    try
        model.sol("sol1").runAll;
    catch solveException
        diagnostic = storedParameterDiagnostic(model);
        continuationException = MException("GasFlow:ContinuationFailure", ...
            "Stationary continuation failed after stored parameter tuple: %s", diagnostic);
        throwAsCaller(addCause(continuationException, solveException));
    end
    [storedNames, storedValues] = lastStoredParameterTuple(model);
    pressureIndex = find(storedNames == "p_out", 1);
    diffusionIndex = find(storedNames == "iso_diff", 1);
    assert(~isempty(pressureIndex) && ~isempty(diffusionIndex) && ...
        abs(storedValues(pressureIndex) - bc.outlet.static_pressure_pa) <= eps(bc.outlet.static_pressure_pa) && ...
        abs(storedValues(diffusionIndex) - terminalDiffusion) <= eps(terminalDiffusion), ...
        "GasFlow:ContinuationTerminalState", ...
        "The stored terminal solution is not the requested pressure/stabilization state.");
catch exception
    throwAsCaller(addCause(MException("GasFlow:Solve", ...
        "Meshing or stationary pseudo-time continuation failed; no export was emitted."), exception));
end

artifacts = n.artifact_names;
modelPath = fullfile(outputDir, artifacts.model);
mphsave(model, modelPath);
result = exportRegularField(model, outputDir, science, numerics, geometry, ...
    inletBoundaries, outletBoundaries, sciencePath, numericsPath, geometryPath);
result.model_path = modelPath;
end

function diagnostic = storedParameterDiagnostic(model)
try
    [names, values] = lastStoredParameterTuple(model);
    parts = names + "=" + compose("%.17g", values);
    diagnostic = char(strjoin(parts, ","));
catch exception
    diagnostic = char("unavailable (" + string(exception.message) + ")");
end
end

function [names, lastValues] = lastStoredParameterTuple(model)
names = string(cell(model.sol("sol1").getPNames()));
values = double(model.sol("sol1").getPVals());
width = numel(names);
assert(width > 0 && numel(values) >= width && mod(numel(values), width) == 0, ...
    "GasFlow:StoredParameterIdentity", "Stored continuation parameter tuples are unavailable.");
lastValues = reshape(values(end - width + 1:end), 1, []);
names = reshape(names, 1, []);
end

function result = exportRegularField(model, outputDir, science, numerics, geometry, inletIds, outletIds, sciencePath, numericsPath, geometryPath)
g = geometry.geometry_mm;
grid = numerics.export_grid;
rValues = grid.radial_start_mm:grid.radial_step_mm:g.low_pressure_enclosure.radius_mm;
zValues = -science.geometry_proxy.upstream_feed_length_mm:grid.axial_step_mm: ...
    g.downstream_aperture_plate.downstream_observation_end_z_mm;
[rGrid, zGrid] = meshgrid(rValues, zValues);
query = [reshape(rGrid.', 1, []); reshape(zGrid.', 1, [])];
try
    [sampledP, sampledTemperature, sampledUZ, sampledUR] = ...
        mphinterp(model, {"p", "T", "w", "u"}, "coord", query, ...
        "ext", 0, "solnum", "end");
catch exception
    throwAsCaller(addCause(MException("GasFlow:ExportAPI", ...
        "COMSOL field interpolation failed; no export is valid."), exception));
end
p = reshape(sampledP, size(rGrid.')).';
temperature = reshape(sampledTemperature, size(rGrid.')).';
uZ = reshape(sampledUZ, size(rGrid.')).';
uR = reshape(sampledUR, size(rGrid.')).';
fluidMask = isfinite(p) & isfinite(temperature) & isfinite(uZ) & isfinite(uR);
if any(temperature(fluidMask) <= numerics.solver.iteration_lower_limits.temperature_k) || ...
        any(p(fluidMask) <= numerics.solver.iteration_lower_limits.pressure_pa)
    error("GasFlow:LowerLimitActive", ...
        "A converged field touches an iteration lower limit and is not physically valid.");
end
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
    VariableNames=cellstr(string(science.export_contract.columns)));
csvPath = fullfile(outputDir, numerics.artifact_names.field_csv);
writetable(tableOut, csvPath);

try
    massIn = mphint2(model, "2*pi*r*(p*M_N2/(R_univ*T))*w", "line", ...
        "selection", inletIds, "solnum", "end");
    massOut = mphint2(model, "2*pi*r*(p*M_N2/(R_univ*T))*w", "line", ...
        "selection", outletIds, "solnum", "end");
catch exception
    throwAsCaller(addCause(MException("GasFlow:MassBalanceAPI", ...
        "Boundary mass-flow integration failed; metadata was not emitted."), exception));
end
if ~isfinite(massIn) || ~isfinite(massOut) || massIn <= 0 || massOut <= 0
    error("GasFlow:MassFlowDirection", ...
        "Expected positive downstream mass flow at both boundaries (in=%.17g, out=%.17g kg/s).", ...
        massIn, massOut);
end
massError = abs(massOut - massIn) / max(abs(massIn), eps);
if ~isfinite(massError) || massError > numerics.validation.maximum_mass_balance_relative_error
    error("GasFlow:MassBalance", ...
        "Relative mass-balance error %.17g exceeds the JSON contract (in=%.17g kg/s, out=%.17g kg/s).", ...
        massError, massIn, massOut);
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
metadata.solution_summary.accepted_isotropic_diffusion = numerics.study.accepted_terminal_isotropic_diffusion;
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
stream = fopen(path, "r");
assert(stream >= 0, "GasFlow:HashRead", "Cannot hash file: %s", path);
cleanup = onCleanup(@() fclose(stream)); %#ok<NASGU>
md = java.security.MessageDigest.getInstance("SHA-256");
while true
    bytes = fread(stream, 1024 * 1024, "*uint8");
    if isempty(bytes)
        break;
    end
    md.update(typecast(bytes, "int8"));
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
