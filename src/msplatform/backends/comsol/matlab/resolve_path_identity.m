function identity = resolve_path_identity(path)
%RESOLVE_PATH_IDENTITY Resolve existing links before appending future leaves.
% Identity is for authority/comparison only. Keep the original caller spelling
% for native argv, cwd and output paths. Java Path.toRealPath follows existing
% links; File.getCanonicalPath does not guarantee stable future-file identity.
    arguments
        path {mustBeTextScalar, mustBeNonempty}
    end
    candidate = java.io.File(char(path)).toPath().toAbsolutePath();
    follow = javaArray('java.nio.file.LinkOption', 0);
    noFollow = javaArray('java.nio.file.LinkOption', 1);
    noFollow(1) = java.nio.file.LinkOption.NOFOLLOW_LINKS;
    leaves = {};
    while true
        try
            resolved = candidate.toRealPath(follow);
            break
        catch failure
            if ~isa(failure, 'matlab.exception.JavaException') || ...
                    ~isa(failure.ExceptionObject, 'java.nio.file.NoSuchFileException')
                rethrow(failure)
            end
            % An existing but unresolved link is not a missing future leaf.
            if java.nio.file.Files.exists(candidate, noFollow)
                rethrow(failure)
            end
            leaf = char(candidate.getFileName());
            assert(~ismember(leaf, {'.', '..'}), 'paths:UnresolvedParentTraversal', ...
                'A future path cannot traverse a missing parent; use an existing parent.');
            leaves = [{leaf}, leaves]; %#ok<AGROW>
            parent = candidate.getParent();
            if isempty(parent), rethrow(failure); end
            candidate = parent;
        end
    end
    for index = 1:numel(leaves)
        resolved = resolved.resolve(leaves{index});
    end
    identity = char(resolved.toString());
end
