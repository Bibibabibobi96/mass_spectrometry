function [summary,audit] = analyze_simion_gui_recording(workbook,outputDir,nominalMassAmu,detectorCenterXmm,detectorCenterYmm,detectorRadiusMm,expectedParticles,expectedDetectorInstance)
%ANALYZE_SIMION_GUI_RECORDING Normalize and audit SIMION Data Recording.
%   Reads an Excel/CSV export containing ion number, TOF, x, y, and z,
%   validates the detector-plane records, converts them to the canonical
%   detector_crossing trace format, and reuses analyze_simion_mass_spectrum.

arguments
    workbook (1,1) string
    outputDir (1,1) string
    nominalMassAmu (1,1) double {mustBePositive} = 524
    detectorCenterXmm (1,1) double = 48.8
    detectorCenterYmm (1,1) double = 0
    detectorRadiusMm (1,1) double {mustBePositive} = 40
    expectedParticles (1,1) double {mustBeInteger,mustBePositive} = 5000
    expectedDetectorInstance (1,1) double {mustBeInteger,mustBePositive} = 4
end

assert(isfile(workbook),'GUI recording does not exist: %s',workbook);
if ~isfolder(outputDir), mkdir(outputDir); end

options = detectImportOptions(workbook,VariableNamingRule="preserve");
T = readtable(workbook,options);
assert(height(T) >= 10,'GUI recording contains only %d rows.',height(T));

names = string(T.Properties.VariableNames);
keys = lower(regexprep(names,'[^a-zA-Z0-9]',''));
tofName = find_name(names,keys,["tof","timeofflight"]);
xName = find_name(names,keys,["x","xmm"]);
yName = find_name(names,keys,["y","ymm"]);
zName = find_name(names,keys,["z","zmm"]);
ionName = find_name(names,keys,["ion","ionnumber","ionno","particlenumber"],true);
if strlength(ionName) == 0
    first = T.(names(1));
    assert(isnumeric(first) && all(isfinite(first)) && ...
        numel(unique(first)) == height(T), ...
        'Cannot infer ion-number variable from the first column.');
    ionName = names(1);
end

ion = double(T.(ionName));
tofUs = double(T.(tofName));
xMm = double(T.(xName));
yMm = double(T.(yName));
zMm = double(T.(zName));
valid = isfinite(ion) & isfinite(tofUs) & isfinite(xMm) & ...
    isfinite(yMm) & isfinite(zMm) & tofUs > 0;
assert(all(valid),'GUI recording has %d invalid or incomplete rows.',nnz(~valid));
assert(numel(unique(ion)) == numel(ion),'GUI recording contains duplicate ion numbers.');

localXmm = xMm-detectorCenterXmm;
localYmm = yMm-detectorCenterYmm;
radiusMm = hypot(localXmm,localYmm);
outsideDetector = radiusMm > detectorRadiusMm+1e-9;
assert(~any(outsideDetector),'%d records lie outside the detector radius.',nnz(outsideDetector));

normalizedTrace = fullfile(outputDir,'simion_gui_recording_normalized_trace.log');
fid = fopen(normalizedTrace,'w','n','UTF-8');
assert(fid >= 0,'Cannot create normalized trace: %s',normalizedTrace);
cleanup = onCleanup(@() fclose(fid));
for k = 1:numel(ion)
    fprintf(fid,['TRACE: detector_crossing ion=%d t=%.15g x=%.15g ' ...
        'y=%.15g z=%.15g r=%.15g zmax=%.15g\n'], ...
        ion(k),tofUs(k),xMm(k),yMm(k),zMm(k),radiusMm(k),zMm(k));
end
clear cleanup

summary = analyze_simion_mass_spectrum(normalizedTrace,outputDir, ...
    nominalMassAmu,detectorCenterXmm,detectorCenterYmm,detectorRadiusMm);

corrIon = pair_correlation(ion,tofUs);
corrX = pair_correlation(xMm,tofUs);
corrY = pair_correlation(yMm,tofUs);
corrRadius = pair_correlation(radiusMm,tofUs);
sequentialIonNumbers = isequal(sort(ion(:)),(min(ion):max(ion)).') && ...
    min(ion) == 1;
eventVariablePresent = any(contains(keys,"event"));
instanceVariablePresent = any(contains(keys,"instance"));
particleCountMatchesExpected = height(T) == expectedParticles && ...
    numel(unique(ion)) == expectedParticles;
if instanceVariablePresent
    instanceIndex = find(contains(keys,"instance"),1);
    instanceValues = double(T.(names(instanceIndex)));
    detectorInstanceMatchesExpected = all(isfinite(instanceValues)) && ...
        all(instanceValues == expectedDetectorInstance);
else
    detectorInstanceMatchesExpected = false;
end
detectorPlaneIsConstant = max(zMm)-min(zMm) <= 1e-9;
if particleCountMatchesExpected && sequentialIonNumbers && ...
        detectorPlaneIsConstant && detectorInstanceMatchesExpected
    recordingStructureStatus = "PASS_STRUCTURE_QUALITY_UNVERIFIED";
else
    recordingStructureStatus = "FAIL_RECORDING_PROVENANCE";
end

audit = table(string(workbook),height(T),expectedParticles, ...
    particleCountMatchesExpected,numel(unique(ion)),min(ion),max(ion), ...
    sequentialIonNumbers,min(zMm),max(zMm),max(zMm)-min(zMm), ...
    detectorPlaneIsConstant,max(radiusMm),eventVariablePresent, ...
    instanceVariablePresent,expectedDetectorInstance, ...
    detectorInstanceMatchesExpected,recordingStructureStatus, ...
    corrIon,corrX,corrY,corrRadius, ...
    'VariableNames',{'SourceWorkbook','Rows','ExpectedParticles', ...
    'ParticleCountMatchesExpected','UniqueIons','MinIon','MaxIon', ...
    'SequentialIonNumbers','MinZmm','MaxZmm','ZRangeMm', ...
    'DetectorPlaneIsConstant','MaxRadiusMm','EventVariablePresent', ...
    'InstanceVariablePresent','ExpectedDetectorInstance', ...
    'DetectorInstanceMatchesExpected','RecordingStructureStatus','CorrIonToTof', ...
    'CorrXToTof','CorrYToTof','CorrRadiusToTof'});
writetable(audit,fullfile(outputDir,'simion_gui_recording_audit.csv'));

report = fullfile(outputDir,'simion_gui_recording_audit.md');
fid = fopen(report,'w','n','UTF-8');
assert(fid >= 0,'Cannot write GUI recording audit: %s',report);
cleanup = onCleanup(@() fclose(fid));
fprintf(fid,'# SIMION GUI Data Recording audit\n\n');
fprintf(fid,'- Source: `%s`\n',workbook);
fprintf(fid,'- Rows / expected / unique ions: %d / %d / %d\n', ...
    height(T),expectedParticles,numel(unique(ion)));
fprintf(fid,'- Ion range / sequential: %.0f...%.0f / %d\n', ...
    min(ion),max(ion),sequentialIonNumbers);
fprintf(fid,'- Detector z min/max/range: %.12g / %.12g / %.12g mm\n', ...
    min(zMm),max(zMm),max(zMm)-min(zMm));
fprintf(fid,'- Maximum detector-local radius: %.12g mm\n',max(radiusMm));
fprintf(fid,'- Event / instance variables present: %d / %d\n', ...
    eventVariablePresent,instanceVariablePresent);
fprintf(fid,'- Expected detector instance / all records match: %d / %d\n', ...
    expectedDetectorInstance,detectorInstanceMatchesExpected);
fprintf(fid,'- Recording structure status: `%s`\n',recordingStructureStatus);
fprintf(fid,['- Trajectory quality is not encoded in a Data Recording export; ' ...
    'verify `trajectory quality=8` in the SIMION Fly dialog.\n']);
fprintf(fid,'- TOF correlation with ion/x/y/radius: %.12g / %.12g / %.12g / %.12g\n', ...
    corrIon,corrX,corrY,corrRadius);
clear cleanup
end

function name = find_name(names,keys,candidates,optional)
if nargin < 4, optional = false; end
index = find(ismember(keys,candidates),1);
if isempty(index)
    if optional
        name = "";
        return;
    end
    error('Required variable not found. Candidates=%s; imported=%s', ...
        strjoin(candidates,','),strjoin(names,','));
end
name = names(index);
end

function value = pair_correlation(a,b)
C = corrcoef(a,b);
value = C(1,2);
end
