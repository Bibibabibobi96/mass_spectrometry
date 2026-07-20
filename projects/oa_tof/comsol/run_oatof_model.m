function result = run_oatof_model(options)
%RUN_OATOF_MODEL Stable named-parameter entry for the oa-TOF COMSOL model.
% The legacy positional production builder remains internal so existing
% validated tests keep their exact call behavior.

arguments
    options.MassAmu (1,1) double = NaN
    options.Label (1,1) string = ""
    options.SolverMode (1,1) string {mustBeMember(options.SolverMode,["cpu","gpu"])} = "cpu"
    options.FieldMode (1,1) string = "real"
    options.ReflectronStage1Mm (1,1) double = NaN
    options.ReflectronStage2RingCount (1,1) double = NaN
    options.ReflectronMeshHmaxMm (1,1) double = NaN
    options.BoreRadiusMm (1,1) double = NaN
    options.RingThicknessMm (1,1) double = NaN
    options.ParticleCount (1,1) double = NaN
    options.ReflectronStage1RingCount (1,1) double = NaN
    options.AcceleratorBoreHalfMm (1,1) double = NaN
    options.FixedParticleTable (1,1) string = ""
    options.FineTimestepNs (1,1) double = NaN
    options.AcceleratorMeshHmaxMm (1,1) double = NaN
    options.DriftTimestepNs (1,1) double = NaN
    options.OutputModelPath (1,1) string = ""
    options.ContractPath (1,1) string = ""
end

projectRoot = fileparts(fileparts(mfilename('fullpath')));
addpath(projectRoot);
contractPath = options.ContractPath;
if strlength(contractPath) == 0
    contractPath = string(fullfile(projectRoot, 'config', 'resolved_geometry.json'));
end
contract = load_oatof_contract(contractPath);
options = apply_defaults(options, contract);
positiveNames = ["MassAmu","ReflectronStage1Mm","ReflectronMeshHmaxMm", ...
    "BoreRadiusMm","RingThicknessMm","ParticleCount", ...
    "ReflectronStage1RingCount","ReflectronStage2RingCount", ...
    "AcceleratorBoreHalfMm","FineTimestepNs", ...
    "AcceleratorMeshHmaxMm","DriftTimestepNs"];
for name = positiveNames
    mustBePositive(options.(name));
end
mustBeInteger(options.ParticleCount);
mustBeInteger(options.ReflectronStage1RingCount);
mustBeInteger(options.ReflectronStage2RingCount);
if strlength(options.Label) == 0
    options.Label = compose("%gamu", options.MassAmu);
end
if strlength(options.OutputModelPath) > 0
    paths = oatof_paths();
    outputPath = string(java.io.File(char(options.OutputModelPath)).getCanonicalPath());
    allowedRoots = string({paths.comsolFormalDir, paths.runsRoot, paths.scratchRoot});
    allowed = false;
    for root = allowedRoots
        canonicalRoot = string(java.io.File(char(root)).getCanonicalPath());
        allowed = allowed || startsWith(lower(outputPath), lower(canonicalRoot + filesep));
    end
    assert(allowed, 'OutputModelPath must remain under formal/comsol, runs, or scratch.');
    [~,~,extension] = fileparts(outputPath);
    assert(strcmpi(extension, '.mph'), 'OutputModelPath must end in .mph.');
    options.OutputModelPath = outputPath;
end

result = ms_oaTOF_two_stage_ringstack_reflectron( ...
    options.MassAmu, char(options.Label), char(options.SolverMode), ...
    char(options.FieldMode), options.ReflectronStage1Mm, ...
    options.ReflectronStage2RingCount, options.ReflectronMeshHmaxMm, ...
    options.BoreRadiusMm, options.RingThicknessMm, options.ParticleCount, ...
    options.ReflectronStage1RingCount, options.AcceleratorBoreHalfMm, ...
    char(options.FixedParticleTable), options.FineTimestepNs, ...
    options.AcceleratorMeshHmaxMm, options.DriftTimestepNs, ...
    char(options.OutputModelPath), char(contractPath));
end

function options = apply_defaults(options, contract)
g = contract.geometry_mm;
defaults = struct( ...
    'MassAmu', contract.validation_target.mass_amu, ...
    'ReflectronStage1Mm', g.L_stage1, ...
    'ReflectronStage2RingCount', contract.rings.stage2_count, ...
    'ReflectronMeshHmaxMm', contract.comsol_runtime.routine_reflectron_hmax_mm, ...
    'BoreRadiusMm', g.bore_r, ...
    'RingThicknessMm', g.ring_thickness, ...
    'ParticleCount', contract.validation_target.particles, ...
    'ReflectronStage1RingCount', contract.rings.stage1_count, ...
    'AcceleratorBoreHalfMm', g.accelerator_bore_half, ...
    'FineTimestepNs', contract.comsol_runtime.fine_output_step_ns, ...
    'AcceleratorMeshHmaxMm', contract.comsol_runtime.routine_accelerator_hmax_mm, ...
    'DriftTimestepNs', contract.comsol_runtime.field_free_output_step_ns);
names = fieldnames(defaults);
for index = 1:numel(names)
    name = names{index};
    if isnan(options.(name)), options.(name) = defaults.(name); end
end
end
