"""Validate one paired static common-point sample set."""
from pathlib import Path
import pandas as pd
from msplatform.analysis.vector_field_samples import _require_static_samples
from msplatform.analysis.field_comparison import merge_complete_samples


def validate_samples(plan: dict, path: Path) -> None:
    """Require the actual complete common point set; make no tolerance decision."""
    actual = pd.read_csv(path, float_precision='round_trip')
    _require_static_samples(actual, 'native')
    expected = pd.read_csv(plan['sample_points']['path'], float_precision='round_trip')
    columns = ['point_id', 'x_mm', 'y_mm', 'z_mm']
    merge_complete_samples(expected, actual, keys=columns, left_label='prepared', right_label='native')
