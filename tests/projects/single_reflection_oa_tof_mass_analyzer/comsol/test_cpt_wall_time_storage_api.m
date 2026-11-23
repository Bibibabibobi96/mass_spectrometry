% Probe the COMSOL 6.4 Charged Particle Tracing properties behind the
% GUI-visible wall-interaction time-storage controls.

reportPath = getenv('COMSOL_BOOTSTRAP_REPORT');
fid = fopen(reportPath, 'w');
assert(fid >= 0, 'Could not open report: %s', reportPath);
cleanup = onCleanup(@() fclose(fid));

import com.comsol.model.*
import com.comsol.model.util.*
model = ModelUtil.create('CptWallTimeStorageApiProbe');
model.component.create('comp1', true);
model.component('comp1').geom.create('geom1', 3);
model.component('comp1').physics.create( ...
    'cpt', 'ChargedParticleTracing', 'geom1');
cpt = model.component('comp1').physics('cpt');

% Long-term API regression for the two GUI Physics Properties checkboxes
% used by the formal oa-TOF storage policy.
assert(~cpt.prop('StoreExtra').getBoolean('StoreExtra'), ...
    'COMSOL default Store extra wall times unexpectedly changed.');
assert(~cpt.prop('StoreParticleStatusData').getBoolean( ...
    'StoreParticleStatusData'), ...
    'COMSOL default particle-status storage unexpectedly changed.');
cpt.prop('StoreExtra').set('StoreExtra', true);
cpt.prop('StoreParticleStatusData').set('StoreParticleStatusData', true);
assert(cpt.prop('StoreExtra').getBoolean('StoreExtra'), ...
    'StoreExtra GUI property did not persist true.');
assert(cpt.prop('StoreParticleStatusData').getBoolean( ...
    'StoreParticleStatusData'), ...
    'StoreParticleStatusData GUI property did not persist true.');
cpt.prop('StoreExtra').set('StoreExtra', false);
cpt.prop('StoreParticleStatusData').set('StoreParticleStatusData', false);
fprintf(fid, 'STORE_EXTRA_READBACK=%d\n', ...
    cpt.prop('StoreExtra').getBoolean('StoreExtra'));
fprintf(fid, 'STORE_PARTICLE_STATUS_READBACK=%d\n', ...
    cpt.prop('StoreParticleStatusData').getBoolean( ...
    'StoreParticleStatusData'));

propertyTags = string(cell(cpt.prop.tags()));
fprintf(fid, 'PHYSICS_PROPERTY_TAGS=%s\n', join(propertyTags, ','));
for tagIndex = 1:numel(propertyTags)
    tag = propertyTags(tagIndex);
    physicsProperty = cpt.prop(char(tag));
    [values, allowed] = mphgetproperties(physicsProperty);
    names = string(fieldnames(values));
    fprintf(fid, 'PROPERTY_GROUP_%s_FIELDS=%s\n', tag, join(names, ','));
    for nameIndex = 1:numel(names)
        name = names(nameIndex);
        value = string(values.(char(name)));
        value = value(~ismissing(value));
        fprintf(fid, 'PROPERTY_%s_%s=%s\n', tag, name, join(value(:), ','));
        if isfield(allowed, char(name))
            allowedValue = string(allowed.(char(name)));
            allowedValue = allowedValue(~ismissing(allowedValue));
            fprintf(fid, 'ALLOWED_%s_%s=%s\n', ...
                tag, name, join(allowedValue(:), ','));
        end
    end
end

fprintf(fid, 'STATUS=PASS\n');
clear cleanup
ModelUtil.remove('CptWallTimeStorageApiProbe');
