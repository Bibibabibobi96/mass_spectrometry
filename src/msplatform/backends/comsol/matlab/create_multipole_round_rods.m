function tags = create_multipole_round_rods(geom, rodArray, tagPrefix, axisName, translationMm)
%CREATE_MULTIPOLE_ROUND_RODS Build round-default or elliptical rods in COMSOL.
% The historical function name is retained for API compatibility.  Rods with
% radius_mm use the byte-for-byte legacy Cylinder branch.  Explicit ellipse
% rods use an ECone with ratio one, which is an elliptic cylinder.
if nargin < 3 || isempty(tagPrefix), tagPrefix = 'rod'; end
if nargin < 4 || isempty(axisName), axisName = 'z'; end
if nargin < 5, translationMm = [0 0 0]; end
assert(any(strcmp(axisName,{'x','z'})) && numel(translationMm)==3, ...
    'multipole:RodAxis','Rod axis must be x or z and translation must have three values.');
rods=rodArray.rods;tags=cell(1,numel(rods));
for index=1:numel(rods)
    rod=rods(index);tags{index}=sprintf('%s%d',tagPrefix,index);
    isRound=isfield(rod,'radius_mm');
    isEllipse=isfield(rod,'semi_major_axis_mm') && isfield(rod,'semi_minor_axis_mm') && ...
        isfield(rod,'major_axis_angle_rad');
    assert(xor(isRound,isEllipse),'multipole:RodCrossSection', ...
        'Each rod must declare exactly one round or ellipse cross section.');
    if isRound
        geom.feature.create(tags{index},'Cylinder');
        geom.feature(tags{index}).set('r',sprintf('%.17g[mm]',rod.radius_mm));
    else
        assert(isfinite(rod.semi_major_axis_mm) && isfinite(rod.semi_minor_axis_mm) && ...
            rod.semi_major_axis_mm>=rod.semi_minor_axis_mm && rod.semi_minor_axis_mm>0 && ...
            isfinite(rod.major_axis_angle_rad),'multipole:RodCrossSection', ...
            'Ellipse semi-axes and orientation must be finite and positive.');
        geom.feature.create(tags{index},'ECone');
        geom.feature(tags{index}).set('semiaxes',{sprintf('%.17g[mm]',rod.semi_major_axis_mm), ...
            sprintf('%.17g[mm]',rod.semi_minor_axis_mm)});
        geom.feature(tags{index}).set('rat','1');
        geom.feature(tags{index}).set('rot',sprintf('%.17g[rad]',rod.major_axis_angle_rad));
    end
    geom.feature(tags{index}).set('h',sprintf('%.17g[mm]',rod.z_max_mm-rod.z_min_mm));
    if strcmp(axisName,'z')
        position=[rod.center_x_mm,rod.center_y_mm,rod.z_min_mm]+translationMm;
    else
        geom.feature(tags{index}).set('axis',{'1','0','0'});
        position=[rod.z_min_mm,rod.center_x_mm,rod.center_y_mm]+translationMm;
    end
    geom.feature(tags{index}).set('pos',arrayfun(@(v)sprintf('%.17g[mm]',v),position,'UniformOutput',false));
    geom.feature(tags{index}).set('selresult','on');
end
end
