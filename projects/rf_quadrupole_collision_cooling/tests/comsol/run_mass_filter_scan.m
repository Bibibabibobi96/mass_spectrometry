projectRoot = fileparts(fileparts(fileparts(mfilename('fullpath'))));
addpath(projectRoot);
addpath(fullfile(projectRoot, 'comsol'));
reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
scanConfigPath = getenv('RFQUAD_SCAN_CONFIG');
try
    scan = jsondecode(fileread(scanConfigPath));
    assert(~isempty(scan.cases), 'Mass-filter scan contains no cases.');
    for index = 1:numel(scan.cases)
        setenv('RFQUAD_RUN_CONFIG', scan.cases(index).run_config);
        ms_rf_quadrupole_no_collision();
    end
    setenv('RFQUAD_RUN_CONFIG', '');
    fid = fopen(reportPath, 'w');
    fprintf(fid, 'STATUS=PASS\nCASES=%d\n', numel(scan.cases));
    fclose(fid);
catch ME
    setenv('RFQUAD_RUN_CONFIG', '');
    fid = fopen(reportPath, 'w');
    fprintf(fid, 'STATUS=FAIL\nERROR=%s\n', getReport(ME,'extended'));
    fclose(fid);
    rethrow(ME)
end
