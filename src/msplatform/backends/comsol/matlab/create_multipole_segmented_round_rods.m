function [tags, metadata] = create_multipole_segmented_round_rods(geom, rodArray, axialContract, tagPrefix)
%CREATE_MULTIPOLE_SEGMENTED_ROUND_RODS Build common-mode stepped RF rod segments.
if nargin < 4 || isempty(tagPrefix), tagPrefix = 'rod'; end
rods = rodArray.rods;
segments = axialContract.derived.segments;
tags = cell(1, numel(rods)*numel(segments));
metadata = repmat(struct('tag','','rod_id',0,'electrode_group',0, ...
    'segment_id',0,'common_mode_V',0), 1, numel(tags));
cursor = 0;
for segmentIndex = 1:numel(segments)
    segment = segments(segmentIndex);
    segmentArray = rodArray;
    for rodIndex = 1:numel(rods)
        segmentArray.rods(rodIndex).z_min_mm = segment.z_min_mm;
        segmentArray.rods(rodIndex).z_max_mm = segment.z_max_mm;
    end
    segmentTags = create_multipole_round_rods(geom, segmentArray, ...
        sprintf('%s_s%d_r', tagPrefix, segment.segment_id), 'z', [0 0 0]);
    for rodIndex = 1:numel(rods)
        cursor = cursor + 1;
        tags{cursor} = segmentTags{rodIndex};
        metadata(cursor) = struct('tag',segmentTags{rodIndex}, ...
            'rod_id',rods(rodIndex).rod_id, ...
            'electrode_group',rods(rodIndex).electrode_group, ...
            'segment_id',segment.segment_id, ...
            'common_mode_V',segment.common_mode_V);
    end
end
end
