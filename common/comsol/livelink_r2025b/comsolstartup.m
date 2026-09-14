bootstrapTaskPath = getenv('COMSOL_MATLAB_TASK');
bootstrapReportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
try
    assert(~isempty(bootstrapTaskPath), 'COMSOL_MATLAB_TASK is not set.');
    assert(~isempty(bootstrapReportPath), 'COMSOL_BOOTSTRAP_REPORT is not set.');
    writeBootstrapReport(bootstrapReportPath, "RUNNING", "");
    executeComsolTask(bootstrapTaskPath);
    writeBootstrapReport(bootstrapReportPath, "PASS", "");
    exit(0);
catch ME
    if ~isempty(bootstrapReportPath)
        try
            writeBootstrapReport(bootstrapReportPath, "FAIL", getReport(ME, 'extended'));
        catch reportException
            fprintf(2, 'COMSOL bootstrap report write failed: %s\n', ...
                getReport(reportException, 'extended'));
        end
    end
    exit(2);
end

function executeComsolTask(taskPath)
% RUN executes scripts in the caller workspace, so isolate project variables
% from the bootstrap paths needed after the task returns.
run(taskPath);
end

function writeBootstrapReport(path, status, errorText)
fid = fopen(path, 'w', 'n', 'UTF-8');
if fid < 0
    error('COMSOL:BootstrapReportWrite', ...
        'Cannot write COMSOL bootstrap report: %s', path);
end
cleanup = onCleanup(@() fclose(fid)); %#ok<NASGU>
fprintf(fid, 'STATUS=%s\n', status);
if strlength(string(errorText)) > 0
    fprintf(fid, 'ERROR=%s\n', errorText);
end
end
