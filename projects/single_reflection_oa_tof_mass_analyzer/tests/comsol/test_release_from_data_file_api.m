reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));

import com.comsol.model.*
import com.comsol.model.util.*
model = ModelUtil.create('ReleaseFromDataFileApiProbe');
model.component.create('comp1', true);
model.component('comp1').geom.create('geom1', 3);
model.component('comp1').physics.create('cpt', 'ChargedParticleTracing', 'geom1');
cpt = model.component('comp1').physics('cpt');

% Probe candidate feature identifiers.  COMSOL's documented Desktop label
% need not equal its API identifier.
rel = cpt.feature.create('relfile1', 'ReleaseFromDataFile', -1);
fprintf(fid, 'FEATURE_TYPE=%s\n', char(rel.getType()));
fprintf(fid, 'FEATURE_DIMENSION=-1\n');
properties = cell(rel.properties());
fprintf(fid, 'PROPERTIES=%s\n', strjoin(properties, ','));
dataPath = fullfile(tempdir, 'release_from_data_file_api_probe.txt');
writematrix([0 0 0 1 0 0], dataPath, 'Delimiter', 'tab');
rel.set('Filename', dataPath);
rel.set('icolp', '0');
rel.set('VelocitySpecification', 'SpecifyVelocity');
rel.set('InitialVelocity', 'FromFile');
rel.set('icolv', '3');
rel.importData();
fprintf(fid, 'FILE_BINDING=PASS\n');
fprintf(fid, 'STATUS=PASS\n');
clear cleanup
ModelUtil.remove('ReleaseFromDataFileApiProbe');
