reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
assert(~isempty(reportPath), 'COMSOL_BOOTSTRAP_REPORT is required.');

matlabDirectory = fileparts(mfilename('fullpath'));
repoRoot = fileparts(fileparts(fileparts(fileparts(fileparts(mfilename('fullpath'))))));
addpath(matlabDirectory);
runDirectory = getenv('MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY');
assert(~isempty(runDirectory), 'The public owner must provide its run execution directory.');
resolvedContractPath = fullfile(repoRoot, 'src', 'msplatform', 'components', ...
    'transverse_helical_filament_wehnelt_electron_gun', 'config', 'resolved_model.json');
result = build_wehnelt_model(resolvedContractPath, runDirectory);
write_wehnelt_build_only_report(result, reportPath);
