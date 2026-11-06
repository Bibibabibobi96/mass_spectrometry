function result = export_corridor_scalar_field(model, geometry, authority, grid, outputDirectory)
%EXPORT_CORRIDOR_SCALAR_FIELD Export native FEM scalar V with strict conductor fill.
% Normalizes the successful 003000 export; mphinterp recover=off, ext=0.
% PA writing uses the frozen official SIMION simion_pa_save example on the path.
arguments
    model
    geometry (1,1) struct
    authority (1,1) struct
    grid (1,1) struct
    outputDirectory (1,1) string
end
dataset = model.result.dataset(char(grid.dataset_tag));
assert(strcmp(char(dataset.getType()),'Solution') && ...
    strcmp(char(dataset.getString('solution')),char(grid.solution_tag)), ...
    'MRTOF:Dataset','Export requires the declared candidate solution dataset.');
voltages = double(authority.analyzer_electrode_voltages_v(:));
components = authority.component_voltages_v;
vacuum = mphgetselection(model.component('comp1').physics('es').selection);
assert(~isempty(vacuum.entities),'MRTOF:Vacuum','Empty electrostatic vacuum selection.');
dimensions = double(grid.dimensions(:).');
pitch = double(grid.pitch_mm(:));
origin = double(grid.origin_mm(:));
pointCount = prod(dimensions);
assert(numel(pitch)==3 && all(isfinite(pitch) & pitch>0) && ...
    pointCount==grid.point_count && all(dimensions>=2) && ...
    all(abs(origin.'+(dimensions-1).*pitch.'-grid.maximum_mm(:).')<1e-10), ...
    'MRTOF:ExportGrid','Scalar export grid is inconsistent.');
potential = zeros(pointCount,1);
valid = false(pointCount,1);
finiteFEM = 0;
filledConductor = 0;
queryTimer = tic;
for first = 1:grid.block_points:pointCount
    last = min(pointCount,first+grid.block_points-1);
    index = first:last;
    [ix,iy,iz] = ind2sub(dimensions,index);
    coordinates = origin+pitch.*[ix-1;iy-1;iz-1];
    queryCoordinates = coordinates;
    queryCoordinates(1,:) = abs(queryCoordinates(1,:));
    values = double(mphinterp(model,'V','coord',queryCoordinates, ...
        'dataset',char(grid.dataset_tag),'ext',0,'coorderr','off', ...
        'selection',vacuum.entities,'recover','off','unit','V'));
    values = values(:).';
    finite = isfinite(values);
    finiteFEM = finiteFEM+nnz(finite);
    missing = find(~finite);
    if ~isempty(missing)
        conductorVoltage = classify_corridor_conductor_voltage(coordinates(:,missing).', ...
            geometry,voltages,authority.assembly,components);
        known = isfinite(conductorVoltage);
        values(missing(known)) = conductorVoltage(known).';
        finite(missing(known)) = true;
        filledConductor = filledConductor+nnz(known);
    end
    values(~finite) = 0; % Storage only: field adapter must consume the valid mask.
    potential(index) = values;
    valid(index) = finite;
    fprintf('SCALAR_EXPORT_BLOCK %d/%d elapsed=%.3f\n',last,pointCount,toc(queryTimer));
end
querySeconds = toc(queryTimer);
writeTimer = tic;
simion_pa_save(fullfile(outputDirectory,'field_v.pa'),reshape(potential,dimensions), ...
    '3dplanar','electric_',0,pitch(1),pitch(2),pitch(3));
clear potential
simion_pa_save(fullfile(outputDirectory,'field_valid.pa'),reshape(double(valid),dimensions), ...
    '3dplanar','electric_',0,pitch(1),pitch(2),pitch(3));
result = struct('status','success','field_qualification',false,'points',pointCount, ...
    'fem_valid',finiteFEM,'strict_conductor_filled',filledConductor, ...
    'remaining_invalid',pointCount-nnz(valid),'dimensions',dimensions, ...
    'origin_mm',origin.','pitch_mm',pitch.','field_units','V', ...
    'dataset_tag',char(grid.dataset_tag),'solution_tag',char(grid.solution_tag), ...
    'query_seconds',querySeconds,'write_seconds',toc(writeTimer), ...
    'x_mapping','V(x,y,z)=V(abs(x),y,z) from native half-domain FEM', ...
    'invalid_policy','Unknown vacuum points remain invalid; no zero-field fallback.', ...
    'field_scope','Same frozen C0 geometry, candidate P/S voltages; no convergence or flight qualification.');
end
