"""Read-only Markdown link checks and editorial inventory for the documentation gate.

Uses repository Markdown conventions, without rendering HTML or accessing the network.
Frozen history is diagnostic-only; its integrity remains owned by the PowerShell gate.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import html
import json
from pathlib import Path
import re
import subprocess
import unicodedata
from urllib.parse import unquote, urlsplit


def is_history(path: Path) -> bool:
    """Recognize only the explicit docs/history boundary, including frozen payloads."""
    return any(a == "docs" and b == "history" for a, b in zip(path.parts, path.parts[1:]))


def document_kind(path: Path) -> str:
    """Classify location and responsibility for inventory; no classification grants authority."""
    if is_history(path):
        return "history"
    if "theory" in path.parts or "multipoles" in path.parts:
        return "theory"
    if "publication" in path.parts:
        return "publication"
    if path.name in {"PROJECT.md", "INTEGRATION.md"}:
        return "current-state"
    if path.name == "README.md":
        return "entry"
    if path.parts[0] == "docs":
        return "repository-reference"
    return "implementation-or-support"


def prose(text: str, *, keep_code_text: bool = False) -> str:
    """Mask fences, HTML comments and inline code while preserving line numbers."""
    result = []
    fence = None
    for line in re.sub(r"<!--[\s\S]*?-->", lambda m: "\n" * m[0].count("\n"), text).splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            result.append("")
        elif marker:
            fence = marker[1]
            result.append("")
        elif line.startswith("    ") or line.startswith("\t"):
            result.append("")
        else:
            result.append(re.sub(r"(`+)(.+?)\1", lambda m: m[2] if keep_code_text else " " * len(m[0]), line))
    return "\n".join(result)


def anchors(text: str) -> set[str]:
    """Build Unicode heading slugs, duplicate suffixes and explicit HTML anchors."""
    clean = prose(text, keep_code_text=True)
    found = set(re.findall(r'<[^>]+\b(?:id|name)=["\']([^"\']+)["\']', clean))
    counts: Counter[str] = Counter()
    headings = []
    lines = clean.splitlines()
    for index, line in enumerate(lines):
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)(?:\s+#+)?\s*$", line)
        if heading:
            headings.append(heading[1])
        elif index and re.fullmatch(r"\s{0,3}(?:=+|-+)\s*", line) and lines[index - 1].strip():
            headings.append(lines[index - 1].strip())
    for heading in headings:
        heading = html.unescape(re.sub(r"<[^>]*>", "", heading))
        heading = re.sub(r"!?\[([^]]*)\]\([^)]*\)", r"\1", heading).lower()
        slug = "".join(c for c in heading if c in "_- " or unicodedata.category(c)[0] in "LNM")
        slug = slug.replace(" ", "-")
        candidate = slug
        while candidate in found:
            counts[slug] += 1
            candidate = f"{slug}-{counts[slug]}"
        found.add(candidate)
    return found


def links(text: str) -> list[tuple[int, str]]:
    """Extract inline and defined full/collapsed/shortcut reference destinations."""
    clean = prose(text)
    definitions = {}
    normalize = lambda value: " ".join(value.casefold().split())
    destination = r'(?:<([^>]+)>|((?:\\.|[^\s()]|\([^()]*\))+))'
    definition = re.compile(r"^\s{0,3}\[([^]]+)\]:\s*" + destination)
    lines = clean.splitlines()
    for line in lines:
        match = definition.match(line)
        if match:
            definitions.setdefault(normalize(match[1]), match[2] or match[3])
    result = []
    inline = re.compile(r"(?<!\\)!?\[(?:[^\[\]]|\[[^]]*\])*\]\(\s*" + destination + r'(?:\s+["\'][^\n]*?["\'])?\s*\)')
    reference = re.compile(r"(?<![\\!])!?\[([^]\n]+)\](?:\[([^]\n]*)\])?")
    for number, line in enumerate(lines, 1):
        if definition.match(line):
            continue
        for match in inline.finditer(line):
            result.append((number, match[1] or match[2]))
        remainder = inline.sub("", line)
        for match in reference.finditer(remainder):
            label = normalize(match[2] or match[1])
            if label in definitions:
                result.append((number, definitions[label]))
    return result


def table_diagnostics(text: str) -> list[tuple[int, str]]:
    """Review table shape and empty cells, without inferring which fields are required.

    Code-span and escaped pipes are cell content. Only header/delimiter pairs
    start tables; fences, indented examples and comments are not tables.
    """
    # Preserve nonempty code cells while hiding their internal separators.
    protected = re.sub(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)",
                       lambda m: m[0].replace("|", "\x00"), text)
    rows = []
    for line in prose(protected, keep_code_text=True).splitlines():
        cells, current = [], []
        for token in re.findall(r"\\.|[^\\|]|[\\|]", line):
            if token == "|":
                cells.append("".join(current).strip())
                current = []
            else:
                current.append(token)
        if not cells:
            rows.append(None)
            continue
        cells.append("".join(current).strip())
        if line.lstrip().startswith("|"):
            cells.pop(0)
        if line.rstrip().endswith("|") and not cells[-1]:
            cells.pop()
        rows.append(cells)
    result = []
    width = None
    for index, cells in enumerate(rows):
        delimiter = cells and all(re.fullmatch(r":?-+:?", cell) for cell in cells)
        if delimiter and index and rows[index - 1]:
            width = len(rows[index - 1])
            if len(cells) != width:
                result.append((index + 1, f"table delimiter has {len(cells)} cells; header has {width}"))
            empty = [str(i + 1) for i, cell in enumerate(rows[index - 1]) if not cell]
            if empty:
                result.append((index, "table header has empty cells at columns " + ", ".join(empty)))
            continue
        if not cells:
            width = None
        elif width is not None:
            if len(cells) != width:
                result.append((index + 1, f"table row has {len(cells)} cells; header has {width}; review missing/extra content"))
            empty = [str(i + 1) for i, cell in enumerate(cells) if not cell]
            if empty:
                result.append((index + 1, "table has empty cells at columns " + ", ".join(empty) + "; review whether intentional"))
    return result


def inspect_repository(root: Path) -> dict:
    """Return errors, nonblocking diagnostics and a per-document inventory."""
    root = root.resolve()
    listing = subprocess.run(["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"], check=True, capture_output=True, cwd=root, timeout=30).stdout
    paths = sorted({root / p.decode("utf-8") for p in listing.split(b"\0") if p and p.lower().endswith(b".md")})
    baseline = subprocess.run(["git", "-C", str(root), "ls-tree", "-rz", "--name-only", "HEAD"], capture_output=True, cwd=root, timeout=30)
    if baseline.returncode and subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "HEAD"], capture_output=True, cwd=root, timeout=30).returncode == 0:
        raise RuntimeError("Cannot read committed history boundary")
    committed = {p.decode("utf-8") for p in baseline.stdout.split(b"\0") if p}
    texts = {p: p.read_text(encoding="utf-8-sig") for p in paths if p.is_file()}
    errors, diagnostics, inventory = [], [], []
    incoming = set()
    paragraphs = defaultdict(set)
    artifact_root = root.parent / "artifacts"
    for path, text in texts.items():
        relative = path.relative_to(root)
        frozen = is_history(relative)
        existing_history = frozen and relative.as_posix() in committed
        row = {"path": relative.as_posix(), "kind": document_kind(relative), "lines": len(text.splitlines()), "characters": len(text), "diagnostics": []}
        inventory.append(row)
        for number, target in links(text):
            target = re.sub(r"\\([() ])", r"\1", html.unescape(target))
            if urlsplit(target).scheme or target.startswith("//"):
                continue
            file_part, _, fragment = target.partition("#")
            resolved = (path.parent / unquote(file_part)).resolve() if file_part else path
            message = None
            external_artifact = resolved == artifact_root or artifact_root in resolved.parents
            if not resolved.exists() and not external_artifact:
                message = f"{relative.as_posix()}:{number}: broken relative link '{target}'"
            elif fragment and resolved.suffix.lower() == ".md" and resolved.is_file():
                content = texts.get(resolved)
                if content is None:
                    content = resolved.read_text(encoding="utf-8-sig")
                if unquote(fragment) not in anchors(content):
                    message = f"{relative.as_posix()}:{number}: broken Markdown anchor '{target}'"
            if message:
                (diagnostics if existing_history else errors).append(message)
                row["diagnostics"].append(message)
            if resolved != path and not frozen:
                incoming.add(resolved)
            if not frozen and "scratch" in resolved.parts:
                message = f"{relative.as_posix()}:{number}: scratch evidence reference '{target}'"
                diagnostics.append(message)
                row["diagnostics"].append(message)
        if frozen:
            continue
        for number, detail in table_diagnostics(text):
            message = f"{relative.as_posix()}:{number}: {detail}"
            diagnostics.append(message)
            row["diagnostics"].append(message)
        for number, line in enumerate(prose(text, keep_code_text=True).splitlines(), 1):
            if re.search(r"(?:artifacts[/\\]|\.\.[/\\])\S*[/\\]scratch[/\\]\S+", line) and not any(f":{number}: scratch evidence" in entry for entry in row["diagnostics"]):
                message = f"{relative.as_posix()}:{number}: scratch path in prose/code span; review evidence lifetime"
                diagnostics.append(message)
                row["diagnostics"].append(message)
        for paragraph in re.split(r"\n\s*\n", prose(text)):
            normalized = " ".join(paragraph.split())
            if len(normalized) >= 200:
                paragraphs[normalized].add(relative.as_posix())
    for row in inventory:
        if row["kind"] == "history":
            continue
        if root / row["path"] not in incoming and row["path"] not in {"README.md", "AGENTS.md", "CLAUDE.md"}:
            row["diagnostics"].append("no incoming link from an active Markdown document (code consumers not assessed)")
        if row["lines"] > 400:
            row["diagnostics"].append("over 400 lines; review navigation and responsibilities")
        for message in row["diagnostics"]:
            if message not in diagnostics and message not in errors:
                diagnostics.append(f"{row['path']}: {message}")
    for paragraph_paths in paragraphs.values():
        if len(paragraph_paths) > 1:
            message = "repeated substantial paragraph: " + ", ".join(sorted(paragraph_paths))
            diagnostics.append(message)
            for row in inventory:
                if row["path"] in paragraph_paths:
                    row["diagnostics"].append(message)
    return {"errors": errors, "diagnostics": diagnostics, "inventory": inventory}


def main() -> int:
    """Emit a read-only report; fail only on active broken local links/anchors."""
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--inventory-json", action="store_true", help="Emit the full inventory to stdout")
    args = parser.parse_args()
    report = inspect_repository(args.root)
    if args.inventory_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for message in report["errors"]:
            print("ERROR: " + message)
        for message in report["diagnostics"]:
            print("REVIEW: " + message)
        print(f"DOCUMENTATION_LINKS: files={len(report['inventory'])} errors={len(report['errors'])} review={len(report['diagnostics'])}")
    return int(bool(report["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
