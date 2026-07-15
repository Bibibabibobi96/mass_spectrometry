% MATLAB parity/reference implementation for the same fixed N=100 ions.
% The versioned canonical cross-solver definitions now live in
% config/analysis_contract.json and analysis/peak_metrics.py. Keep this
% script as an independent parity check; do not change its KDE/FWHM rules
% without intentionally updating the contract and Python regression values.
% Compare peak shape, not absolute resolution, for the same fixed N=100 ions.
% This intentionally uses the exported arrival tables only; no COMSOL re-solve.
testDir = fileparts(mfilename('fullpath'));
projectDir = fileparts(fileparts(testDir));
addpath(projectDir);
paths = oatof_paths();

runDir = fullfile(paths.artifactRoot, 'runs');
comsolCsv = fullfile(runDir, 'comsol_fixed_particle_closure', '2026-07-15', ...
    'candidate_524amu_fixedN100_real_dt0p2ns_particles.csv');
simionCsv = fullfile(runDir, 'simion_comsol_fixed_particle_closure', '2026-07-15', ...
    'simion_real_fixedN100_particles.csv');
resultsDir = fullfile(paths.artifactRoot, 'results', 'cross_solver');
if ~exist(resultsDir, 'dir'), mkdir(resultsDir); end
reportPath = fullfile(resultsDir, 'fixedN100_peak_shape_comparison.txt');
pngPath = fullfile(resultsDir, 'fixedN100_peak_shape_comparison.png');

comsol = readtable(comsolCsv);
simion = readtable(simionCsv, 'VariableNamingRule', 'preserve');
assert(isequal(comsol.Ion, simion.Ion), 'Ion identifiers must match exactly.');
comsolTof = double(comsol.TofUs(:))*1e-6;
simionTof = double(simion.TofUs(:))*1e-6;
assert(numel(comsolTof) == 100 && all(isfinite(comsolTof)) && all(isfinite(simionTof)), ...
    'Expected 100 finite, paired arrival times from both solvers.');

cm = peak_metrics(comsolTof, 524);
sm = peak_metrics(simionTof, 524);
[pairedR, pairedP] = corrcoef((comsolTof-mean(comsolTof))/std(comsolTof), ...
    (simionTof-mean(simionTof))/std(simionTof));
pairedR = pairedR(1,2); pairedP = pairedP(1,2);
initialZ = double(simion.Z0Mm(:));
initialEnergy = double(simion.EnergyEv(:));
comsolZCorrelation = correlation_scalar(comsolTof, initialZ);
simionZCorrelation = correlation_scalar(simionTof, initialZ);
comsolEnergyCorrelation = correlation_scalar(comsolTof, initialEnergy);
simionEnergyCorrelation = correlation_scalar(simionTof, initialEnergy);
comsolSourceFitR2 = source_fit_r2(comsolTof, simion);
simionSourceFitR2 = source_fit_r2(simionTof, simion);
ksDistance = two_sample_ks((comsolTof-mean(comsolTof))/std(comsolTof), ...
    (simionTof-mean(simionTof))/std(simionTof));

u = linspace(-6, 6, 2001);
comsolStd = (comsolTof-mean(comsolTof))/std(comsolTof);
simionStd = (simionTof-mean(simionTof))/std(simionTof);
dc = gaussian_kde(comsolStd, u);
ds = gaussian_kde(simionStd, u);
profileOverlap = trapz(u, min(dc, ds));

figure('Visible', 'off', 'Color', 'w', 'Position', [100 100 1250 760]);
tiledlayout(2,2, 'TileSpacing', 'compact', 'Padding', 'compact');
ax = nexttile; style_axes(ax);
plot(cm.massGrid, cm.intensity./max(cm.intensity), 'b-', 'LineWidth', 1.5); hold on;
plot(sm.massGrid, sm.intensity./max(sm.intensity), 'r-', 'LineWidth', 1.5);
xlabel('apparent mass [Da]'); ylabel('normalized intensity'); grid on;
legend('COMSOL, 0.2 ns', 'SIMION, quality 8', 'Location', 'best');
title('Absolute mass peaks');
ax = nexttile; style_axes(ax);
plot(u, dc./max(dc), 'b-', 'LineWidth', 1.5); hold on;
plot(u, ds./max(ds), 'r-', 'LineWidth', 1.5);
xlabel('(TOF - mean)/std'); ylabel('normalized intensity'); grid on;
legend('COMSOL', 'SIMION', 'Location', 'best');
title(sprintf('Shape-normalized overlap = %.3f', profileOverlap));
ax = nexttile; style_axes(ax);
plot(u, dc./max(dc)-ds./max(ds), 'k-', 'LineWidth', 1.5); hold on;
yline(0, 'k--');
xlabel('(TOF - mean)/std'); ylabel('COMSOL - SIMION intensity'); grid on;
title('Signed normalized-shape difference');
ax = nexttile; style_axes(ax);
q = linspace(0.01, 0.99, 99);
plot(quantile(simionStd, q), quantile(comsolStd, q), 'ko', 'MarkerSize', 3); hold on;
plot([-3 3], [-3 3], 'k--'); axis equal; xlim([-3 3]); ylim([-3 3]); grid on;
xlabel('SIMION standardized TOF quantile'); ylabel('COMSOL standardized TOF quantile');
title(sprintf('paired r = %.4f; KS = %.3f', pairedR, ksDistance));
sgtitle('524 amu fixed-particle cross-solver peak-shape comparison (N=100)');
print(gcf, pngPath, '-dpng', '-r180');
close(gcf);

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Cannot write report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, 'COMSOL_CSV=%s\nSIMION_CSV=%s\nPLOT=%s\n', comsolCsv, simionCsv, pngPath);
write_metrics(fid, 'COMSOL', cm);
write_metrics(fid, 'SIMION', sm);
fprintf(fid, 'PAIRED_STANDARDIZED_TOF_CORRELATION=%.12g\n', pairedR);
fprintf(fid, 'PAIRED_STANDARDIZED_TOF_CORRELATION_P=%.12g\n', pairedP);
fprintf(fid, 'COMSOL_TOF_INITIAL_Z_CORRELATION=%.12g\n', comsolZCorrelation);
fprintf(fid, 'SIMION_TOF_INITIAL_Z_CORRELATION=%.12g\n', simionZCorrelation);
fprintf(fid, 'COMSOL_TOF_INITIAL_ENERGY_CORRELATION=%.12g\n', comsolEnergyCorrelation);
fprintf(fid, 'SIMION_TOF_INITIAL_ENERGY_CORRELATION=%.12g\n', simionEnergyCorrelation);
fprintf(fid, 'COMSOL_SOURCE_Z2_ENERGY_XY_FIT_R2=%.12g\n', comsolSourceFitR2);
fprintf(fid, 'SIMION_SOURCE_Z2_ENERGY_XY_FIT_R2=%.12g\n', simionSourceFitR2);
fprintf(fid, 'STANDARDIZED_TWO_SAMPLE_KS_DISTANCE=%.12g\n', ksDistance);
fprintf(fid, 'STANDARDIZED_KDE_OVERLAP=%.12g\n', profileOverlap);
fprintf(fid, 'STATUS=PASS\n');
clear cleanup

function metrics = peak_metrics(tof, mass)
tof = tof(:);
metrics.meanTofUs = mean(tof)*1e6;
metrics.stdTofNs = std(tof)*1e9;
metrics.skewness = skewness(tof);
metrics.excessKurtosis = kurtosis(tof)-3;
apparentMass = mass*(tof./mean(tof)).^2;
sigma = std(apparentMass);
padding = max([0.20*(max(apparentMass)-min(apparentMass)); 4*sigma; 1e-6]);
grid = linspace(min(apparentMass)-padding, max(apparentMass)+padding, 1001);
density = gaussian_kde(apparentMass, grid);
[peak, peakIndex] = max(density);
half = peak/2;
leftIndex = find(density(1:peakIndex) < half, 1, 'last');
rightOffset = find(density(peakIndex:end) < half, 1, 'first');
assert(~isempty(leftIndex) && ~isempty(rightOffset), 'FWHM not bracketed.');
rightIndex = peakIndex + rightOffset - 1;
leftMass = interp1(density(leftIndex:leftIndex+1), grid(leftIndex:leftIndex+1), half, 'linear');
rightMass = interp1(density(rightIndex-1:rightIndex), grid(rightIndex-1:rightIndex), half, 'linear');
metrics.massFwhmDa = rightMass-leftMass;
metrics.resolution = mass/metrics.massFwhmDa;
metrics.leftHalfWidthDa = grid(peakIndex)-leftMass;
metrics.rightHalfWidthDa = rightMass-grid(peakIndex);
metrics.halfWidthAsymmetry = metrics.rightHalfWidthDa/metrics.leftHalfWidthDa;
localMax = density(2:end-1) > density(1:end-2) & density(2:end-1) >= density(3:end);
metrics.significantModes = sum(density(2:end-1) >= 0.10*peak & localMax);
metrics.massGrid = grid;
metrics.intensity = density;
end

function density = gaussian_kde(samples, grid)
samples = samples(:);
bandwidth = max(1.06*std(samples)*numel(samples)^(-1/5), 1e-12);
density = mean(exp(-0.5*((grid(:)-samples.')/bandwidth).^2), 2) ...
    ./ (sqrt(2*pi)*bandwidth);
end

function d = two_sample_ks(a, b)
values = sort([a(:); b(:)]);
d = max(abs(arrayfun(@(x) mean(a <= x)-mean(b <= x), values)));
end

function r = correlation_scalar(a, b)
C = corrcoef(a(:), b(:));
r = C(1,2);
end

function r2 = source_fit_r2(tof, source)
z = double(source.Z0Mm(:));
e = double(source.EnergyEv(:));
x = double(source.X0Mm(:));
y = double(source.Y0Mm(:));
X = [ones(numel(tof),1), z, z.^2, e, x, y];
fitted = X*(X\tof(:));
r2 = 1-sum((tof(:)-fitted).^2)/sum((tof(:)-mean(tof)).^2);
end

function write_metrics(fid, name, m)
fprintf(fid, '%s_MEAN_TOF_US=%.12g\n', name, m.meanTofUs);
fprintf(fid, '%s_STD_TOF_NS=%.12g\n', name, m.stdTofNs);
fprintf(fid, '%s_MASS_FWHM_DA=%.12g\n', name, m.massFwhmDa);
fprintf(fid, '%s_R_DIRECT=%.12g\n', name, m.resolution);
fprintf(fid, '%s_TOF_SKEWNESS=%.12g\n', name, m.skewness);
fprintf(fid, '%s_TOF_EXCESS_KURTOSIS=%.12g\n', name, m.excessKurtosis);
fprintf(fid, '%s_HALF_WIDTH_ASYMMETRY_RIGHT_OVER_LEFT=%.12g\n', name, m.halfWidthAsymmetry);
fprintf(fid, '%s_SIGNIFICANT_KDE_MODES=%.12g\n', name, m.significantModes);
end

function style_axes(ax)
ax.Color = 'w';
ax.XColor = 'k';
ax.YColor = 'k';
end
