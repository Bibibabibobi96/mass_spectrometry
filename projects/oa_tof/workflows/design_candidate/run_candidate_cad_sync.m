%RUN_CANDIDATE_CAD_SYNC Export an isolated candidate MPH to candidate CAD.
reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
modelPath = getenv('OATOF_CANDIDATE_MODEL_PATH');
outputDir = getenv('OATOF_CANDIDATE_CAD_DIR');
assert(~isempty(reportPath), 'COMSOL_BOOTSTRAP_REPORT is required.');
assert(isfile(modelPath), 'Candidate MPH is missing: %s', modelPath);
assert(~isempty(outputDir), 'OATOF_CANDIDATE_CAD_DIR is required.');

testDir = fileparts(mfilename('fullpath'));
projectRoot = fileparts(fileparts(testDir));
addpath(projectRoot, fullfile(projectRoot, 'cad'));
paths = oatof_paths();
addpath(paths.commonSolidWorksDir);

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));
try
    result = ms_export_oatof_to_solidworks(string(modelPath), string(outputDir), false);
    sw = result.solidWorks;
    assert(startsWith(string(sw.solidWorksRevision), '30.'), ...
        'Candidate CAD did not use SolidWorks 2022.');
    assert(sw.partCount == sw.assembly.componentCount, ...
        'Candidate CAD part/component counts differ.');
    assert(sw.assembly.saveErrors == 0 && sw.assembly.saveWarnings == 0, ...
        'Candidate assembly save reported errors or warnings.');
    fprintf(fid, 'MODEL=%s\nOUTPUT_DIR=%s\nASSEMBLY=%s\nCOMPONENTS=%d\nSTATUS=PASS\n', ...
        modelPath, outputDir, sw.assembly.sldasmPath, sw.assembly.componentCount);
catch exception
    fprintf(fid, 'STATUS=FAIL\nERROR=%s\n', getReport(exception, 'extended', 'hyperlinks', 'off'));
    rethrow(exception)
end
clear cleanup
