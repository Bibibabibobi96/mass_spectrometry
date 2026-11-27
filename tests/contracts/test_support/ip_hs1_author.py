"""Explicitly migrate an inert fixture's original outer state into its gas author."""
import json
from importlib.resources import files
from pathlib import Path

from msplatform.io.manifest_records import file_record


def environment_record(directory, *, pressure_pa, temperature_k, bulk_velocity_m_s):
    author = json.loads(files("msplatform").joinpath("components/ion_processor/config/gas_environment.json").read_text(encoding="utf-8"))
    author["outer_state"] = dict(pressure_pa=pressure_pa, temperature_k=temperature_k,
                                 bulk_velocity_m_s=list(bulk_velocity_m_s))
    path = Path(directory) / "hs1_environment_author.json"
    path.write_text(json.dumps(author), encoding="utf-8", newline="\n")
    return file_record(path)
