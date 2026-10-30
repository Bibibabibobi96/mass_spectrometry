classdef comsolstartupReportTest < matlab.unittest.TestCase
    % Pure startup report transport; no COMSOL or solver invocation.
    properties (TestParameter)
        outcome = struct('pass', struct('fail', false, 'code', 0, 'status', "PASS"), ...
            'fail', struct('fail', true, 'code', 2, 'status', "FAIL"));
    end
    methods (Test)
        function preservesTaskDiagnostics(testCase, outcome)
            fixture = startupFixture(testCase);
            writeTask(fixture.task, fixture.report, outcome.fail);
            run(fixture.startup);
            actual = fileread(fixture.report);
            global COMSOL_TEST_EXIT_CODE
            testCase.verifyEqual(COMSOL_TEST_EXIT_CODE, outcome.code);
            testCase.verifySubstring(actual, "VACUUM_MESH_HAS_PROBLEMS=1");
            testCase.verifySubstring(actual, "VACUUM_MESH_ELEMENTS=37");
            testCase.verifySubstring(actual, "STATUS=" + outcome.status);
        end
        function bootstrapFailureWithoutTaskReport(testCase)
            fixture = startupFixture(testCase);
            writeText(fixture.report, "OLD_ATTEMPT_SENTINEL STATUS=PASS");
            writeText(fixture.task, "error('Test:Primary','original failure');");
            run(fixture.startup);
            actual = fileread(fixture.report);
            global COMSOL_TEST_EXIT_CODE
            testCase.verifyEqual(COMSOL_TEST_EXIT_CODE, 2);
            testCase.verifySubstring(actual, 'STATUS=FAIL');
            testCase.verifySubstring(actual, 'original failure');
            testCase.verifyFalse(contains(actual, 'OLD_ATTEMPT_SENTINEL'));
        end
    end
end

function fixture = startupFixture(testCase)
folder = tempname;
mkdir(folder);
testCase.addTeardown(@() rmdir(folder, 's'));
oldTask = getenv('COMSOL_MATLAB_TASK');
oldReport = getenv('COMSOL_BOOTSTRAP_REPORT');
testCase.addTeardown(@() setenv('COMSOL_MATLAB_TASK', oldTask));
testCase.addTeardown(@() setenv('COMSOL_BOOTSTRAP_REPORT', oldReport));
writeText(fullfile(folder, 'exit.m'), ...
    "function exit(code); global COMSOL_TEST_EXIT_CODE; COMSOL_TEST_EXIT_CODE=code; end");
testCase.applyFixture(matlab.unittest.fixtures.PathFixture(folder));
fixture.task = fullfile(folder, 'task.m');
fixture.report = fullfile(folder, 'report.txt');
fixture.startup = fullfile(fileparts(fileparts(mfilename('fullpath'))), ...
    'livelink_r2025b', 'comsolstartup.m');
setenv('COMSOL_MATLAB_TASK', fixture.task);
setenv('COMSOL_BOOTSTRAP_REPORT', fixture.report);
end

function writeTask(task, report, shouldFail)
body = sprintf("fid=fopen('%s','w','n','UTF-8'); fprintf(fid,'VACUUM_MESH_HAS_PROBLEMS=1\\nVACUUM_MESH_ELEMENTS=37'); fclose(fid);", ...
    strrep(report, "'", "''"));
if shouldFail
    body = body + " error('Test:Primary','original mesh failure');";
end
writeText(task, body);
end

function writeText(path, value)
fid = fopen(path, 'w', 'n', 'UTF-8');
cleanup = onCleanup(@() fclose(fid)); %#ok<NASGU>
fprintf(fid, '%s', value);
end
