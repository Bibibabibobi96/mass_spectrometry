reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));

import com.comsol.model.*
import com.comsol.model.util.*
model = ModelUtil.create('VectorizedReleaseApiProbe');
model.component.create('comp1', true);
model.component('comp1').geom.create('geom1', 3);
model.component('comp1').physics.create( ...
    'cpt', 'ChargedParticleTracing', 'geom1');
cpt = model.component('comp1').physics('cpt');
aux = cpt.feature.create('auxphase', 'AuxiliaryField', -1);
aux.set('fieldVariableName', 'particle_phase');
aux.set('R', '0');

release = cpt.feature.create( ...
    'relfile1', 'ReleaseFromDataFile', -1);
properties = cell(release.properties());
fprintf(fid, 'AUXILIARY_TYPE=%s\n', char(aux.getType()));
fprintf(fid, 'AUXILIARY_PROPERTIES=%s\n', ...
    strjoin(cell(aux.properties()), ','));
fprintf(fid, 'RELEASE_PROPERTIES=%s\n', strjoin(properties, ','));
for index = 1:numel(properties)
    property = properties{index};
    if contains(lower(property), 'aux') || ...
            contains(lower(property), 'phase') || ...
            contains(lower(property), 'icol')
        try
            value = char(release.getString(property));
        catch
            value = '<non-string>';
        end
        try
            allowed = cell(release.getAllowedPropertyValues(property));
            allowedText = strjoin(allowed, '|');
        catch
            allowedText = '<unavailable>';
        end
        fprintf(fid, 'PROPERTY=%s VALUE=%s ALLOWED=%s\n', ...
            property, value, allowedText);
    end
end
forceTypes = {'Force', 'UserDefinedForce'};
for index = 1:numel(forceTypes)
    forceType = forceTypes{index};
    forceTag = sprintf('forceprobe%d', index);
    try
        force = cpt.feature.create(forceTag, forceType, 3);
        forceProperties = cell(force.properties());
        fprintf(fid, 'FORCE_TYPE=%s STATUS=AVAILABLE PROPERTIES=%s\n', ...
            forceType, strjoin(forceProperties, ','));
        for propertyIndex = 1:numel(forceProperties)
            property = forceProperties{propertyIndex};
            try
                value = char(force.getString(property));
            catch
                value = '<non-string>';
            end
            try
                allowed = cell(force.getAllowedPropertyValues(property));
                allowedText = strjoin(allowed, '|');
            catch
                allowedText = '<unavailable>';
            end
            fprintf(fid, ...
                'FORCE_PROPERTY=%s VALUE=%s ALLOWED=%s\n', ...
                property, value, allowedText);
        end
        cpt.feature.remove(forceTag);
    catch exception
        fprintf(fid, 'FORCE_TYPE=%s STATUS=UNAVAILABLE ERROR=%s\n', ...
            forceType, replace(exception.message, newline, ' | '));
    end
end
fprintf(fid, 'STATUS=PASS\n');

clear cleanup
ModelUtil.remove('VectorizedReleaseApiProbe');
