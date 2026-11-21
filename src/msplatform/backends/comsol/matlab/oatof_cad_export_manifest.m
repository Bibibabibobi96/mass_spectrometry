function manifest = oatof_cad_export_manifest(featureTags)
%OATOF_CAD_EXPORT_MANIFEST Discover physical bodies in the actual oa-TOF geometry.
% Ring counts come only from completed feature tags, never a default design.
% Outer solids/bore cutters (suffix O/H), ideal grids and vacuum are excluded.
arguments
    featureTags (:,1) string
end
accelerator = ring_tags(featureTags, "accelring_");
stage1 = ring_tags(featureTags, "ring1_");
stage2 = ring_tags(featureTags, "ring2_");
fixed = ["repeller"; "accelshield"; "flighttubewall"; "backplate"; "detector"];
assert(all(ismember(fixed,featureTags)), 'oatofCadExport:MissingPhysicalFeature', ...
    'The complete oa-TOF geometry must contain each fixed physical feature.');
featureTag = [fixed(1:2); accelerator; fixed(3); stage1; stage2; fixed(4:5)];
component = ["repeller"; "accelerator_shield"; ...
    repmat("accelerator_ring",numel(accelerator),1); "flight_tube_shield"; ...
    repmat("reflectron_stage1_ring",numel(stage1),1); ...
    repmat("reflectron_stage2_ring",numel(stage2),1); "reflectron_backplate"; "detector"];
manifest = table(featureTag,component,'VariableNames',{'FeatureTag','Component'});
end

function tags = ring_tags(allTags,prefix)
tokens = regexp(cellstr(allTags), ['^' char(prefix) '(\d+)$'], 'tokens', 'once');
selected = ~cellfun(@isempty,tokens);
tags = allTags(selected);
assert(~isempty(tags), 'oatofCadExport:MissingRings', ...
    'No completed %s ring features found for CAD export.',prefix);
numbers = cellfun(@(token) str2double(token{1}),tokens(selected));
[numbers,order] = sort(numbers);
tags = tags(order);
% The provider builders use canonical consecutive indices starting at one.
% Reject gaps, repeated indices and aliases such as ring1_01 rather than
% silently exporting an incomplete or ambiguous mechanical stack.
assert(isequal(numbers(:),(1:numel(numbers))') && ...
    all(tags == prefix+string(numbers(:))), 'oatofCadExport:RingNumbering', ...
    'Completed %s ring features must have unique consecutive canonical indices.',prefix);
end
