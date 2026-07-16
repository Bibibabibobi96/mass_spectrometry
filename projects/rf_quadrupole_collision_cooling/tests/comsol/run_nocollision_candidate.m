projectRoot = fileparts(fileparts(fileparts(mfilename('fullpath'))));
addpath(projectRoot);
addpath(fullfile(projectRoot, 'comsol'));
reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
try
    result = ms_rf_quadrupole_no_collision(); %#ok<NASGU>
    fid = fopen(reportPath, 'w');
    fprintf(fid, 'STATUS=PASS\n');
    fclose(fid);
catch ME
    fid = fopen(reportPath, 'w');
    fprintf(fid, 'STATUS=FAIL\nERROR=%s\n', getReport(ME,'extended'));
    fclose(fid);
    rethrow(ME)
end
