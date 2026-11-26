"""Thin installed command line over the same recipe, workflow and results APIs."""
from __future__ import annotations

import argparse
import json
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Validate or run a recipe, inspect a run, or collect eligible managed caches."""
    parser = argparse.ArgumentParser(prog="msplatform")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="resolve SI inputs and check supported capabilities")
    validate.add_argument("recipe")
    run = commands.add_parser("run", help="trace a recipe and publish complete evidence")
    run.add_argument("recipe")
    run.add_argument("--artifact-root", required=True)
    run.add_argument("--source-revision", help="explicit repository SHA for provenance; never a cache invalidation key")
    for name in ("high-water-bytes", "low-water-bytes"):
        run.add_argument("--" + name, type=int)
    run.add_argument("--safety-bytes", type=int, default=0)
    run.add_argument("--reserve-bytes", type=int, default=0)
    for command in (validate, run):
        command.add_argument("--execution-environment", help="explicit native machine deployment JSON")
        command.add_argument("--profile", help="named native engineering profile")
        command.add_argument("--workspace", help="existing native execution owner's workspace")
    results = commands.add_parser("results").add_subparsers(dest="results_command", required=True)
    inspect = results.add_parser("inspect", help="verify and recompute statistics from published data")
    inspect.add_argument("run_id")
    inspect.add_argument("--artifact-root", required=True)
    gc = commands.add_parser("gc", help="collect only policy-eligible unprotected caches")
    gc.add_argument("--artifact-root", required=True)
    gc.add_argument("--target-bytes", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        context = None
        if args.command in {"validate", "run"}:
            selected = (args.execution_environment, args.profile, args.workspace)
            if any(selected):
                if not all(selected):
                    raise ValueError("native deployment requires execution-environment, profile and workspace together")
                from msplatform.execution.context import load_environment
                context = load_environment(args.execution_environment, workspace=args.workspace, profile=args.profile)
        if args.command == "validate":
            from msplatform.recipes import load_recipe
            from msplatform.tracing import preflight
            output = load_recipe(args.recipe).to_dict()
            if output["schema_version"] == 2:
                from msplatform.workflows.native_tracing import preflight_native
                output = {"resolved": output, "capabilities": preflight_native(output, context=context)}
            else:
                if context is not None:
                    raise ValueError("reference validation does not consume a native deployment")
                preflight(output)
        elif args.command == "run":
            from msplatform.workflows.reference_tracing import run_recipe
            output = run_recipe(args.recipe, artifact_root=args.artifact_root,
                                high_water_bytes=args.high_water_bytes, low_water_bytes=args.low_water_bytes,
                                safety_bytes=args.safety_bytes, reserve_bytes=args.reserve_bytes,
                                source_revision=args.source_revision, context=context)
        elif args.command == "results":
            from msplatform.workflows.reference_tracing import inspect_results
            output = inspect_results(args.run_id, artifact_root=args.artifact_root)
        else:
            from msplatform.storage import ArtifactStore
            output = ArtifactStore(args.artifact_root).collect(target_bytes=args.target_bytes)
        print(json.dumps(output, ensure_ascii=False, allow_nan=False, indent=2))
        status = (output.get("summary") or {}).get("execution_status") if isinstance(output, dict) else None
        return 1 if status in {"failed", "cancelled"} else 0
    except (ValueError, OSError, RuntimeError, KeyError) as error:
        parser.exit(2, f"msplatform: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
