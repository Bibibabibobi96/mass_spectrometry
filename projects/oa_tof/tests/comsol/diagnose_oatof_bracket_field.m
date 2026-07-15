reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
testDir = fileparts(mfilename('fullpath'));
componentDir = fileparts(fileparts(testDir));
addpath(componentDir);
paths = oatof_paths();
modelPath = fullfile(paths.comsolFormalDir, ...
    'MS_oaTOF_TwoStageRingStackReflectron_Final.mph');

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));

fprintf(fid, 'MATLAB_VERSION=%s\n', version);
fprintf(fid, 'JVM=%d\n', usejava('jvm'));
import com.comsol.model.util.*
fprintf(fid, 'COMSOL_VERSION=%s\n', char(ModelUtil.getComsolVersion));
fprintf(fid, 'MODEL=%s\n', modelPath);

model = mphload(modelPath, 'OaTofBracketDiagnostic');
xCenterMm = model.param.evaluate('x_accel_center') * 1e3;
shieldHalfMm = model.param.evaluate('accel_shield_half') * 1e3;
accelLengthMm = model.param.evaluate('L_accel') * 1e3;
repellerV = model.param.evaluate('V_repeller');
grid1V = model.param.evaluate('V_grid1');
targetEz = (repellerV - grid1V) / 3e-3;

fprintf(fid, 'ACCEL_CENTER_X_MM=%.12g\n', xCenterMm);
fprintf(fid, 'ACCEL_SHIELD_HALF_MM=%.12g\n', shieldHalfMm);
fprintf(fid, 'ACCEL_X_RANGE_MM=%.12g,%.12g\n', ...
    xCenterMm-shieldHalfMm, xCenterMm+shieldHalfMm);
fprintf(fid, 'ACCEL_Z_RANGE_MM=0,%.12g\n', accelLengthMm);

selection = model.component('comp1').selection('selbracket');
fprintf(fid, 'SELBRACKET_XMIN_EXPR=%s\n', ...
    char(selection.getString('xmin')));
fprintf(fid, 'SELBRACKET_XMAX_EXPR=%s\n', ...
    char(selection.getString('xmax')));
domainIds = selection.entities(3);
fprintf(fid, 'SELBRACKET_DOMAIN_COUNT=%d\n', numel(domainIds));
fprintf(fid, 'SELBRACKET_DOMAIN_IDS=%s\n', joinNumbers(domainIds));

selection.set('xmin', 'x_accel_center-accel_shield_half');
selection.set('xmax', 'x_accel_center+accel_shield_half');
selection.set('ymin', '-accel_shield_half');
selection.set('ymax', 'accel_shield_half');
selection.set('zmin', '0');
selection.set('zmax', 'L_accel');
parameterizedDomainIds = selection.entities(3);
fprintf(fid, 'PARAMETERIZED_SELBRACKET_DOMAIN_COUNT=%d\n', ...
    numel(parameterizedDomainIds));
fprintf(fid, 'PARAMETERIZED_SELBRACKET_DOMAIN_IDS=%s\n', ...
    joinNumbers(parameterizedDomainIds));

zMm = linspace(0.2, 2.8, 261);
coords = [repmat(xCenterMm, 1, numel(zMm)); zeros(1, numel(zMm)); zMm];
[potential, ezRaw] = mphinterp(model, {'V', 'es.Ez'}, ...
    'coord', coords, 'dataset', 'dset1');
relativeRawPct = 100 * (ezRaw-targetEz) / targetEz;
fitCoefficients = polyfit(zMm, potential, 1);
fitPotential = polyval(fitCoefficients, zMm);
fitEz = -fitCoefficients(1) * 1e3;
potentialResidualMv = 1e3 * (potential-fitPotential);
ezFromPotential = -gradient(potential, zMm*1e-3);
relativePotentialPct = 100 * (ezFromPotential-targetEz) / targetEz;

fprintf(fid, 'TARGET_EZ_V_PER_M=%.15g\n', targetEz);
fprintf(fid, 'RAW_EZ_MIN_MAX_V_PER_M=%.15g,%.15g\n', min(ezRaw), max(ezRaw));
fprintf(fid, 'RAW_RELATIVE_MIN_MAX_PCT=%.15g,%.15g\n', ...
    min(relativeRawPct), max(relativeRawPct));
fprintf(fid, 'RAW_RELATIVE_STD_PCT=%.15g\n', std(relativeRawPct));
fprintf(fid, 'POTENTIAL_FIT_EZ_V_PER_M=%.15g\n', fitEz);
fprintf(fid, 'POTENTIAL_FIT_RELATIVE_PCT=%.15g\n', ...
    100*(fitEz-targetEz)/targetEz);
fprintf(fid, 'POTENTIAL_MAX_RESIDUAL_MV=%.15g\n', ...
    max(abs(potentialResidualMv)));
fprintf(fid, 'POTENTIAL_DERIVATIVE_RELATIVE_MIN_MAX_PCT=%.15g,%.15g\n', ...
    min(relativePotentialPct), max(relativePotentialPct));

zCheckMm = [0.2, 0.5, 1, 1.5, 2, 2.5, 2.8];
checkCoords = [repmat(xCenterMm, 1, numel(zCheckMm)); ...
    zeros(1, numel(zCheckMm)); zCheckMm];
[vCheck, ezCheck] = mphinterp(model, {'V', 'es.Ez'}, ...
    'coord', checkCoords, 'dataset', 'dset1');
for index = 1:numel(zCheckMm)
    fprintf(fid, 'AXIS_Z_%.1fMM_V_EZ_REL=%.15g,%.15g,%.15g\n', ...
        zCheckMm(index), vCheck(index), ezCheck(index), ...
        100*(ezCheck(index)-targetEz)/targetEz);
end

offsetMm = [-0.5, 0, 0.5];
[dx, dy, dz] = ndgrid(offsetMm, offsetMm, [1, 1.5, 2]);
releaseCoords = [xCenterMm+dx(:)'; dy(:)'; dz(:)'];
releaseEz = mphinterp(model, 'es.Ez', 'coord', releaseCoords, ...
    'dataset', 'dset1');
releaseRelativePct = 100 * (releaseEz-targetEz) / targetEz;
fprintf(fid, 'RELEASE_CUBE_EZ_MIN_MAX_V_PER_M=%.15g,%.15g\n', ...
    min(releaseEz), max(releaseEz));
fprintf(fid, 'RELEASE_CUBE_RELATIVE_MIN_MAX_PCT=%.15g,%.15g\n', ...
    min(releaseRelativePct), max(releaseRelativePct));
fprintf(fid, 'RELEASE_CUBE_RELATIVE_STD_PCT=%.15g\n', ...
    std(releaseRelativePct));

fprintf(fid, 'STATUS=PASS\n');
clear cleanup
ModelUtil.remove('OaTofBracketDiagnostic');

function text = joinNumbers(values)
if isempty(values)
    text = '';
else
    text = strjoin(string(values), ',');
end
end
