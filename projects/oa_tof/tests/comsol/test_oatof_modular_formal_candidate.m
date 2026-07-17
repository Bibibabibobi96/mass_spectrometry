reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
testDir = fileparts(mfilename('fullpath'));
projectRoot = fileparts(fileparts(testDir));
addpath(projectRoot);
addpath(fullfile(projectRoot, 'comsol'));
paths = oatof_paths();

ionPath = fullfile(paths.simionFormalDir, ...
    'oatof_comsol_524amu_gaussian_N100.ion');
modelPath = fullfile(paths.comsolCandidateDir, ...
    'MS_oaTOF_TwoStageRingStackReflectron_ModularCandidate.mph');
assert(isfile(ionPath), 'Formal fixed N=100 ion table is missing: %s', ionPath);

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));

result = run_oatof_model( ...
    MassAmu=524, Label="ModularCandidate", SolverMode="cpu", ...
    FieldMode="real", ParticleCount=100, FixedParticleTable=string(ionPath), ...
    FineTimestepNs=0.2, AcceleratorMeshHmaxMm=1, DriftTimestepNs=50, ...
    OutputModelPath=string(modelPath));
assert(result.nP == 100 && result.nDet == 100, ...
    'Modular formal candidate detected only %d/%d particles.', ...
    result.nDet, result.nP);
assert(isfile(modelPath), 'Modular formal candidate MPH was not saved.');
fprintf(fid, 'MODEL=%s\n', modelPath);
fprintf(fid, 'PARTICLES=%d\n', result.nP);
fprintf(fid, 'DETECTED=%d\n', result.nDet);
fprintf(fid, 'MEAN_TOF_US=%.12g\n', result.meanT*1e6);
fprintf(fid, 'STATUS=PASS\n');
clear cleanup
