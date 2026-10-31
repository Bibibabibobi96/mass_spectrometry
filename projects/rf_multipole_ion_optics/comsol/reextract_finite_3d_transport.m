function receipt=reextract_finite_3d_transport(request,fid)
%REEXTRACT_FINITE_3D_TRANSPORT Read a saved finite solution; never solve/save it.
% request.context MUST be projected by the original frozen input owner, not
% reconstructed with current registry defaults. Output ownership is the caller's.
required={'model_path','source_path','source_metadata_path','mapping_path','context'};
assert(isstruct(request)&&all(isfield(request,required)), ...
 'rf:ExtractionRequest','Cold extraction request is incomplete.');
for name={'model_path','source_path','source_metadata_path','mapping_path'}
 assert(isfile(request.(name{1})),'rf:ExtractionDependency', ...
  'Required frozen extraction dependency is missing: %s',name{1});
end
source=readtable(request.source_path);
metadata=jsondecode(fileread(request.source_metadata_path));
mapping=jsondecode(fileread(request.mapping_path));
assert(all(isfield(mapping,{'native_order','source_ids','source_birth_s','native_scope'}))&& ...
 strcmp(mapping.native_scope,'complete_cohort'), ...
 'rf:ExtractionMapping','Frozen complete-cohort mapping is required.');
context=request.context;
assert(isequal(context.native_order(:),mapping.native_order(:))&& ...
 isequal(context.source_ids(:),mapping.source_ids(:))&& ...
 isequal(context.source_birth_s(:),mapping.source_birth_s(:)), ...
 'rf:ExtractionMapping','Request differs from saved release mapping.');
validate_finite_extraction_context(source,metadata,context);
% Do not permit CSV destinations to overwrite any protected parent input.
protected={request.model_path,request.source_path,request.source_metadata_path,request.mapping_path};
outputNames=fieldnames(context.outputs);
for index=1:numel(outputNames)
 destination=context.outputs.(outputNames{index});
 assert(isempty(destination)||~any(strcmpi(destination,protected)), ...
  'rf:ExtractionOutput','Extraction output aliases a frozen input.');
end
import com.comsol.model.util.*
tag=char(java.util.UUID.randomUUID());tag=['RF_COLD_' strrep(tag,'-','_')];
model=mphload(request.model_path,tag);
cleanup=onCleanup(@()ModelUtil.remove(tag));
solutions=cell(model.sol.tags());
assert(all(ismember({context.solution_on,context.solution_zero},solutions)), ...
 'rf:ExtractionSolution','Saved primary/control solutions are missing.');
% Datasets are presentation-only; an absent one is created only in memory.
for pair={ {context.dataset_on,context.solution_on}, {context.dataset_zero,context.solution_zero} }
 binding=pair{1};datasets=cell(model.result.dataset.tags());
 if any(strcmp(datasets,binding{1}))
  dataset=model.result.dataset(binding{1});
  assert(strcmp(char(dataset.getString('solution')),binding{2}), ...
   'rf:ExtractionDataset','Saved dataset is bound to a different solution.');
 else
  dataset=model.result.dataset.create(binding{1},'Particle');
  dataset.set('solution',binding{2});
 end
end
receipt=export_finite_3d_particle_outputs(model,source,metadata,context,fid);
receipt.parent_model_saved=false;receipt.native_solves=0;
clear cleanup
end
