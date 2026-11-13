function [groupKeys,groupFaces] = classify_assembly_reference_faces(keys,faces,allVacuumFaces,outerFaces)
%CLASSIFY_ASSEMBLY_REFERENCE_FACES Preserve complete disjoint entity sets.
% Accept native row or column vectors; output is consistently row-oriented.
assert(numel(keys)==numel(faces),'assembly:MemberFaces','Member selection count differs');
allVacuumFaces=double(allVacuumFaces); allVacuumFaces=allVacuumFaces(:)';
outerFaces=double(outerFaces); outerFaces=outerFaces(:)';
assert(~isempty(allVacuumFaces),'assembly:VacuumFaces','Reference vacuum has no boundary faces');
for k=1:numel(faces)
    value=double(faces{k}); faces{k}=value(:)';
    assert(~isempty(faces{k}),'assembly:MemberFaces','A selected member has no vacuum-facing entities');
    assert(isempty(setdiff(faces{k},allVacuumFaces)),'assembly:MemberFaces','Member face is outside vacuum');
end
[groupKeys,~,indices]=unique(keys,'stable');
groupFaces=cell(1,numel(groupKeys));
for k=1:numel(groupKeys)
    groupFaces{k}=unique([faces{indices==k}]);
    for j=1:k-1
        assert(isempty(intersect(groupFaces{k},groupFaces{j})), ...
            'assembly:GroupOverlap','Distinct scientific groups share boundary entities');
    end
end
occupied=unique([groupFaces{:}]);
assert(~isempty(outerFaces),'assembly:OuterFaces','Propagated outer boundary is empty');
assert(isempty(intersect(outerFaces,occupied)),'assembly:OuterContact', ...
    'Outer boundary overlaps a selected canonical member');
assert(isempty(setxor(unique([outerFaces occupied]),unique(allVacuumFaces))), ...
    'assembly:UnclassifiedFaces','Vacuum boundary classification is incomplete');
end
