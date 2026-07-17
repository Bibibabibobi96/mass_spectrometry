reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
testDir = fileparts(mfilename('fullpath'));
projectDir = fileparts(fileparts(testDir));
addpath(projectDir);
addpath(fullfile(projectDir, 'comsol'));
paths = oatof_paths();

ionTable = getenv('OATOF_ION_TABLE');
if isempty(ionTable)
    ionTable = fullfile(paths.simionFormalDir, ...
        'oatof_comsol_524amu_gaussian_N100.ion');
end
assert(isfile(ionTable), 'Fixed SIMION particle table not found: %s', ionTable);
fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, 'ION_TABLE=%s\n', ionTable);
fprintf(fid, 'MODE=candidate_3d_fixed_particle_table\n');
fieldMode = getenv('OATOF_FIELD_MODE');
if isempty(fieldMode), fieldMode = 'real'; end
fineStepText = getenv('OATOF_FINE_TSTEP_NS');
if isempty(fineStepText), fineStepText = '0.2'; end
fineStepNs = str2double(fineStepText);
assert(isfinite(fineStepNs) && fineStepNs > 0, 'Invalid OATOF_FINE_TSTEP_NS.');
driftStepText = getenv('OATOF_DRIFT_TSTEP_NS');
if isempty(driftStepText), driftStepText = '50'; end
driftStepNs = str2double(driftStepText);
assert(isfinite(driftStepNs) && driftStepNs > 0, ...
    'Invalid OATOF_DRIFT_TSTEP_NS.');
label = sprintf('Candidate_524amu_FixedN100_%s_dt%gns', fieldMode, fineStepNs);
fprintf(fid, 'FIELD_MODE=%s\n', fieldMode);
fprintf(fid, 'FINE_TSTEP_NS=%.12g\n', fineStepNs);
fprintf(fid, 'DRIFT_TSTEP_NS=%.12g\n', driftStepNs);

try
    result = ms_oaTOF_two_stage_ringstack_reflectron(524, ...
        label, 'cpu', fieldMode, 120, 5, 15, 250, 5, 100, 10, 5, ...
        ionTable, fineStepNs, 1, driftStepNs);
    fprintf(fid, 'DETECTED=%d/%d\n', result.nDet, result.nP);
    fprintf(fid, 'MEAN_TOF_US=%.12g\n', result.meanT*1e6);
    fprintf(fid, 'MASS_FWHM_DIRECT_DA=%.12g\n', result.mass_fwhm_direct_Da);
    fprintf(fid, 'R_DIRECT=%.12g\n', result.R_fwhm_direct);
    fprintf(fid, 'R_SIGMA_PROXY=%.12g\n', result.R_fwhm_sigma_proxy);
    fprintf(fid, 'STATUS=PASS\n');
catch exception
    fprintf(fid, 'STATUS=FAIL\nERROR=%s\n', getReport(exception, 'extended', 'hyperlinks', 'off'));
    rethrow(exception)
end
clear cleanup
