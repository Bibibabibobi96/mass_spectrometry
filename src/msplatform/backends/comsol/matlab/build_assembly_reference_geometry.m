function result = build_assembly_reference_geometry(geom, projection)
% REPOSITORY_CONTRACT: MATLAB_BUILD_ONLY
%BUILD_ASSEMBLY_REFERENCE_GEOMETRY Emit exact, explicit Assembly geometry.
% Build-only candidate. Caller owns boundary physics and solve.
% The input has already passed project_assembly_geometry. No implicit domain.
arguments
    geom
    projection (1,1) struct
end
assert(strcmp(projection.role,'comsol_canonical_assembly_geometry_projection') && ...
    projection.schema_version==1, 'assembly:Projection','Explicit geometry projection required');
geom.lengthUnit('mm');
members=projection.members;
if isstruct(members), members=num2cell(members); end
solidTags=cell(1,numel(members)); sheetTags=cell(1,numel(members));
memberTags=cell(1,numel(members)); solidCount=0; sheetCount=0;
counter=0;
for k=1:numel(members)
    member=members{k}; pose=member.transform;
    R=double(pose.rotation); T=double(pose.translation_mm(:));
    if strcmp(member.representation_role,'ideal_surface')
        tag=emitSheet(member.shape,R,T);
        sheetCount=sheetCount+1; sheetTags{sheetCount}=tag;
    else
        tag=emitShape(member.shape,R,T);
        solidCount=solidCount+1; solidTags{solidCount}=tag;
    end
    geom.feature(tag).set('selresult','on');
    memberTags{k}=struct('instance_id',member.instance_id,'member_id',member.member_id, ...
        'electrode_group_id',member.electrode_group_id,'feature_tag',tag, ...
        'representation_role',member.representation_role);
end
solidTags=solidTags(1:solidCount); sheetTags=sheetTags(1:sheetCount);
assert(~isempty(solidTags),'assembly:Empty','No solid members');
outer=projection.outer_box_mm; lo=double(outer.min(:)); hi=double(outer.max(:));
geom.feature.create('assembly_outer','Block');
geom.feature('assembly_outer').set('pos',lo');
geom.feature('assembly_outer').set('size',(hi-lo)');
geom.feature('assembly_outer').set('selresult','on');
geom.feature('assembly_outer').set('selresultshow','bnd');
geom.feature.create('assembly_vac','Difference');
geom.feature('assembly_vac').selection('input').set({'assembly_outer'});
geom.feature('assembly_vac').selection('input2').set(solidTags);
geom.feature('assembly_vac').set('keepsubtract','on');
geom.feature('assembly_vac').set('propagatesel','on');
geom.feature('assembly_vac').set('selresult','on');
geom.feature.create('assembly_vac_sheets','Union');
geom.feature('assembly_vac_sheets').selection('input').set([{'assembly_vac'},sheetTags]);
geom.feature('assembly_vac_sheets').set('intbnd','on');
geom.feature('assembly_vac_sheets').set('propagatesel','on');
% Caller must execute geom.run and verify nonempty, disjoint, exhaustive group
% selections after COMSOL finalization. No field or boundary is invented here.
result=struct('members',{memberTags},'vacuum_feature','assembly_vac', ...
    'vacuum_with_sheets_feature','assembly_vac_sheets', ...
    'outer_box_mm',projection.outer_box_mm);

    function tag=nextTag()
        counter=counter+1; tag=sprintf('am%04d',counter);
    end
    function tag=emitShape(shape,R,T)
        kind=char(shape.kind);
        if strcmp(kind,'union') || strcmp(kind,'difference')
            if strcmp(kind,'union')
                parts=shape.parts; if isstruct(parts),parts=num2cell(parts);end
                tags=cell(1,numel(parts));
                for j=1:numel(parts),tags{j}=emitShape(parts{j},R,T);end
                tag=nextTag();geom.feature.create(tag,'Union');
                geom.feature(tag).selection('input').set(tags);
            else
                first=emitShape(shape.base,R,T);tools=shape.tools;
                if isstruct(tools),tools=num2cell(tools);end
                tags=cell(1,numel(tools));
                for j=1:numel(tools),tags{j}=emitShape(tools{j},R,T);end
                tag=nextTag();geom.feature.create(tag,'Difference');
                geom.feature(tag).selection('input').set({first});
                geom.feature(tag).selection('input2').set(tags);
            end
            return
        end
        if strcmp(kind,'box')
            c=R*double(shape.center_mm(:))+T; sizeWorld=abs(R)*double(shape.size_mm(:));
            tag=nextTag();geom.feature.create(tag,'Block');
            geom.feature(tag).set('pos',(c-sizeWorld/2)');geom.feature(tag).set('size',sizeWorld');
        elseif strcmp(kind,'cylinder')
            center=double(shape.center_mm(:));radius=double(shape.radius_mm);height=double(shape.height_mm);
            tag=emitCylinder(center-[0;0;height/2],radius,height,R,T);
        elseif strcmp(kind,'rod')
            center=double(shape.center_xy_mm(:));z0=double(shape.z_min_mm);z1=double(shape.z_max_mm);
            tag=emitCylinder([center;z0],double(shape.radius_mm),z1-z0,R,T);
        elseif strcmp(kind,'annulus')
            center=double(shape.center_xy_mm(:));z0=double(shape.z_min_mm);z1=double(shape.z_max_mm);
            outside=emitCylinder([center;z0],double(shape.outer_radius_mm),z1-z0,R,T);
            if shape.inner_radius_mm==0, tag=outside; return; end
            inside=emitCylinder([center;z0],double(shape.inner_radius_mm),z1-z0,R,T);
            tag=nextTag();geom.feature.create(tag,'Difference');
            geom.feature(tag).selection('input').set({outside});geom.feature(tag).selection('input2').set({inside});
        else
            error('assembly:Shape','Unsupported physical shape');
        end
    end
    function tag=emitCylinder(base,radius,height,R,T)
        assert(height>0 && radius>0,'assembly:Cylinder','Positive cylinder dimensions required');
        pos=R*base+T;axis=R*[0;0;1];tag=nextTag();
        geom.feature.create(tag,'Cylinder');geom.feature(tag).set('r',radius);
        geom.feature(tag).set('h',height);geom.feature(tag).set('axistype','cartesian');
        geom.feature(tag).set('axis',axis');geom.feature(tag).set('pos',pos');
    end
    function tag=emitSheet(shape,R,T)
        kind=char(shape.kind); tag=nextTag();
        geom.feature.create(tag,'WorkPlane');geom.feature(tag).set('quickplane','xy');
        if strcmp(kind,'box')
            c=R*double(shape.center_mm(:))+T;sz=abs(R)*double(shape.size_mm(:));
            geom.feature(tag).set('quickz',c(3));w=geom.feature(tag).geom;
            w.feature.create('s','Rectangle');w.feature('s').set('size',sz(1:2)');
            w.feature('s').set('pos',(c(1:2)-sz(1:2)/2)');
        elseif strcmp(kind,'annulus') && shape.inner_radius_mm==0
            c=R*[double(shape.center_xy_mm(:));double(shape.z_min_mm)]+T;
            geom.feature(tag).set('quickz',c(3));w=geom.feature(tag).geom;
            w.feature.create('s','Circle');w.feature('s').set('r',double(shape.outer_radius_mm));
            w.feature('s').set('pos',c(1:2)');
        else
            error('assembly:Sheet','Unsupported ideal surface');
        end
    end
end
