reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
assert(~isempty(reportPath), 'COMSOL_BOOTSTRAP_REPORT is required.');

testDir = fileparts(mfilename('fullpath'));
detectorSuite = testsuite(fullfile(testDir, 'OaTofDetectorArrivalTest.m'));
fieldSuite = testsuite(fullfile(testDir, 'OaTofFieldIdealizationTest.m'));
suite = [detectorSuite(:).', fieldSuite(:).'];
results = run(suite);

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, 'TESTS=%d\n', numel(results));
fprintf(fid, 'PASSED=%d\n', sum([results.Passed]));
fprintf(fid, 'FAILED=%d\n', sum([results.Failed]));
fprintf(fid, 'INCOMPLETE=%d\n', sum([results.Incomplete]));
for index = 1:numel(results)
    fprintf(fid, 'TEST_%02d=%s|PASSED=%d|FAILED=%d|INCOMPLETE=%d\n', ...
        index, results(index).Name, results(index).Passed, ...
        results(index).Failed, results(index).Incomplete);
end
assert(~isempty(results), 'The oaTOF MATLAB unit-test suite is empty.');
assert(all([results.Passed]), 'One or more oaTOF MATLAB unit tests failed.');
fprintf(fid, 'STATUS=PASS\n');
clear cleanup
