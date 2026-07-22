function tags = create_multipole_round_rods(geom, rodArray, tagPrefix, axisName, translationMm)
%CREATE_MULTIPOLE_ROUND_RODS Build a solver-neutral round-rod array in COMSOL.
if nargin < 3 || isempty(tagPrefix), tagPrefix = 'rod'; end
if nargin < 4 || isempty(axisName), axisName = 'z'; end
if nargin < 5, translationMm = [0 0 0]; end
assert(any(strcmp(axisName,{'x','z'})) && numel(translationMm)==3, ...
    'multipole:RodAxis','Rod axis must be x or z and translation must have three values.');
rods=rodArray.rods;tags=cell(1,numel(rods));
for index=1:numel(rods)
    rod=rods(index);tags{index}=sprintf('%s%d',tagPrefix,index);
    geom.feature.create(tags{index},'Cylinder');
    geom.feature(tags{index}).set('r',sprintf('%.17g[mm]',rod.radius_mm));
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
