"""Pure identity checks for borrowed scalar sample lineage."""


def validate_original_sample_source(item, original) -> None:
    """Require the derived product to borrow the exact flattened raw records."""
    if original.producer.get('status') != 'success':
        raise ValueError('original samples producer must be successful')
    if (original.metadata.get('derivation') is not None
            or original.metadata.get('original_samples_reference') is not None):
        raise ValueError('original samples source must be flattened')
    raw = ('sampled_field_v', 'sampled_field_valid')
    if not all(k in original.data_records for k in raw):
        if any(k in original.data_records for k in raw) or original.metadata.get('conductor_support_policy') is not None:
            raise ValueError('original samples have incomplete raw pair')
        raw = ('field_v', 'field_valid')
    pairs = [('sampled_field_v', raw[0]), ('sampled_field_valid', raw[1])]
    names = ('grid','projection','request','geometry_validation','reopen_geometry',
             'reopen_solution','report','field_solution_manifest')
    pairs += [(name, name) for name in names]
    for name in ('writer', 'writer_manifest'):
        if name in item.data_records or name in original.data_records:
            pairs.append((name, name))
    for selected, source in pairs:
        if selected not in item.data_records or source not in original.data_records:
            raise ValueError('derived sample source record missing: ' + selected)
        a, b = item.data_records[selected], original.data_records[source]
        if (any(a.get(key) != b.get(key) for key in ('bytes','sha256','retention_role'))
                or item.data_path(selected).resolve(strict=True) != original.data_path(source).resolve(strict=True)):
            raise ValueError('derived sample source record differs: ' + selected)
