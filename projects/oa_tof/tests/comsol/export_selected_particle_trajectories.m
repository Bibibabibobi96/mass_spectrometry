% Export selected formal COMSOL particle trajectories on a sparse time grid.

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
outputCsv = getenv('OATOF_COMSOL_TRAJECTORY_CSV');
particleText = getenv('OATOF_TRAJECTORY_PARTICLE_IDS');
assert(~isempty(outputCsv), 'OATOF_COMSOL_TRAJECTORY_CSV is not set.');
if isempty(particleText), particleText = '18,52,97'; end
particleIds = str2double(split(string(particleText), ','));
assert(all(isfinite(particleIds)) && all(particleIds >= 1) && ...
    all(particleIds == round(particleIds)), 'Invalid particle identifiers.');

testDir = fileparts(mfilename('fullpath'));
projectDir = fileparts(fileparts(testDir));
addpath(projectDir);
paths = oatof_paths();
modelPath = fullfile(paths.comsolFormalDir, ...
        'oa_tof__model.mph');

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, 'MODEL=%s\n', modelPath);
fprintf(fid, 'OUTPUT_CSV=%s\n', outputCsv);
fprintf(fid, 'PARTICLE_IDS=%s\n', join(string(particleIds), ','));

try
    model = mphopen(modelPath);
    requestedTimes = (0:0.05:72.1) * 1e-6;
    pd = mphparticle(model, 'dataset', 'pdset1', ...
        'expr', {'qx','qy','qz'}, 't', requestedTimes, 'dataonly', 'on');
    t = pd.t(:);
    x = orient_time_by_particle(squeeze(pd.d1), numel(t));
    y = orient_time_by_particle(squeeze(pd.d2), numel(t));
    z = orient_time_by_particle(squeeze(pd.d3), numel(t));
    assert(max(particleIds) <= size(x, 2), ...
        'Requested particle exceeds exported particle count.');

    rows = table();
    for id = reshape(particleIds, 1, [])
        valid = isfinite(x(:,id)) & isfinite(y(:,id)) & isfinite(z(:,id));
        count = sum(valid);
        rows = [rows; table(repmat(id, count, 1), t(valid)*1e6, ... %#ok<AGROW>
            x(valid,id), y(valid,id), z(valid,id), ...
            'VariableNames', {'particle_id','time_us','x_mm','y_mm','z_mm'})];
    end
    outputDir = fileparts(outputCsv);
    if ~isfolder(outputDir), mkdir(outputDir); end
    writetable(rows, outputCsv);
    fprintf(fid, 'TIME_POINTS=%d\n', numel(t));
    fprintf(fid, 'EXPORTED_ROWS=%d\n', height(rows));
    fprintf(fid, 'PARTICLE_ARRAY_SIZE=%d,%d\n', size(x,1), size(x,2));
    fprintf(fid, 'STATUS=PASS\n');
catch exception
    fprintf(fid, 'STATUS=FAIL\nERROR=%s\n', ...
        getReport(exception, 'extended', 'hyperlinks', 'off'));
    rethrow(exception)
end
clear cleanup

function values = orient_time_by_particle(values, timeCount)
if size(values, 1) == timeCount
    return
end
if size(values, 2) == timeCount
    values = values.';
    return
end
error('Unexpected particle array shape %dx%d for %d times.', ...
    size(values,1), size(values,2), timeCount);
end
