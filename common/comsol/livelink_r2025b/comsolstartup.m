taskPath = getenv('COMSOL_MATLAB_TASK');
reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
try
    assert(~isempty(taskPath), 'COMSOL_MATLAB_TASK is not set.');
    run(taskPath);
    exit(0);
catch ME
    if ~isempty(reportPath)
        fid = fopen(reportPath, 'a');
        if fid >= 0
            fprintf(fid, 'STATUS=FAIL\nERROR=%s\n', getReport(ME, 'extended'));
            fclose(fid);
        end
    end
    exit(2);
end
