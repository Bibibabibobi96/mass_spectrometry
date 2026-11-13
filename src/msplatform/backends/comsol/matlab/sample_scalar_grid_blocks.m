function [potential,valid,finiteFEM,filledConductor,querySeconds] = sample_scalar_grid_blocks(grid, sampler, fillMissing)
% Shared scalar sampling mechanics. Caller supplies actual coordinate/physics policy.
dimensions=double(grid.dimensions(:).');pitch=double(grid.pitch_mm(:));origin=double(grid.origin_mm(:));
pointCount=prod(dimensions);potential=zeros(pointCount,1);valid=false(pointCount,1);
finiteFEM=0;filledConductor=0;queryTimer=tic;
for first=1:grid.block_points:pointCount
    last=min(pointCount,first+grid.block_points-1);index=first:last;
    [ix,iy,iz]=ind2sub(dimensions,index);coordinates=origin+pitch.*[ix-1;iy-1;iz-1];
    values=double(sampler(coordinates));values=values(:).';finite=isfinite(values);
    finiteFEM=finiteFEM+nnz(finite);missing=find(~finite);
    if ~isempty(missing) && ~isempty(fillMissing)
        conductorVoltage=fillMissing(coordinates(:,missing).');known=isfinite(conductorVoltage);
        values(missing(known))=conductorVoltage(known).';finite(missing(known))=true;
        filledConductor=filledConductor+nnz(known);
    end
    values(~finite)=0;potential(index)=values;valid(index)=finite;
    fprintf('SCALAR_EXPORT_BLOCK %d/%d elapsed=%.3f\n',last,pointCount,toc(queryTimer));
end
querySeconds=toc(queryTimer);
end
