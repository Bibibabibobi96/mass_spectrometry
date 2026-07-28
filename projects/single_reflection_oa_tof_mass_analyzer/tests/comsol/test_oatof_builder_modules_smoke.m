reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
testDir = fileparts(mfilename('fullpath'));
projectRoot = fileparts(fileparts(testDir));
addpath(projectRoot);
addpath(fullfile(projectRoot, 'comsol'));

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));

result = run_oatof_model( ...
    MassAmu=524, Label="BuilderModuleSmoke", SolverMode="cpu", ...
    FieldMode="real", ParticleCount=100);
assert(result.nP == 100 && result.nDet == 100, ...
    'Modular builder detected only %d/%d particles.', result.nDet, result.nP);
assert(all(isfinite(result.detTimes)), 'Modular builder returned nonfinite detector times.');
fprintf(fid, 'PARTICLES=%d\n', result.nP);
fprintf(fid, 'DETECTED=%d\n', result.nDet);
fprintf(fid, 'MEAN_TOF_US=%.12g\n', result.meanT*1e6);
fprintf(fid, 'STATUS=PASS\n');
clear cleanup
