"""Shared test helper for declared dependency path expansion."""


def declared_dependency_paths(repo, contract, consumer):
    """Expand the actual test author's explicit source and resource declarations."""
    from msplatform.execution.inputs import enumerate_python_sources
    paths = {row['source_repo_path'] for group in contract['providers'] for row in group['files']
             if consumer in row['consumers']}
    for group in contract['providers']:
        selections = [row for row in group['python_packages'] if consumer in row['consumers']]
        modules = [row['source_repo_path'] for row in group['python_modules'] if consumer in row['consumers']]
        if selections or modules:
            paths.update(enumerate_python_sources(repo,
                package_roots=[row['source_repo_path'] for row in selections], module_paths=modules))
        for selection in selections:
            if selection.get('resource_suffixes'):
                paths.update(enumerate_python_sources(repo, package_roots=[selection['source_repo_path']],
                    resource_suffixes=selection['resource_suffixes']))
    return paths
