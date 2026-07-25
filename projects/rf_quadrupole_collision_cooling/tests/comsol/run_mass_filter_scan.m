projectRoot = fileparts(fileparts(fileparts(mfilename('fullpath'))));
addpath(projectRoot);
addpath(fullfile(projectRoot, 'comsol'));
reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
scanConfigPath = getenv('RFQUAD_SCAN_CONFIG');
try
    scan = jsondecode(fileread(scanConfigPath));
    assert(~isempty(scan.cases), 'Mass-filter scan contains no cases.');
    for index = 1:numel(scan.cases)
        caseConfigPath=scan.cases(index).run_config;
        setenv('RFQUAD_RUN_CONFIG',caseConfigPath);
        caseConfig=jsondecode(fileread(caseConfigPath));
        assert(strcmp(caseConfig.workflow_id,'mass_filter_reference'), ...
            'Mass-filter scan received a non-mass-filter case.');
        ms_rf_quadrupole_no_collision(caseConfig);
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
