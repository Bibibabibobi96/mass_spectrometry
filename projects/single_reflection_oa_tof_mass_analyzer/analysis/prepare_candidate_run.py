"""Project CLI forwarding for the installed OA-TOF candidate preparation owner."""
from __future__ import annotations

import sys
from pathlib import Path

from msplatform.workflows.oa_candidate.prepare_candidate_run import (
    _candidate_sources as _candidate_sources,
    _inside as _inside,
    _manifest_alias_record as _manifest_alias_record,
    _provenance_path as _provenance_path,
    _registered_candidate_template as _registered_candidate_template,
    _registered_template_source_path as _registered_template_source_path,
    _select_postprocess_child_exports as _select_postprocess_child_exports,
    candidate_native_execution_relative_paths as candidate_native_execution_relative_paths,
    freeze_pa_producer_handoffs as freeze_pa_producer_handoffs,
    load_pa_producer_handoffs as load_pa_producer_handoffs,
    plan_pa_producer_handoffs as plan_pa_producer_handoffs,
    prepare_candidate_run as _prepare_candidate_run,
    prepare_postprocess_request as _prepare_postprocess_request,
    select_postprocess_parent as select_postprocess_parent,
    validate_artifact_capacity as validate_artifact_capacity,
    validate_workflow as validate_workflow,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parents[1]


def prepare_candidate_run(*args, **kwargs) -> dict:
    """Preserve the checkout entry while forwarding its explicit science root."""
    return _prepare_candidate_run(*args, **kwargs, science_root=REPO_ROOT)


def prepare_postprocess_request(parent: Path, run_id: str) -> dict:
    """Preserve the checkout postprocess entry through explicit forwarding."""
    return _prepare_postprocess_request(parent, run_id, science_root=REPO_ROOT)


def main() -> None:
    from msplatform.workflows.oa_candidate.prepare_candidate_run import main as installed_main
    if "--science-root" not in sys.argv:
        sys.argv.extend(["--science-root", str(REPO_ROOT)])
    installed_main()


if __name__ == "__main__":
    main()
