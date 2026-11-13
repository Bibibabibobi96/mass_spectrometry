function selections = validate_assembly_reference_selections(comp, geometryTag, buildResult, sanityTolerance)
% REPOSITORY_CONTRACT: MATLAB_BUILD_ONLY
%VALIDATE_ASSEMBLY_REFERENCE_SELECTIONS Verify native entity selections.
% Call after geom.run, before materials, boundaries, mesh or studies. Missing,
% empty, non-vacuum or cross-electrode shared entities fail closed.
arguments
    comp
    geometryTag (1,:) char
    buildResult (1,1) struct
    sanityTolerance (1,1) struct
end
members=buildResult.members;
if isstruct(members)
    members=num2cell(members);
end
vacTag='assembly_reference_vacuum';
vac=comp.selection.create(vacTag,'Explicit');
vac.geom(geometryTag,3);
vac.set(double(comp.selection([geometryTag '_assembly_vac_dom']).entities()));
assert(~isempty(vac.entities()),'assembly:Vacuum','Reference vacuum selection is empty');
adj=comp.selection.create('assembly_reference_vacuum_faces','Adjacent');
adj.set('entitydim',3);
adj.set('outputdim',2);
adj.set('input',{vacTag});
adj.set('interior','on');
allVacuumFaces=double(adj.entities());
allVacuumFaces=allVacuumFaces(:)';
assert(~isempty(allVacuumFaces),'assembly:VacuumFaces','Reference vacuum has no boundary faces');
keys=cell(1,numel(members));
faces=cell(1,numel(members));
for k=1:numel(members)
    row=members{k};
    keys{k}=[char(row.instance_id) '/' char(row.electrode_group_id)];
    tag=char(row.feature_tag);
    if strcmp(row.representation_role,'ideal_surface')
        selected=comp.selection([geometryTag '_' tag '_bnd']).entities();
    else
        adjacentTag=sprintf('assembly_member_adj_%04d',k);
        adjacent=comp.selection.create(adjacentTag,'Adjacent');
        adjacent.set('entitydim',3);
        adjacent.set('outputdim',2);
        adjacent.set('input',{[geometryTag '_' tag '_dom']});
        selected=adjacent.entities();
    end
    selected=double(selected); selected=selected(:)';
    faces{k}=intersect(selected,allVacuumFaces);
    faces{k}=faces{k}(:)';
    assert(~isempty(faces{k}),'assembly:MemberFaces', ...
        'A selected canonical member has no vacuum-facing entities: %s',tag);
end
% This selection originates at the authored Block and propagates through both
% Boolean operations. Never infer the exterior from unassigned vacuum faces.
outerTag=[geometryTag '_assembly_outer_bnd'];
try
    outerSelected=double(comp.selection(outerTag).entities());
catch cause
    try
        available=strjoin(string(comp.selection.tags),', ');
    catch inventoryError
        available="<inventory unavailable: " + string(inventoryError.message) + ">";
    end
    failure=MException('assembly:OuterSelectionMissing', ...
        'Missing propagated outer selection %s. Available selection tags: %s', ...
        outerTag,char(available));
    failure=addCause(failure,cause);
    throw(failure);
end
outerSelected=outerSelected(:)';
outerFaces=intersect(outerSelected,allVacuumFaces);
outerFaces=outerFaces(:)';
[groupKeys,groupFaces]=classify_assembly_reference_faces(keys,faces,allVacuumFaces,outerFaces);
% Plane/normal checks are sanity samples, not a proof of the complete face.
% The propagated block selection and preflight clearance supply provenance.
positionTol=double(sanityTolerance.position_mm);
normalTol=double(sanityTolerance.normal_abs);
lo=double(buildResult.outer_box_mm.min(:)); hi=double(buildResult.outer_box_mm.max(:));
assert(isscalar(positionTol) && isfinite(positionTol) && positionTol>=0 && ...
    2*positionTol<min(hi-lo),'assembly:Tolerance','Invalid explicit position tolerance');
assert(isscalar(normalTol) && isfinite(normalTol) && normalTol>=0 && normalTol<1, ...
    'assembly:Tolerance','Invalid explicit normal tolerance');
geom=comp.geom(geometryTag);
planes=false(3,2);
for face=outerFaces(:)'
    range=double(geom.faceParamRange(face));
    uv=[mean(range(1:2)) mean(range(3:4))];
    xyz=double(geom.faceX(face,uv)); xyz=xyz(:);
    normal=double(geom.faceNormal(face,uv)); normal=normal(:);
    assert(numel(xyz)==3 && numel(normal)==3 && all(isfinite([xyz;normal])), ...
        'assembly:OuterGeometry','Invalid outer-face geometry sample');
    hits=false(3,2);
    for axis=1:3
        expected=zeros(3,1); expected(axis)=1;
        aligned=norm(abs(normal)-expected,inf)<=normalTol;
        hits(axis,1)=aligned && abs(xyz(axis)-lo(axis))<=positionTol;
        hits(axis,2)=aligned && abs(xyz(axis)-hi(axis))<=positionTol;
    end
    assert(nnz(hits)==1,'assembly:OuterGeometry', ...
        'Propagated outer face does not match exactly one declared box plane');
    planes=planes | hits;
end
assert(all(planes(:)),'assembly:OuterGeometry','Not all six outer planes are represented');
vacuumDomains=double(vac.entities()); vacuumDomains=vacuumDomains(:)';
selections=struct('group_keys',{groupKeys},'group_faces',{groupFaces}, ...
    'vacuum_domains',vacuumDomains,'outer_faces',outerFaces);
end
