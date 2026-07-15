function summary = analyze_simion_peak_shape_sources(particleCsv, outputDir, nominalMassAmu)
%ANALYZE_SIMION_PEAK_SHAPE_SOURCES Diagnose initial-condition TOF mapping.
%   PARTICLECSV is produced by analyze_ideal_field_log.ps1 and contains the
%   fixed initial coordinates, energy, detector TOF, and detector radius.

arguments
    particleCsv (1,1) string
    outputDir (1,1) string
    nominalMassAmu (1,1) double {mustBePositive} = 524
end
assert(isfile(particleCsv),'Particle CSV does not exist: %s',particleCsv);
if ~isfolder(outputDir), mkdir(outputDir); end
massTag = sprintf('%gamu',nominalMassAmu);
T = readtable(particleCsv);
required = ["X0Mm" "Y0Mm" "Z0Mm" "EnergyEv" "TofUs"];
assert(all(ismember(required,string(T.Properties.VariableNames))), ...
    'Particle CSV is missing required variables.');

x = T.X0Mm; y = T.Y0Mm; z = T.Z0Mm; energy = T.EnergyEv; tof = T.TofUs;
n = numel(tof);
zc = z-mean(z);
xc = x-mean(x);
yc = y-mean(y);
ec = energy-mean(energy);

linearDesign = [ones(n,1),xc,yc,zc,ec];
linearCoefficient = linearDesign\tof;
linearFit = linearDesign*linearCoefficient;
linearR2 = model_r_squared(tof,linearFit);

quadraticDesign = [linearDesign,zc.^2];
quadraticCoefficient = quadraticDesign\tof;
quadraticFit = quadraticDesign*quadraticCoefficient;
quadraticR2 = model_r_squared(tof,quadraticFit);
zOnlyDesign = [ones(n,1),zc,zc.^2];
zOnlyCoefficient = zOnlyDesign\tof;
zOnlyFit = zOnlyDesign*zOnlyCoefficient;
zOnlyQuadraticR2 = model_r_squared(tof,zOnlyFit);

zCurvatureUsPerMm2 = zOnlyCoefficient(3);
if abs(zCurvatureUsPerMm2) > eps
    vertexZMm = mean(z)-zOnlyCoefficient(2)/(2*zCurvatureUsPerMm2);
else
    vertexZMm = NaN;
end
vertexInsideSource = vertexZMm >= min(z) && vertexZMm <= max(z);

correlation = corrcoef([tof,x,y,z,energy]);
corrTofX = correlation(1,2);
corrTofY = correlation(1,3);
corrTofZ = correlation(1,4);
corrTofEnergy = correlation(1,5);

zEdges = linspace(min(z),max(z),11);
zBin = discretize(z,zEdges);
zCenter = ((zEdges(1:end-1)+zEdges(2:end))/2).';
binCount = zeros(10,1); binMeanTofUs = nan(10,1); binStdTofNs = nan(10,1);
for k = 1:10
    inBin = zBin == k;
    binCount(k) = nnz(inBin);
    binMeanTofUs(k) = mean(tof(inBin));
    binStdTofNs(k) = 1e3*std(tof(inBin),0);
end
zBinTable = table(zCenter,binCount,binMeanTofUs,binStdTofNs, ...
    'VariableNames',{'Z0BinCenterMm','ParticleCount','MeanTofUs','StdTofNs'});
writetable(zBinTable,fullfile(outputDir,"simion_"+massTag+"_z_mapping_bins.csv"));

summary = table(n,linearR2,quadraticR2,zOnlyQuadraticR2, ...
    zCurvatureUsPerMm2,vertexZMm,vertexInsideSource, ...
    corrTofX,corrTofY,corrTofZ,corrTofEnergy, ...
    'VariableNames',{'Particles','LinearAllPredictorsR2', ...
    'QuadraticZPlusLinearPredictorsR2','ZOnlyQuadraticR2', ...
    'ZCurvatureUsPerMm2','QuadraticVertexZMm','VertexInsideSource', ...
    'CorrTofX0','CorrTofY0','CorrTofZ0','CorrTofEnergy'});
writetable(summary,fullfile(outputDir,"simion_"+massTag+"_peak_shape_source_summary.csv"));

fig = figure('Visible','off','Color','w','Theme','light', ...
    'Position',[100 100 1050 650]);
axesHandle = axes(fig);
set(axesHandle,'Color','w','XColor','k','YColor','k', ...
    'GridColor',[0.75 0.75 0.75],'MinorGridColor',[0.85 0.85 0.85]);
scatter(z,tof,12,energy,'filled','MarkerFaceAlpha',0.45);
hold on;
zPlot = linspace(min(z),max(z),401).';
zcPlot = zPlot-mean(z);
plot(zPlot,zOnlyCoefficient(1)+zOnlyCoefficient(2)*zcPlot+ ...
    zOnlyCoefficient(3)*zcPlot.^2,'k-','LineWidth',2.2);
if vertexInsideSource
    xline(vertexZMm,'r--','LineWidth',1.5);
end
grid on; box on;
xlabel('Initial z (mm)'); ylabel('Detector TOF (us)');
colorbar; colormap(parula); title(sprintf([ ...
    '%g amu initial-z mapping: quadratic R^2=%.4f, vertex z=%.4f mm'], ...
    nominalMassAmu,zOnlyQuadraticR2,vertexZMm));
exportgraphics(fig,fullfile(outputDir,"simion_"+massTag+"_initial_z_tof_mapping.png"), ...
    'Resolution',220);
savefig(fig,fullfile(outputDir,"simion_"+massTag+"_initial_z_tof_mapping.fig"));
close(fig);
end

function r2 = model_r_squared(observed,fitted)
r2 = 1-sum((observed-fitted).^2)/sum((observed-mean(observed)).^2);
end
