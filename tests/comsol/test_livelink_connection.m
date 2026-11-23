reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
assert(~isempty(reportPath), 'COMSOL_BOOTSTRAP_REPORT is required.');

import com.comsol.model.util.*
version = char(ModelUtil.getComsolVersion);
tags = cell(ModelUtil.tags());

fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Cannot create LiveLink smoke report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, 'TASK=SHARED_LIVELINK_CONNECTION_SMOKE\n');
fprintf(fid, 'COMSOL_VERSION=%s\n', version);
fprintf(fid, 'OPEN_MODEL_COUNT=%d\n', numel(tags));
fprintf(fid, 'MODEL_CREATED=false\n');
fprintf(fid, 'SOLVER_RUN=false\n');
fprintf(fid, 'STATUS=PASS\n');
