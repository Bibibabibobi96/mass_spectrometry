reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
testDir = fileparts(mfilename('fullpath'));
projectRoot = fileparts(fileparts(testDir));
addpath(projectRoot);
addpath(fullfile(projectRoot, 'comsol'));

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));

selector = "ideal:accel.ez+stage2.ex+stage2.ey";
result = run_oatof_model( ...
    MassAmu=524, Label="FieldIdealizationSmoke", SolverMode="cpu", ...
    FieldMode=selector, ParticleCount=100);
assert(result.nP == 100 && result.nDet == 100, ...
    'Field idealization smoke detected only %d/%d particles.', result.nDet, result.nP);
assert(result.field_idealization.canonical == selector, ...
    'Canonical selector mismatch: %s.', result.field_idealization.canonical);

saved = mphload(result.model_path);
assert(saved.param.evaluate('ideal_accel_ez') == 1, 'Saved MPH lost ideal_accel_ez.');
assert(saved.param.evaluate('ideal_stage2_ex') == 1, 'Saved MPH lost ideal_stage2_ex.');
assert(saved.param.evaluate('ideal_stage2_ey') == 1, 'Saved MPH lost ideal_stage2_ey.');
assert(saved.param.evaluate('ideal_accel_ex') == 0, 'Unselected ideal_accel_ex is not zero.');
assert(saved.param.evaluate('ideal_stage2_ez') == 0, 'Unselected ideal_stage2_ez is not zero.');

fprintf(fid, 'SELECTOR=%s\n', result.field_idealization.canonical);
fprintf(fid, 'PARTICLES=%d\n', result.nP);
fprintf(fid, 'DETECTED=%d\n', result.nDet);
fprintf(fid, 'MODEL_PATH=%s\n', result.model_path);
fprintf(fid, 'STATUS=PASS\n');
clear cleanup
