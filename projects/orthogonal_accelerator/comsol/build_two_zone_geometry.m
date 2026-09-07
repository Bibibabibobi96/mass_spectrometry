function ringTags = build_two_zone_geometry(geom1, layout, interfacePort)
% REPOSITORY_CONTRACT: MATLAB_BUILD_ONLY
%BUILD_TWO_ZONE_GEOMETRY Build accelerator solids from explicit COMSOL expressions.
% The caller supplies model-parameter expressions in model length units.
% Acceleration is along +z; repeller_front_z is its front surface. This function
% creates no vacuum, grids, physics, meshes, solver, or output assets.
arguments
    geom1
    layout (1,1) struct
    interfacePort (1,1) struct
end
required = {'x_center','y_center','repeller_front_z','electrode_half_width', ...
    'repeller_thickness','shield_inner_half_width','shield_wall','total_length', ...
    'rear_gap','grid1_z','stage2_length','ring_bore_half_width','ring_thickness', ...
    'grid1_voltage'};
for k = 1:numel(required)
    key = required{k};
    if ~isfield(layout,key) || ~(ischar(layout.(key)) || isstring(layout.(key))) || ...
            ~isscalar(string(layout.(key))) || strlength(string(layout.(key))) == 0
        error('accelerator:GeometryContract', 'layout.%s must be a nonempty expression.', key);
    end
end
if ~isfield(layout,'ring_count') || ~isnumeric(layout.ring_count) || ...
        ~isscalar(layout.ring_count) || ~isreal(layout.ring_count) || ...
        ~isfinite(layout.ring_count) || layout.ring_count < 1 || ...
        layout.ring_count ~= fix(layout.ring_count)
    error('accelerator:GeometryContract', 'layout.ring_count must be a positive integer.');
end
if ~isfield(interfacePort,'enabled') || ~islogical(interfacePort.enabled) || ~isscalar(interfacePort.enabled)
    error('accelerator:InterfacePortContract', 'interfacePort.enabled must be a logical scalar.');
end
x = char(layout.x_center); y = char(layout.y_center);
z = char(layout.repeller_front_z); half = char(layout.electrode_half_width);
inner = char(layout.shield_inner_half_width); wall = char(layout.shield_wall);
thickness = char(layout.repeller_thickness);
total = char(layout.total_length); rear = char(layout.rear_gap);
outerHalf = ['(' inner ')+(' wall ')'];
back = ['(' z ')-(' thickness ')-(' rear ')'];
depth = ['(' total ')+(' thickness ')+(' rear ')'];
add_block(geom1,'repeller','Repeller (solid rectangular electrode)', ...
    {['2*(' half ')'],['2*(' half ')'],thickness}, ...
    {[x '-(' half ')'],[y '-(' half ')'],[z '-(' thickness ')']});
add_block(geom1,'accelshieldO','Accelerator shield outer solid with integrated rear cap', ...
    {['2*(' outerHalf ')'],['2*(' outerHalf ')'],[depth '+(' wall ')']}, ...
    {[x '-(' outerHalf ')'],[y '-(' outerHalf ')'],[back '-(' wall ')']});
add_block(geom1,'accelshieldH','Accelerator shield cavity', ...
    {['2*(' inner ')'],['2*(' inner ')'],depth}, ...
    {[x '-(' inner ')'],[y '-(' inner ')'],back});
cuts = {'accelshieldH'};
if interfacePort.enabled
    keys = {'full_width_y_mm','full_height_z_mm','center_z_mm'};
    for k = 1:numel(keys)
        key = keys{k};
        if ~isfield(interfacePort,key) || ~isnumeric(interfacePort.(key)) || ...
                ~isscalar(interfacePort.(key)) || ~isreal(interfacePort.(key)) || ...
                ~isfinite(interfacePort.(key))
            error('accelerator:InterfacePortContract','interfacePort.%s must be a finite scalar.',key);
        end
    end
    if interfacePort.full_width_y_mm <= 0 || interfacePort.full_height_z_mm <= 0 || ...
            ~isfield(layout,'boolean_cut_padding_mm') || ...
            ~isnumeric(layout.boolean_cut_padding_mm) || ~isscalar(layout.boolean_cut_padding_mm) || ...
            ~isreal(layout.boolean_cut_padding_mm) || ~isfinite(layout.boolean_cut_padding_mm) || ...
            layout.boolean_cut_padding_mm <= 0
        error('accelerator:InterfacePortContract','Port widths and Boolean padding must be positive.');
    end
    padding = layout.boolean_cut_padding_mm;
    add_block(geom1,'accelshieldPort','Accelerator negative-x side-port cut', ...
        {[wall '+' mm(2*padding)],mm(interfacePort.full_width_y_mm),mm(interfacePort.full_height_z_mm)}, ...
        {[x '-(' outerHalf ')-' mm(padding)], ...
        [y '-' mm(interfacePort.full_width_y_mm/2)], ...
        mm(interfacePort.center_z_mm-interfacePort.full_height_z_mm/2)});
    cuts{end+1} = 'accelshieldPort';
end
geom1.feature.create('accelshield','Difference');
geom1.feature('accelshield').label('Grounded accelerator enclosure');
geom1.feature('accelshield').selection('input').set({'accelshieldO'});
geom1.feature('accelshield').selection('input2').set(cuts);
ringTags = cell(1,layout.ring_count);
for k = 1:layout.ring_count
    tag = sprintf('accelring_%d',k);
    center = sprintf('(%s)+%d*(%s)/%d',layout.grid1_z,k,layout.stage2_length,layout.ring_count+1);
    ringT = char(layout.ring_thickness); bore = char(layout.ring_bore_half_width);
    add_block(geom1,[tag 'O'],sprintf('Accelerator ring %d outer solid',k), ...
        {['2*(' half ')'],['2*(' half ')'],ringT}, ...
        {[x '-(' half ')'],[y '-(' half ')'],[center '-(' ringT ')/2']});
    add_block(geom1,[tag 'H'],sprintf('Accelerator ring %d bore',k), ...
        {['2*(' bore ')'],['2*(' bore ')'],ringT}, ...
        {[x '-(' bore ')'],[y '-(' bore ')'],[center '-(' ringT ')/2']});
    geom1.feature.create(tag,'Difference');
    geom1.feature(tag).label(sprintf('Accelerator ring %d (V=%s*(1-%d/%d))', ...
        k,layout.grid1_voltage,k,layout.ring_count+1));
    geom1.feature(tag).selection('input').set({[tag 'O']});
    geom1.feature(tag).selection('input2').set({[tag 'H']});
    ringTags{k} = tag;
end
end

function add_block(geom,tag,label,sizeExpressions,positionExpressions)
geom.feature.create(tag,'Block');
geom.feature(tag).label(label);
geom.feature(tag).set('size',sizeExpressions);
geom.feature(tag).set('pos',positionExpressions);
end

function value = mm(number)
value = sprintf('%.17g[mm]',number);
end
