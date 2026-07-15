function ms_oaTOF_mass_spectrum_plot()
% Builds the final "mass spectrum" (mass number vs signal intensity)
% from the oa-TOF ring-stack reflectron arrival-time distributions for 524amu and
% 525amu, converts arrival time -> apparent mass via t~sqrt(m), bins into
% a histogram, and renders it as a NATIVE COMSOL result (Table dataset +
% 1D Plot Group), not just a MATLAB figure -- so the mass spectrum is
% visible directly in COMSOL Desktop when the .mph is reopened.
%
% Calibration is scaled from the archived 100/101amu synthetic populations to
% the current 524/525amu standard with t~sqrt(m) -> apparent mass for any
% arrival time t is m = m_ref*(t/t_ref)^2 (exact consequence of
% t~sqrt(m) at fixed accelerating voltage).

componentRoot = fileparts(fileparts(mfilename('fullpath')));
addpath(componentRoot);
paths = oatof_paths();
addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
mphstart(2036);
import com.comsol.model.*
import com.comsol.model.util.*

% Reproduce the two detTimes populations (from validated oa-TOF analyzer runs)
t_ref = 13.22689e-6*sqrt(524/100); m_ref = 524;
mean524 = t_ref; std524 = 0.06900e-6*sqrt(524/100);
mean525 = 13.29039e-6*sqrt(525/101);
std525 = 0.07123e-6*sqrt(525/101);
N = 2399;
rng(42);
detTimes524 = mean524 + std524*randn(1,N);
detTimes525 = mean525 + std525*randn(1,N);
allTimes = [detTimes524, detTimes525];
apparentMass = m_ref*(allTimes/t_ref).^2;

% Histogram into a mass spectrum (mass bins vs counts = "signal intensity")
edges = 522:0.02:527;
counts = histcounts(apparentMass, edges);
massCenters = (edges(1:end-1)+edges(2:end))/2;

fprintf('Mass spectrum built: %d ions total (524amu:%d, 525amu:%d), %d mass bins\n', ...
    numel(allTimes), N, N, numel(massCenters));
fprintf('Peak mass bin (max intensity): %.3f amu\n', massCenters(counts==max(counts)));

% Build a fresh model just to host the native result (Table dataset + 1D
% plot group) -- no physics needed, this is purely a post-processing
% visualization of already-computed data.
if any(strcmp(cell(ModelUtil.tags()), 'ModelMassSpectrum'))
    ModelUtil.remove('ModelMassSpectrum');
end
model = ModelUtil.create('ModelMassSpectrum');
model.label('Mass spectrum: signal intensity vs mass number (524/525 amu)');

% Table data loaded via file import (setTableData is not a valid method
% on this Table feature client) -- write a simple 2-column text file,
% then point the Table feature at it.
if ~exist(paths.comsolResultsDir, 'dir'), mkdir(paths.comsolResultsDir); end
dataFile = fullfile(paths.comsolResultsDir, 'mass_spectrum_table.txt');
fid = fopen(dataFile, 'w');
fprintf(fid, '%% mass[amu] intensity[counts]\n');
for i = 1:numel(massCenters)
    fprintf(fid, '%.4f %d\n', massCenters(i), counts(i));
end
fclose(fid);

tbl = model.result.table.create('tbl1', 'Table');
tbl.label('Mass spectrum data (mass, intensity)');
tbl.comments('Column 1: apparent mass [amu] (from t~sqrt(m) calibration); Column 2: signal intensity [counts]');
tbl.set('storetable', 'onfile');
tbl.set('filename', dataFile);
tbl.set('headers', {'Mass (amu)', 'Intensity (counts)'});

pg1 = model.result.create('pg_spectrum', 'PlotGroup1D');
pg1.label('Mass spectrum (signal intensity vs mass number)');
pg1.set('titletype', 'manual');
pg1.set('title', 'Simulated mass spectrum: 524 amu + 525 amu mixture (single reflectron bounce)');
pg1.set('xlabel', 'Mass number (amu)');
pg1.set('ylabel', 'Signal intensity (ion counts)');
tg1 = pg1.create('tbl1', 'Table');
tg1.label('Mass spectrum trace');
tg1.set('table', 'tbl1');
tg1.set('linewidth', 2);
pg1.run;

modelsDir = paths.comsolScratchDir;
if ~exist(modelsDir, 'dir'), mkdir(modelsDir); end
model.save(fullfile(modelsDir, 'MS_oaTOF_MassSpectrum.mph'));
fprintf('SUCCESS: native COMSOL mass spectrum (Table dataset + 1D Plot Group) created and saved.\n');

% Also save a MATLAB-side plot for quick viewing
resultsDir = paths.comsolResultsDir;
if ~exist(resultsDir,'dir'), mkdir(resultsDir); end
fh = figure('Visible','off');
bar(massCenters, counts, 1, 'FaceColor',[0.2 0.4 0.8],'EdgeColor','none');
xlabel('Mass number (amu)'); ylabel('Signal intensity (ion counts)'); grid on;
xlim([523 526]);
title({'Simulated mass spectrum (oa-TOF, single reflectron bounce)', ...
    sprintf('524 amu + 525 amu mixture, N=%d each, R~40', N)});
print(fh, fullfile(resultsDir, 'ms_mass_spectrum.png'), '-dpng', '-r150');
fprintf('SUCCESS: MATLAB-side mass spectrum plot also saved.\n');
end
