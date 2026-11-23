reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
assert(~isempty(reportPath), 'COMSOL_BOOTSTRAP_REPORT is required.');

matlabDirectory = fileparts(mfilename('fullpath'));
addpath(matlabDirectory);
runDirectory = getenv('MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY');
assert(~isempty(runDirectory), 'The public owner must provide its run execution directory.');
resolvedContractPath = getenv('MASS_SPECTROMETRY_WEHNELT_RESOLVED_CONTRACT');
assert(~isempty(resolvedContractPath), 'The public owner must provide its verified frozen resolved contract.');
result = build_wehnelt_model(resolvedContractPath, runDirectory);
write_wehnelt_build_only_report(result, reportPath);
