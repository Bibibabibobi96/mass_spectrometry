reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
testDir = fileparts(mfilename('fullpath'));
projectRoot = fileparts(fileparts(testDir));
addpath(projectRoot);
addpath(fullfile(projectRoot, 'comsol'));
paths = oatof_paths();
modelPath = fullfile(tempname(paths.scratchRoot), 'model.mph');

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));

result = run_oatof_model( ...
    MassAmu=524, Label="BuilderModuleSmoke", SolverMode="cpu", ...
    FieldMode="real", ParticleCount=100, ...
    ContractPath=string(fullfile(projectRoot,'config','resolved_geometry.json')), ...
    OutputModelPath=string(modelPath));
assert(result.nP == 100 && result.nDet == 100, ...
    'Modular builder detected only %d/%d particles.', result.nDet, result.nP);
assert(isfile(result.raw_detector_events_path), 'Modular builder did not export raw detector events.');
assert(isfile(result.analysis_request_path), 'Modular builder did not emit a Python analysis request.');
fprintf(fid, 'PARTICLES=%d\n', result.nP);
fprintf(fid, 'DETECTED=%d\n', result.nDet);
fprintf(fid, 'RAW_DETECTOR_EVENTS=%s\n', result.raw_detector_events_path);
fprintf(fid, 'PYTHON_ANALYSIS_REQUEST=%s\n', result.analysis_request_path);
fprintf(fid, 'STATUS=PASS\n');
clear cleanup
