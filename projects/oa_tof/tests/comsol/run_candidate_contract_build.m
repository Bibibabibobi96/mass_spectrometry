%RUN_CANDIDATE_CONTRACT_BUILD Build one isolated N=100 candidate MPH.
reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
contractPath = getenv('OATOF_CANDIDATE_CONTRACT_PATH');
modelPath = getenv('OATOF_CANDIDATE_MODEL_PATH');
ionPath = getenv('OATOF_CANDIDATE_ION_PATH');
assert(~isempty(reportPath), 'COMSOL_BOOTSTRAP_REPORT is required.');
assert(isfile(contractPath), 'Candidate contract is missing: %s', contractPath);
assert(~isempty(modelPath), 'OATOF_CANDIDATE_MODEL_PATH is required.');
assert(isfile(ionPath), 'Candidate N=100 particle table is missing: %s', ionPath);

testDir = fileparts(mfilename('fullpath'));
projectRoot = fileparts(fileparts(testDir));
addpath(projectRoot, fullfile(projectRoot, 'comsol'));
contract = load_oatof_contract(contractPath);

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));
try
    result = run_oatof_model( ...
        MassAmu=contract.validation_target.mass_amu, ...
        Label="ContractCandidate", SolverMode="cpu", FieldMode="real", ...
        ParticleCount=100, FixedParticleTable=string(ionPath), ...
        FineTimestepNs=contract.comsol_runtime.fine_output_step_ns, ...
        AcceleratorMeshHmaxMm=contract.comsol_runtime.routine_accelerator_hmax_mm, ...
        DriftTimestepNs=contract.comsol_runtime.field_free_output_step_ns, ...
        OutputModelPath=string(modelPath), ContractPath=string(contractPath));
    assert(result.nP == 100 && result.nDet == 100, ...
        'Candidate detected only %d/%d particles.', result.nDet, result.nP);
    assert(isfile(modelPath), 'Candidate MPH was not saved.');
    fprintf(fid, 'MODEL=%s\nCONTRACT=%s\nPARTICLES=%d\nDETECTED=%d\nSTATUS=PASS\n', ...
        modelPath, contractPath, result.nP, result.nDet);
catch exception
    fprintf(fid, 'STATUS=FAIL\nERROR=%s\n', getReport(exception, 'extended', 'hyperlinks', 'off'));
    rethrow(exception)
end
clear cleanup
