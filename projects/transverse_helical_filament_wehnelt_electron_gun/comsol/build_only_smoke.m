reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
assert(~isempty(reportPath), 'COMSOL_BOOTSTRAP_REPORT is required.');

projectRoot = fileparts(fileparts(mfilename('fullpath')));
repoRoot = fileparts(fileparts(projectRoot));
addpath(fullfile(repoRoot, 'src', 'msplatform', 'backends', 'comsol', 'matlab'));
runDirectory = getenv('MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY');
assert(~isempty(runDirectory), 'The public owner must provide its run execution directory.');
resolvedContractPath = fullfile(projectRoot, 'config', 'resolved_model.json');
result = build_wehnelt_model(resolvedContractPath, runDirectory);
write_wehnelt_build_only_report(result, reportPath);
