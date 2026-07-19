% Read-only runtime validation of the shared detector-arrival extractor.
reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
modelPath = getenv('OATOF_DETECTOR_EXTRACTOR_MODEL');
referenceCsv = getenv('OATOF_DETECTOR_EXTRACTOR_REFERENCE_CSV');
assert(isfile(modelPath),'Saved MPH is missing: %s',modelPath);
testDir = fileparts(mfilename('fullpath'));
projectRoot = fileparts(fileparts(testDir));
addpath(fullfile(projectRoot,'comsol'));
fid = fopen(reportPath,'w');
assert(fid>=0,'Could not open report: %s',reportPath);
cleanup = onCleanup(@() fclose(fid));

model = mphopen(modelPath);
expectedTof = model.param.evaluate('t_detector_ref');
fineStep = model.param.evaluate('cpt_dt_fine');
simulationEnd = model.param.evaluate('cpt_t_end');
extractTimes = unique([linspace(0,simulationEnd,2001), ...
    expectedTof+(-300e-9:fineStep:300e-9),simulationEnd]);
pd = mphparticle(model,'dataset','pdset1','expr',{'qx','qy','qz'}, ...
    't',extractTimes,'dataonly','on');
t = pd.t(:);
x = orient(squeeze(pd.d1),numel(t));
y = orient(squeeze(pd.d2),numel(t));
z = orient(squeeze(pd.d3),numel(t));
detectorZ = model.param.evaluate('detector_z')*1e3;
arrivals = oatof_extract_detector_arrivals(t,x,y,z,detectorZ,1e-3,0.5);
assert(all(arrivals.hit),'Strict detector extraction found %d/%d hits.',sum(arrivals.hit),numel(arrivals.hit));
fprintf(fid,'MODEL=%s\nHIT=%d/%d\n',modelPath,sum(arrivals.hit),numel(arrivals.hit));
for event = unique(arrivals.event).'
    fprintf(fid,'EVENT_%s=%d\n',upper(event),sum(arrivals.event==event));
end
if ~isempty(referenceCsv)
    reference = readtable(referenceCsv,'VariableNamingRule','preserve');
    assert(height(reference)==numel(arrivals.time_s),'Reference particle count differs.');
    deltaNs = (arrivals.time_s*1e6-reference.tof_us)*1e3;
    fprintf(fid,'REFERENCE=%s\nTOF_RMS_DELTA_NS=%.12g\nTOF_MAX_ABS_DELTA_NS=%.12g\n', ...
        referenceCsv,sqrt(mean(deltaNs.^2)),max(abs(deltaNs)));
    assert(max(abs(deltaNs))<1e-3,'Strict extraction differs from the archived diagnostic by >=1 ps.');
end
fprintf(fid,'STATUS=PASS\n');
clear cleanup

function values = orient(values,timeCount)
if size(values,1)==timeCount, return; end
if size(values,2)==timeCount, values=values.'; return; end
error('Unexpected particle array shape %dx%d.',size(values,1),size(values,2));
end
