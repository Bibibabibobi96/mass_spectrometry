"""Admit explicit linear scalar samples for a registered Assembly; no tracking."""

from __future__ import annotations
import copy
import math
from collections.abc import Mapping
from msplatform.backends.comsol.assembly_geometry import project_assembly_geometry
from msplatform.backends.comsol.assembly_electrostatic_model import validate_request
from msplatform.backends.simion.model import _validate_timing, resolve_ip_schedule_authorities
from msplatform.backends.simion.scalar_sample_binding import (
    _read,
    _small_product,
    verify_scalar_sample,
    attach_refinement_windows,
)
from msplatform.io.manifest_records import (
    record_path,
    validate_file_record,
    verify_record,
)


def compile_linear_terms(projection, drive, samples):
    """Check explicit coefficients against actual keyed static, pulse and RF rows."""
    if (
        not isinstance(drive, Mapping)
        or not {"groups", "clock"} <= set(drive)
        or set(drive) - {"groups", "clock", "pulse", "ip_schedule", "ip_schedules"}
    ):
        raise ValueError("explicit groups and clock required")
    groups = drive["groups"]
    if not isinstance(groups, Mapping) or not groups:
        raise ValueError("nonempty group drives required")
    fields = {
        "static": {"kind", "voltage_v"},
        "ip_schedule": {"kind", "schedule_index"},
        "pulse": {"kind", "off_voltage_v", "on_voltage_v"},
        "rf": {
            "kind",
            "waveform",
            "frequency_hz",
            "phase_rad",
            "rf_amplitude_v",
            "polarity",
            "common_mode_v",
            "dc_v",
        },
    }
    for instance, values in groups.items():
        if (
            not isinstance(instance, str)
            or not instance
            or not isinstance(values, Mapping)
            or not values
        ):
            raise ValueError("invalid drive instance")
        for group, row in values.items():
            if (
                not isinstance(group, str)
                or not group
                or not isinstance(row, Mapping)
                or row.get("kind") not in fields
                or set(row) != fields[row.get("kind")]
            ):
                raise ValueError("invalid physical drive row")
    for values in groups.values():
        for row in values.values():
            for key, value in row.items():
                if key not in {"kind", "waveform"} and (
                    type(value) not in (int, float) or not math.isfinite(value)
                ):
                    raise ValueError("finite physical drive values required")
            if row["kind"] == "rf" and (
                row["waveform"] not in ("sine", "cosine")
                or row["frequency_hz"] <= 0
                or row["rf_amplitude_v"] < 0
            ):
                raise ValueError("unsupported RF waveform, frequency or amplitude")
    scheduled = [(i, g) for i, values in groups.items() for g, row in values.items()
                 if row["kind"] == "ip_schedule"]
    scheduled_instances = {instance for instance, _ in scheduled}
    try:
        resolve_ip_schedule_authorities(drive, scheduled_instances)
    except ValueError as exc:
        raise ValueError("canonical IP schedule authority required") from exc
    pulse = any(
        row["kind"] == "pulse" for values in groups.values() for row in values.values()
    )
    if pulse != ("pulse" in drive):
        raise ValueError("pulse timing must match group drives")
    _validate_timing(drive, requires_pulse=pulse)
    keys = [
        (row["instance_id"], row["electrode_group_id"])
        for row in projection["electrode_groups"]
    ]
    rows = {(i, g): row for i, values in groups.items() for g, row in values.items()}
    if len(keys) != len(set(keys)) or set(rows) != set(keys):
        raise ValueError("scientific group coverage differs")
    sigs = sorted(
        {
            (r["waveform"], r["frequency_hz"], r["phase_rad"])
            for r in rows.values()
            if r["kind"] == "rf"
        }
    )
    names = (
        ["carrier"]
        + (["pulse"] if pulse else [])
        + ["rf_" + str(i) for i in range(len(sigs))]
        + ["schedule_" + str(i) for i in range(len(scheduled))]
    )
    vectors = {name: {} for name in names}
    for key, row in rows.items():
        kind = row["kind"]
        if kind not in ("static", "pulse", "rf", "ip_schedule"):
            raise ValueError("unsupported drive kind")
        if kind == "rf" and row["polarity"] not in (-1, 1):
            raise ValueError("RF polarity must be signed")
        vectors["carrier"][key] = (
            row["voltage_v"]
            if kind == "static"
            else row["off_voltage_v"]
            if kind == "pulse"
            else row["common_mode_v"] + row["dc_v"] if kind == "rf" else 0.0
        )
        if pulse:
            vectors["pulse"][key] = (
                (row["on_voltage_v"] - row["off_voltage_v"]) if kind == "pulse" else 0.0
            )
        for i, sig in enumerate(sigs):
            vectors["rf_" + str(i)][key] = (
                (row["polarity"] * row["rf_amplitude_v"])
                if kind == "rf"
                and (row["waveform"], row["frequency_hz"], row["phase_rad"]) == sig
                else 0.0
            )
    # Existing IP field construction uses an independently driven unit response
    # per canonical scheduled group. This proves a conservative full span.
    for i, scheduled_key in enumerate(scheduled):
        vectors["schedule_" + str(i)] = {key: float(key == scheduled_key) for key in keys}
    if any(
        not math.isfinite(value)
        for vector in vectors.values()
        for value in vector.values()
    ):
        raise ValueError("nonfinite derived drive vector")
    if not isinstance(samples, Mapping) or not samples:
        raise ValueError("explicit samples required")
    sample_vectors = {}
    weights = {}
    for name, row in samples.items():
        if not isinstance(name, str) or not name or set(row) != {"request", "weights"}:
            raise ValueError("basis weights required")
        if validate_request(projection, row["request"]) != row["request"]:
            raise ValueError("noncanonical sample request")
        actual = {
            (r["instance_id"], r["electrode_group_id"]): r["voltage_v"]
            for r in row["request"]["group_voltages"]
        }
        if len(actual) != len(keys) or set(actual) != set(keys):
            raise ValueError("basis voltage coverage differs")
        values = row["weights"]
        if not isinstance(values, list) or any(
            not isinstance(v, Mapping)
            or set(v) != {"instance_id", "electrode_group_id", "weight"}
            for v in values
        ):
            raise ValueError("explicit keyed basis weights required")
        mapped = {
            (v["instance_id"], v["electrode_group_id"]): v["weight"] for v in values
        }
        if len(mapped) != len(values) or set(mapped) != set(keys):
            raise ValueError("basis weight group coverage differs")
        if any(
            type(v) not in (int, float) or not math.isfinite(v) for v in mapped.values()
        ):
            raise ValueError("finite basis weights required")
        sample_vectors[name] = actual
        weights[name] = mapped
    # Validate B*L*v=v for every canonical temporal drive vector v.
    # The bound covers nested binary64 products/sums; it is not a voltage tolerance.
    for vector in vectors.values():
        coefficients = {}
        magnitudes = {}
        for name in samples:
            products = [float(weights[name][key]) * float(vector[key]) for key in keys]
            if not all(math.isfinite(x) for x in products):
                raise ValueError("nonfinite basis projection")
            coefficients[name] = math.fsum(products)
            magnitudes[name] = math.fsum(abs(x) for x in products)
        for key in keys:
            products = [
                sample_vectors[name][key] * coefficients[name] for name in samples
            ]
            uncertainty = [
                abs(sample_vectors[name][key]) * magnitudes[name] for name in samples
            ]
            if not all(math.isfinite(x) for x in products + uncertainty):
                raise ValueError("nonfinite span")
            actual = math.fsum(products)
            target = vector[key]
            scale = max(math.fsum(uncertainty), abs(target))
            bound = 4 * (len(keys) + len(samples) + 2) * math.ulp(scale)
            if (
                not math.isfinite(actual)
                or not math.isfinite(bound)
                or abs(actual - target) > bound
            ):
                raise ValueError("basis does not span drive voltage vector")
    return dict(
        clock=copy.deepcopy(drive["clock"]),
        pulse=copy.deepcopy(drive.get("pulse")),
        rf_signatures=[
            dict(waveform=x[0], frequency_hz=x[1], phase_rad=x[2]) for x in sigs
        ],
        terms=names,
    )


def admit_linear_samples(
    *, model_reference, assembly, geometry_artifact, operator, samples, refinement_windows=None
):
    """Verify actual public sample products and exact source workpoints; no qualification."""
    from .model import (
        require_prepared_model,
        model_geometry,
        compile_prepared_model,
        _compile_static_world_published_model,
    )
    from .field_closure import load_field_model

    source = load_field_model(model_reference)
    model = source.model
    document = require_prepared_model(model)
    geometry = model_geometry(model)
    snapshot = dict(
        composition_plan=assembly.composition_plan,
        components_resolved=assembly.components_resolved,
        components_source=assembly.components_source,
    )
    if (
        geometry.frontend_geometry.get("role")
        != "simion_neutral_world_collision_geometry"
        or geometry.frontend_geometry.get("source_snapshot") != snapshot
    ):
        raise ValueError("model and registered Assembly source differ")
    compiler = (
        _compile_static_world_published_model
        if "producer_validated_members" in geometry.frontend_geometry
        else compile_prepared_model
    )
    rebuilt = compiler(
        geometry,
        assembly.components_resolved,
        drive=document["drive"],
        physics=document["physics"],
    )
    if require_prepared_model(rebuilt) != document:
        raise ValueError("model drive differs from canonical Assembly")
    drive = document["drive"]
    producer, product, path = _small_product(
        geometry_artifact, "geometry_artifact", ("projection",)
    )
    meta = product["metadata"]
    if (
        meta.get("backend") != "comsol"
        or meta.get("scope") != "geometry_only"
        or meta.get("native_reopen_verified") is not True
    ):
        raise ValueError("successful reopened geometry required")
    record = validate_file_record(
        producer["inputs"]["execution_request"], "geometry request"
    )
    verify_record("geometry request", record, base_dir=path.parent)
    frozen = _read(record_path(record, base_dir=path.parent))
    projection = _read(record_path(product["data"]["projection"], base_dir=path.parent))
    snapshot = dict(
        composition_plan=assembly.composition_plan,
        components_resolved=assembly.components_resolved,
        components_source=assembly.components_source,
    )
    if (
        frozen.get("role") != "run_artifact_workflow_request"
        or frozen["payload"].get("action") != "build_comsol_geometry"
        or frozen["payload"]["assembly"] != snapshot
        or frozen["payload"]["projection"] != projection
        or project_assembly_geometry(snapshot, outer_box_mm=projection["outer_box_mm"])
        != projection
    ):
        raise ValueError("geometry source differs")
    rows = {
        name: dict(request=value["request"], weights=value["weights"])
        for name, value in samples.items()
    }
    plan = compile_linear_terms(projection, drive, rows)
    def admit_level(level_samples):
        if not isinstance(level_samples, Mapping) or set(level_samples) != set(samples):
            raise ValueError("scalar refinement basis coverage differs")
        bindings, grid = {}, None
        for name, reference in level_samples.items():
            expected = samples[name]["request"]
            if (any(expected.get(key) != value for key, value in operator.items())
                    or set(operator) != {"relative_permittivity", "exterior", "mesh", "study"}
                    or operator["exterior"] != {"kind": "potential", "voltage_v": 0.0}):
                raise ValueError("common linear zero-exterior operator required")
            def check(request):
                if request != expected: raise ValueError("sample workpoint differs")
            binding = verify_scalar_sample(reference, projection, check_workpoint=check, resolve_reference=True)
            if grid is not None and binding["grid"] != grid: raise ValueError("sample grids differ")
            grid = binding["grid"]
            bindings[name] = binding
        return {"bases": bindings, "grid": grid}

    base = admit_level({name: row["reference"] for name, row in samples.items()})
    bindings, grid = base["bases"], base["grid"]
    attach_refinement_windows(bindings, refinement_windows, admit_level=admit_level)
    return dict(
        schema_version=1,
        role="generic_linear_scalar_admission",
        model_identity_sha256=document["model_identity_sha256"],
        model_reference=source.artifact.reference,
        clock_authority_reference=source.clock_authority_reference,
        geometry_reference=copy.deepcopy(
            dict(
                geometry_artifact.reference
                if hasattr(geometry_artifact, "reference")
                else geometry_artifact
            )
        ),
        geometry_execution_request=dict(
            record, path=str(record_path(record, base_dir=path.parent))
        ),
        terms=plan,
        grid=grid,
        bases=bindings,
        weights={name: copy.deepcopy(row["weights"]) for name, row in samples.items()},
        scope="declared_linear_composition_not_same_mesh_or_qualification",
    )
