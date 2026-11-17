"""Bounded plain-Lua evaluation for native backend contracts."""
from pathlib import Path
import subprocess


def run_lua_program(executable: Path, program: Path, working_directory: Path) -> str:
    result = subprocess.run(
        [str(executable), str(program)], cwd=working_directory,
        capture_output=True, text=True, timeout=30, check=True,
    )
    return result.stdout
