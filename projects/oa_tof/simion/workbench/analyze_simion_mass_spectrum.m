function summary = analyze_simion_mass_spectrum(logFile, outputDir, nominalMassAmu, detectorCenterXmm, detectorCenterYmm, detectorRadiusMm)
%ANALYZE_SIMION_MASS_SPECTRUM Build mass/time spectra and detector maps.
%   Converts each detected TOF to apparent mass with
%       m_app = nominalMassAmu * (tof / mean(tof))^2
%   and writes particle, mass/time histogram, smooth-spectrum, detector-plane
%   density, summary, report, PNG, and FIG artifacts. Base MATLAB only.

arguments
    logFile (1,1) string
    outputDir (1,1) string
    nominalMassAmu (1,1) double {mustBePositive} = 524
    detectorCenterXmm (1,1) double = 48.8
    detectorCenterYmm (1,1) double = 0
    detectorRadiusMm (1,1) double {mustBePositive} = 40
end

assert(isfile(logFile), 'SIMION log does not exist: %s', logFile);
if ~isfolder(outputDir), mkdir(outputDir); end
massTag = sprintf('%gamu',nominalMassAmu);

lines = readlines(logFile);
pattern = ['^TRACE: detector_crossing ion=(\d+) t=([-+0-9.eE]+) ' ...
    'x=([-+0-9.eE]+) y=([-+0-9.eE]+) z=([-+0-9.eE]+) ' ...
    'r=([-+0-9.eE]+) zmax=([-+0-9.eE]+)'];
ion = zeros(numel(lines),1);
tofUs = zeros(numel(lines),1);
detectorXmm = zeros(numel(lines),1);
detectorYmm = zeros(numel(lines),1);
radiusMm = zeros(numel(lines),1);
used = 0;
for k = 1:numel(lines)
    token = regexp(lines(k), pattern, 'tokens', 'once');
    if isempty(token), continue; end
    used = used + 1;
    ion(used) = str2double(token{1});
    tofUs(used) = str2double(token{2});
    detectorXmm(used) = str2double(token{3});
    detectorYmm(used) = str2double(token{4});
    radiusMm(used) = str2double(token{6});
end
ion = ion(1:used);
tofUs = tofUs(1:used);
detectorXmm = detectorXmm(1:used);
detectorYmm = detectorYmm(1:used);
radiusMm = radiusMm(1:used);
assert(used >= 10, 'Only %d detector crossings found in %s.', used, logFile);
assert(numel(unique(ion)) == used, 'Duplicate detector-crossing ion numbers found.');
assert(all(isfinite(tofUs)) && all(tofUs > 0), 'Invalid detector TOF value.');

[ion, order] = sort(ion);
tofUs = tofUs(order);
detectorXmm = detectorXmm(order);
detectorYmm = detectorYmm(order);
radiusMm = radiusMm(order);
n = numel(tofUs);
meanTofUs = mean(tofUs);
stdTofUs = std(tofUs,0);
fwhmFactor = 2*sqrt(2*log(2));
fwhmTofNs = fwhmFactor*stdTofUs*1e3;
resolutionTof = meanTofUs/(2*fwhmFactor*stdTofUs);

q25Tof = linear_quantile(tofUs,0.25);
q75Tof = linear_quantile(tofUs,0.75);
iqrTof = q75Tof-q25Tof;
fdWidthTof = 2*iqrTof*n^(-1/3);
if ~(isfinite(fdWidthTof) && fdWidthTof > 0)
    fdWidthTof = 3.5*stdTofUs*n^(-1/3);
end
nBinsTof = ceil((max(tofUs)-min(tofUs))/fdWidthTof);
nBinsTof = min(80,max(30,nBinsTof));
[timeCounts,timeEdges] = histcounts(tofUs,nBinsTof);
timeCentersUs = (timeEdges(1:end-1)+timeEdges(2:end))/2;
timeCountsNorm = timeCounts/max(timeCounts);
timeBandwidthUs = 0.9*min(stdTofUs,iqrTof/1.34)*n^(-1/5);
if ~(isfinite(timeBandwidthUs) && timeBandwidthUs > 0)
    timeBandwidthUs = max(stdTofUs*n^(-1/5),eps(meanTofUs));
end
timeGridUs = linspace(min(tofUs)-3*timeBandwidthUs, ...
    max(tofUs)+3*timeBandwidthUs,1601).';
timeU = (timeGridUs-tofUs.')/timeBandwidthUs;
timeKde = mean(exp(-0.5*timeU.^2),2)/(timeBandwidthUs*sqrt(2*pi));
timeKdeNorm = timeKde/max(timeKde);
timeGaussian = exp(-0.5*((timeGridUs-meanTofUs)/stdTofUs).^2) ...
    /(stdTofUs*sqrt(2*pi));
timeGaussianNorm = timeGaussian/max(timeGaussian);
[~,peakTimeIndex] = max(timeKdeNorm);
peakTofUs = timeGridUs(peakTimeIndex);
[leftHalfTofUs,rightHalfTofUs] = half_height_crossings( ...
    timeGridUs,timeKdeNorm,peakTimeIndex);
empiricalFwhmTofNs = (rightHalfTofUs-leftHalfTofUs)*1e3;
resolutionEmpiricalTof = meanTofUs/(2*(rightHalfTofUs-leftHalfTofUs));

localXmm = detectorXmm-detectorCenterXmm;
localYmm = detectorYmm-detectorCenterYmm;
calculatedRadiusMm = hypot(localXmm,localYmm);
assert(max(abs(calculatedRadiusMm-radiusMm)) < 1e-6, ...
    'Detector center does not reproduce logged impact radius.');
centroidXmm = mean(localXmm);
centroidYmm = mean(localYmm);
rmsRadiusMm = sqrt(mean(calculatedRadiusMm.^2));
r95Mm = linear_quantile(calculatedRadiusMm,0.95);
maxRadiusMm = max(calculatedRadiusMm);
zoomHalfMm = max(5,ceil(1.1*max(abs([localXmm;localYmm]))));
densityEdges = linspace(-zoomHalfMm,zoomHalfMm,61);
[densityCounts,xEdges,yEdges] = histcounts2(localXmm,localYmm, ...
    densityEdges,densityEdges);
xDensityCenter = (xEdges(1:end-1)+xEdges(2:end))/2;
yDensityCenter = (yEdges(1:end-1)+yEdges(2:end))/2;

massAmu = nominalMassAmu*(tofUs/meanTofUs).^2;
meanMass = mean(massAmu);
stdMass = std(massAmu,0);
gaussianFwhmMass = fwhmFactor*stdMass;
resolutionGaussianMass = nominalMassAmu/gaussianFwhmMass;

q25 = linear_quantile(massAmu,0.25);
q75 = linear_quantile(massAmu,0.75);
iqrMass = q75-q25;
fdWidth = 2*iqrMass*n^(-1/3);
if ~(isfinite(fdWidth) && fdWidth > 0)
    fdWidth = 3.5*stdMass*n^(-1/3);
end
nBins = ceil((max(massAmu)-min(massAmu))/fdWidth);
nBins = min(80,max(30,nBins));
[counts,edges] = histcounts(massAmu,nBins);
massCenters = (edges(1:end-1)+edges(2:end))/2;
normalizedCounts = counts/max(counts);

bandwidth = 0.9*min(stdMass,iqrMass/1.34)*n^(-1/5);
if ~(isfinite(bandwidth) && bandwidth > 0)
    bandwidth = max(stdMass*n^(-1/5),eps(nominalMassAmu));
end
massGrid = linspace(min(massAmu)-3*bandwidth,max(massAmu)+3*bandwidth,1601).';
u = (massGrid-massAmu.')/bandwidth;
kde = mean(exp(-0.5*u.^2),2)/(bandwidth*sqrt(2*pi));
kdeNorm = kde/max(kde);
gaussian = exp(-0.5*((massGrid-meanMass)/stdMass).^2)/(stdMass*sqrt(2*pi));
gaussianNorm = gaussian/max(gaussian);

[~,peakIndex] = max(kdeNorm);
peakMass = massGrid(peakIndex);
[leftHalfMass,rightHalfMass] = half_height_crossings(massGrid,kdeNorm,peakIndex);
empiricalFwhmMass = rightHalfMass-leftHalfMass;
resolutionEmpirical = nominalMassAmu/empiricalFwhmMass;
leftHwhm = peakMass-leftHalfMass;
rightHwhm = rightHalfMass-peakMass;
asymmetryRatio = rightHwhm/leftHwhm;
fwhmDifferencePct = 100*(empiricalFwhmMass-gaussianFwhmMass)/gaussianFwhmMass;

candidatePeak = find(kdeNorm(2:end-1) > kdeNorm(1:end-2) & ...
    kdeNorm(2:end-1) >= kdeNorm(3:end))+1;
significantPeak = candidatePeak(kdeNorm(candidatePeak) >= 0.20);
significantPeakCount = numel(significantPeak);

centered = massAmu-meanMass;
sigmaPopulation = sqrt(mean(centered.^2));
skewnessMoment = mean(centered.^3)/sigmaPopulation^3;
excessKurtosis = mean(centered.^4)/sigmaPopulation^4-3;
tailFraction3Sigma = mean(abs(centered) > 3*stdMass);

sortedZ = sort(centered/stdMass);
probability = ((1:n)'-0.5)/n;
normalQuantile = sqrt(2)*erfinv(2*probability-1);
corrMatrix = corrcoef(normalQuantile,sortedZ);
qqCorrelation = corrMatrix(1,2);

reasons = strings(0,1);
if significantPeakCount > 1
    reasons(end+1) = "KDE存在多个高度不低于主峰20%的局部峰";
end
if abs(skewnessMoment) > 0.30
    reasons(end+1) = "偏度绝对值超过0.30";
end
if abs(excessKurtosis) > 0.75
    reasons(end+1) = "超额峰度绝对值超过0.75";
end
if abs(fwhmDifferencePct) > 10
    reasons(end+1) = "经验FWHM与2.3548sigma相差超过10%";
end
if asymmetryRatio < 0.75 || asymmetryRatio > 1.33
    reasons(end+1) = "左右半高宽比超出0.75到1.33";
end
if tailFraction3Sigma > 0.01
    reasons(end+1) = "三sigma外粒子比例超过1%";
end
if qqCorrelation < 0.995
    reasons(end+1) = "正态Q-Q相关系数低于0.995";
end
if isempty(reasons)
    peakShapeStatus = "PASS_NO_MATERIAL_ANOMALY";
    reasonText = "未触发预设异常判据";
else
    peakShapeStatus = "REVIEW_NON_GAUSSIAN_SHAPE";
    reasonText = strjoin(reasons,"；");
end

particleTable = table(ion,tofUs,massAmu,detectorXmm,detectorYmm, ...
    localXmm,localYmm,radiusMm, ...
    'VariableNames',{'Ion','TofUs','ApparentMassAmu','DetectorXmm', ...
    'DetectorYmm','DetectorLocalXmm','DetectorLocalYmm','DetectorRadiusMm'});
writetable(particleTable,fullfile(outputDir,"simion_"+massTag+"_particle_mass.csv"));
timeTable = table(timeCentersUs(:),timeCounts(:),timeCountsNorm(:), ...
    'VariableNames',{'TofUs','IntensityCounts','NormalizedIntensity'});
writetable(timeTable,fullfile(outputDir,"simion_"+massTag+"_intensity_time_spectrum.csv"));
timeSmoothTable = table(timeGridUs,timeKdeNorm,timeGaussianNorm, ...
    'VariableNames',{'TofUs','KdeNormalizedIntensity','GaussianNormalizedIntensity'});
writetable(timeSmoothTable,fullfile(outputDir,"simion_"+massTag+"_smooth_time_spectrum.csv"));
spectrumTable = table(massCenters(:),counts(:),normalizedCounts(:), ...
    'VariableNames',{'MassAmu','IntensityCounts','NormalizedIntensity'});
writetable(spectrumTable,fullfile(outputDir,"simion_"+massTag+"_intensity_mass_spectrum.csv"));
smoothTable = table(massGrid,kdeNorm,gaussianNorm, ...
    'VariableNames',{'MassAmu','KdeNormalizedIntensity','GaussianNormalizedIntensity'});
writetable(smoothTable,fullfile(outputDir,"simion_"+massTag+"_smooth_spectrum.csv"));
[densityXmm,densityYmm] = ndgrid(xDensityCenter,yDensityCenter);
densityTable = table(densityXmm(:),densityYmm(:),densityCounts(:), ...
    'VariableNames',{'DetectorLocalXBinCenterMm','DetectorLocalYBinCenterMm', ...
    'ImpactCounts'});
writetable(densityTable,fullfile(outputDir,"simion_"+massTag+"_detector_density.csv"));

summary = table(nominalMassAmu,n,meanTofUs,stdTofUs*1e3,fwhmTofNs, ...
    peakTofUs,empiricalFwhmTofNs,resolutionEmpiricalTof, ...
    meanMass,peakMass,gaussianFwhmMass,empiricalFwhmMass, ...
    resolutionTof,resolutionGaussianMass,resolutionEmpirical, ...
    skewnessMoment,excessKurtosis,leftHwhm,rightHwhm,asymmetryRatio, ...
    significantPeakCount,tailFraction3Sigma,qqCorrelation, ...
    fwhmDifferencePct,centroidXmm,centroidYmm,rmsRadiusMm,r95Mm,maxRadiusMm, ...
    peakShapeStatus,reasonText, ...
    'VariableNames',{'NominalMassAmu','DetectedParticles','MeanTofUs', ...
    'StdTofNs','FwhmTofNs','KdePeakTofUs','EmpiricalFwhmTofNs', ...
    'ResolutionFromEmpiricalTofFwhm','MeanApparentMassAmu','KdePeakMassAmu', ...
    'GaussianFwhmMassAmu','EmpiricalFwhmMassAmu','ResolutionFromTof', ...
    'ResolutionFromGaussianMass','ResolutionFromEmpiricalFwhm', ...
    'Skewness','ExcessKurtosis','LeftHwhmMassAmu','RightHwhmMassAmu', ...
    'HwhmAsymmetryRatio','SignificantPeakCount','TailFraction3Sigma', ...
    'QqCorrelation','EmpiricalVsGaussianFwhmDifferencePct', ...
    'ImpactCentroidXmm','ImpactCentroidYmm','ImpactRmsRadiusMm', ...
    'ImpactR95Mm','ImpactMaxRadiusMm', ...
    'PeakShapeStatus','PeakShapeReasons'});
writetable(summary,fullfile(outputDir,"simion_"+massTag+"_peak_shape_summary.csv"));

figureHandle = figure('Visible','off','Color','w','Theme','light', ...
    'Position',[100 100 1100 800]);
layout = tiledlayout(figureHandle,2,1,'TileSpacing','compact','Padding','compact');
axSpectrum = nexttile(layout,1);
set(axSpectrum,'Color','w','XColor','k','YColor','k', ...
    'GridColor',[0.75 0.75 0.75],'MinorGridColor',[0.85 0.85 0.85]);
bar(massCenters,normalizedCounts,1,'FaceColor',[0.28 0.52 0.82], ...
    'EdgeColor','none','FaceAlpha',0.55);
hold on;
plot(massGrid,kdeNorm,'Color',[0.80 0.16 0.12],'LineWidth',2.2);
plot(massGrid,gaussianNorm,'k--','LineWidth',1.6);
xline(nominalMassAmu,':','Color',[0.2 0.2 0.2],'LineWidth',1.2);
yline(0.5,':','Color',[0.4 0.4 0.4]);
grid on; box on;
xlabel('Apparent mass (amu)'); ylabel('Normalized intensity');
legend('Histogram','Gaussian KDE','Matched Gaussian',sprintf('%g amu',nominalMassAmu), ...
    'Location','best','Color','w','TextColor','k');
title(sprintf(['SIMION intensity-mass spectrum: N=%d, empirical FWHM=%.6g amu, ' ...
    'R=%.1f'],n,empiricalFwhmMass,resolutionEmpirical));

axQq = nexttile(layout,2);
set(axQq,'Color','w','XColor','k','YColor','k', ...
    'GridColor',[0.75 0.75 0.75],'MinorGridColor',[0.85 0.85 0.85]);
plot(normalQuantile,sortedZ,'.','Color',[0.16 0.42 0.70],'MarkerSize',8);
hold on; plot([min(normalQuantile) max(normalQuantile)], ...
    [min(normalQuantile) max(normalQuantile)],'k--','LineWidth',1.4);
grid on; box on; axis equal;
xlabel('Theoretical normal quantile'); ylabel('Observed standardized mass');
title(sprintf('Normal Q-Q audit: r=%.6f, skew=%.4f, excess kurtosis=%.4f', ...
    qqCorrelation,skewnessMoment,excessKurtosis));
overallTitle = sgtitle(layout,sprintf('%g amu SIMION peak-shape audit — %s',nominalMassAmu,peakShapeStatus), ...
    'Interpreter','none');
overallTitle.Color = 'k';
exportgraphics(figureHandle,fullfile(outputDir,"simion_"+massTag+"_intensity_mass_spectrum.png"), ...
    'Resolution',220);
savefig(figureHandle,fullfile(outputDir,"simion_"+massTag+"_intensity_mass_spectrum.fig"));
close(figureHandle);

timeFigure = figure('Visible','off','Color','w','Theme','light', ...
    'Position',[100 100 1050 560]);
timeAxes = axes(timeFigure);
bar(timeCentersUs,timeCountsNorm,1,'FaceColor',[0.28 0.52 0.82], ...
    'EdgeColor','none','FaceAlpha',0.55);
hold on;
plot(timeGridUs,timeKdeNorm,'Color',[0.80 0.16 0.12],'LineWidth',2.2);
plot(timeGridUs,timeGaussianNorm,'k--','LineWidth',1.6);
xline(meanTofUs,':','Color',[0.2 0.2 0.2],'LineWidth',1.2);
yline(0.5,':','Color',[0.4 0.4 0.4]);
set(timeAxes,'Color','w','XColor','k','YColor','k', ...
    'GridColor',[0.75 0.75 0.75]);
grid on; box on;
xlabel('Detector time of flight (us)'); ylabel('Normalized intensity');
legend('Histogram','Gaussian KDE','Matched Gaussian','Mean TOF', ...
    'Location','best','Color','w','TextColor','k');
title(sprintf(['%g amu SIMION intensity-time spectrum: N=%d, ' ...
    'empirical FWHM=%.6g ns, R=%.1f'],nominalMassAmu,n, ...
    empiricalFwhmTofNs,resolutionEmpiricalTof));
exportgraphics(timeFigure,fullfile(outputDir, ...
    "simion_"+massTag+"_intensity_time_spectrum.png"),'Resolution',220);
savefig(timeFigure,fullfile(outputDir, ...
    "simion_"+massTag+"_intensity_time_spectrum.fig"));
close(timeFigure);

impactFigure = figure('Visible','off','Color','w','Theme','light', ...
    'Position',[100 100 1200 570]);
impactLayout = tiledlayout(impactFigure,1,2,'TileSpacing','compact', ...
    'Padding','compact');
impactDensityAxes = nexttile(impactLayout,1);
imagesc(impactDensityAxes,xDensityCenter,yDensityCenter,densityCounts.');
axis(impactDensityAxes,'xy'); axis(impactDensityAxes,'equal');
hold(impactDensityAxes,'on');
scatter(impactDensityAxes,localXmm,localYmm,5,'k','filled', ...
    'MarkerFaceAlpha',0.08,'MarkerEdgeAlpha',0.08);
xlim(impactDensityAxes,[-zoomHalfMm zoomHalfMm]);
ylim(impactDensityAxes,[-zoomHalfMm zoomHalfMm]);
set(impactDensityAxes,'Color','w','XColor','k','YColor','k');
grid(impactDensityAxes,'on'); box(impactDensityAxes,'on');
xlabel(impactDensityAxes,'Detector local x (mm)');
ylabel(impactDensityAxes,'Detector local y (mm)');
densityColorbar = colorbar(impactDensityAxes);
densityColorbar.Label.String = 'Impacts per bin';
title(impactDensityAxes,sprintf('Zoomed 2D impact density (%d particles)',n));

impactScatterAxes = nexttile(impactLayout,2);
scatter(impactScatterAxes,localXmm,localYmm,8,tofUs,'filled', ...
    'MarkerFaceAlpha',0.45,'MarkerEdgeAlpha',0.15);
hold(impactScatterAxes,'on');
theta = linspace(0,2*pi,721);
plot(impactScatterAxes,detectorRadiusMm*cos(theta), ...
    detectorRadiusMm*sin(theta),'k-','LineWidth',1.8);
plot(impactScatterAxes,0,0,'k+','MarkerSize',10,'LineWidth',1.5);
axis(impactScatterAxes,'equal');
xlim(impactScatterAxes,1.05*[-detectorRadiusMm detectorRadiusMm]);
ylim(impactScatterAxes,1.05*[-detectorRadiusMm detectorRadiusMm]);
set(impactScatterAxes,'Color','w','XColor','k','YColor','k');
grid(impactScatterAxes,'on'); box(impactScatterAxes,'on');
xlabel(impactScatterAxes,'Detector local x (mm)');
ylabel(impactScatterAxes,'Detector local y (mm)');
tofColorbar = colorbar(impactScatterAxes);
tofColorbar.Label.String = 'TOF (us)';
title(impactScatterAxes,sprintf(['Full detector: centroid=(%.3f, %.3f) mm, ' ...
    'r95=%.3f mm, max=%.3f mm'],centroidXmm,centroidYmm,r95Mm,maxRadiusMm));
colormap(impactFigure,turbo);
impactTitle = sgtitle(impactLayout,sprintf( ...
    '%g amu SIMION detector-plane impact distribution',nominalMassAmu));
impactTitle.Color = 'k';
exportgraphics(impactFigure,fullfile(outputDir, ...
    "simion_"+massTag+"_detector_impact_distribution.png"),'Resolution',220);
savefig(impactFigure,fullfile(outputDir, ...
    "simion_"+massTag+"_detector_impact_distribution.fig"));
close(impactFigure);

reportFile = fullfile(outputDir,"simion_"+massTag+"_peak_shape_report.md");
fid = fopen(reportFile,'w','n','UTF-8');
assert(fid >= 0,'Cannot write report: %s',reportFile);
cleanup = onCleanup(@() fclose(fid));
fprintf(fid,'# SIMION %g amu intensity-mass spectrum and peak-shape audit\n\n',nominalMassAmu);
fprintf(fid,'- Source log: `%s`\n',logFile);
fprintf(fid,'- Detected: %d/%d\n',n,n);
fprintf(fid,'- TOF mean / sigma / FWHM: %.12g us / %.12g ns / %.12g ns\n', ...
    meanTofUs,stdTofUs*1e3,fwhmTofNs);
fprintf(fid,'- TOF-equivalent R: %.12g\n',resolutionTof);
fprintf(fid,'- KDE peak TOF / empirical TOF FWHM: %.12g us / %.12g ns\n', ...
    peakTofUs,empiricalFwhmTofNs);
fprintf(fid,'- Empirical-TOF-FWHM R: %.12g\n',resolutionEmpiricalTof);
fprintf(fid,'- KDE peak mass: %.12g amu\n',peakMass);
fprintf(fid,'- Gaussian / empirical mass FWHM: %.12g / %.12g amu\n', ...
    gaussianFwhmMass,empiricalFwhmMass);
fprintf(fid,'- Empirical-FWHM R: %.12g\n',resolutionEmpirical);
fprintf(fid,'- Skewness / excess kurtosis: %.12g / %.12g\n', ...
    skewnessMoment,excessKurtosis);
fprintf(fid,'- Left/right HWHM ratio: %.12g\n',asymmetryRatio);
fprintf(fid,'- Significant KDE peaks: %d\n',significantPeakCount);
fprintf(fid,'- Tail fraction outside 3 sigma: %.12g\n',tailFraction3Sigma);
fprintf(fid,'- Normal Q-Q correlation: %.12g\n',qqCorrelation);
fprintf(fid,'- Impact centroid local x/y: %.12g / %.12g mm\n', ...
    centroidXmm,centroidYmm);
fprintf(fid,'- Impact RMS / r95 / max radius: %.12g / %.12g / %.12g mm\n', ...
    rmsRadiusMm,r95Mm,maxRadiusMm);
fprintf(fid,'- Status: **%s**\n',peakShapeStatus);
fprintf(fid,'- Reasons: %s\n',reasonText);
clear cleanup
end

function q = linear_quantile(x,p)
x = sort(x(:));
position = 1+(numel(x)-1)*p;
lower = floor(position);
upper = ceil(position);
if lower == upper
    q = x(lower);
else
    q = x(lower)+(position-lower)*(x(upper)-x(lower));
end
end

function [leftCross,rightCross] = half_height_crossings(x,y,peakIndex)
leftBelow = find(y(1:peakIndex) <= 0.5,1,'last');
rightOffset = find(y(peakIndex:end) <= 0.5,1,'first');
assert(~isempty(leftBelow) && ~isempty(rightOffset), ...
    'KDE grid does not bracket both half-height crossings.');
rightBelow = peakIndex+rightOffset-1;
leftCross = linear_crossing(x(leftBelow),y(leftBelow), ...
    x(leftBelow+1),y(leftBelow+1),0.5);
rightCross = linear_crossing(x(rightBelow-1),y(rightBelow-1), ...
    x(rightBelow),y(rightBelow),0.5);
end

function xCross = linear_crossing(x1,y1,x2,y2,target)
xCross = x1+(target-y1)*(x2-x1)/(y2-y1);
end
