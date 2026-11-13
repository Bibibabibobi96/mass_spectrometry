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
nativeShapes={};
if isfield(projection,'native_shapes')
    nativeShapes=projection.native_shapes;
    if isstruct(nativeShapes), nativeShapes=num2cell(nativeShapes); end
    assert(numel(nativeShapes)==numel(members),'assembly:Projection','Native shape coverage differs');
end
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
        shape=member.shape; if ~isempty(nativeShapes), shape=nativeShapes{k}; end
        tag=emitShape(shape,R,T);
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
        if strcmp(kind,'ip_box')
            low=double(shape.min_mm(:)); high=double(shape.max_mm(:));
            c=R*((low+high)/2)+T; sizeWorld=abs(R)*(high-low);
            assert(all(sizeWorld>0),'assembly:IPBox','Positive IP solid dimensions required');
            tag=nextTag();geom.feature.create(tag,'Block');
            geom.feature(tag).set('pos',(c-sizeWorld/2)');geom.feature(tag).set('size',sizeWorld');
        elseif strcmp(kind,'ip_cylinder_x')
            base=[double(shape.x_min_mm);double(shape.center_y_mm);double(shape.center_z_mm)];
            height=double(shape.x_max_mm)-double(shape.x_min_mm);radius=double(shape.radius_mm);
            assert(height>0 && radius>0,'assembly:IPCylinder','Positive cylinder dimensions required');
            tag=nextTag();geom.feature.create(tag,'Cylinder');geom.feature(tag).set('r',radius);
            geom.feature(tag).set('h',height);geom.feature(tag).set('axistype','cartesian');
            geom.feature(tag).set('axis',(R*[1;0;0])');geom.feature(tag).set('pos',(R*base+T)');
        elseif strcmp(kind,'ip_certified_tetra_union')
            tetra=shape.tetrahedra;
            if iscell(tetra), count=numel(tetra); else, count=size(tetra,1); end
            tags=cell(1,count);
            for j=1:count
                if iscell(tetra), vertices=double(tetra{j});
                else, vertices=squeeze(double(tetra(j,:,:))); end
                assert(isequal(size(vertices),[4,3]),'assembly:IPTetra','Four source vertices required');
                tags{j}=nextTag();geom.feature.create(tags{j},'Tetrahedron');
                geom.feature(tags{j}).set('type','solid');
                geom.feature(tags{j}).set('p',R*vertices'+T);
            end
            if count==1, tag=tags{1};
            else
                tag=nextTag();geom.feature.create(tag,'Union');
                geom.feature(tag).selection('input').set(tags);
            end
        elseif strcmp(kind,'ip_certified_prism')
            assert(shape.reconstruction_residual_mm<=shape.arithmetic_bound_mm, ...
                'assembly:IPPrism','Certified reconstruction residual exceeds its arithmetic bound');
            wp=nextTag();geom.feature.create(wp,'WorkPlane');
            plane=char(shape.plane);geom.feature(wp).set('quickplane',plane);
            if strcmp(plane,'yz'), prop='quickx';
            elseif strcmp(plane,'zx'), prop='quicky';
            elseif strcmp(plane,'xy'), prop='quickz';
            else, error('assembly:IPPrism','Unsupported certified plane'); end
            geom.feature(wp).set(prop,double(shape.offset_mm));
            w=geom.feature(wp).geom;w.feature.create('section','Polygon');
            w.feature('section').set('source','table');w.feature('section').set('type','solid');
            w.feature('section').set('table',double(shape.polygon_mm));
            geom.run(wp);
            tag=nextTag();geom.feature.create(tag,'Extrude');
            geom.feature(tag).set('workplane',wp);
            geom.feature(tag).selection('input').set({wp});
            geom.feature(tag).set('distance',double(shape.distance_mm));
            geom.feature(tag).set('displ',reshape(double(shape.displacement_mm),1,2));
        elseif strcmp(kind,'box')
            c=R*double(shape.center_mm(:))+T; sizeWorld=abs(R)*double(shape.size_mm(:));
            tag=nextTag();geom.feature.create(tag,'Block');
            geom.feature(tag).set('pos',(c-sizeWorld/2)');geom.feature(tag).set('size',sizeWorld');
        elseif strcmp(kind,'cylinder')
            center=double(shape.center_mm(:));radius=double(shape.radius_mm);height=double(shape.height_mm);
            tag=emitCylinder(center-[0;0;height/2],radius,height,R,T);
        elseif strcmp(kind,'extruded_yz_polygon')
            tag=emitYZPolygon(shape,R,T);
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
    function tag=emitYZPolygon(shape,R,T)
        % The component supplies its original polygon; apply its signed pose once.
        bounds=double(shape.x(:)); vertices=double(shape.polygon_yz_mm);
        assert(numel(bounds)==2 && bounds(2)>bounds(1) && size(vertices,2)==2 && size(vertices,1)>=3, ...
            'assembly:Polygon','Finite positive extrusion and polygon required');
        axisIndex=find(abs(R(:,1))==1);assert(numel(axisIndex)==1,'assembly:Pose','Signed axis pose required');
        planeAxes={[2,3],[3,1],[1,2]};planeNames={'yz','zx','xy'};quickNames={'quickx','quicky','quickz'};
        normal0=R*[bounds(1);0;0]+T;normal1=R*[bounds(2);0;0]+T;
        lower=min(normal0(axisIndex),normal1(axisIndex));distance=abs(normal1(axisIndex)-normal0(axisIndex));
        world=R*[repmat(bounds(1),1,size(vertices,1));vertices.']+T;
        wp=nextTag();geom.feature.create(wp,'WorkPlane');geom.feature(wp).set('quickplane',planeNames{axisIndex});
        geom.feature(wp).set(quickNames{axisIndex},lower);w=geom.feature(wp).geom;
        w.feature.create('polygon','Polygon');w.feature('polygon').set('source','table');
        w.feature('polygon').set('type','solid');w.feature('polygon').set('table',world(planeAxes{axisIndex},:).');
        tag=nextTag();geom.feature.create(tag,'Extrude');geom.feature(tag).set('workplane',wp);
        geom.feature(tag).selection('input').set({wp});geom.feature(tag).set('distance',distance);
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
