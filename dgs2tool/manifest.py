"""Parse the DGS2 GodMode9 autorun script into a machine-readable manifest."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


SET_RE = re.compile(r"^set\s+([A-Z0-9_]+)\s+(.+?)\s*$")
COPY_RE = re.compile(
    r"^cp\s+-p\s+\$\[SOURCE\]/(?P<path>\S+)\s+"
    r"\$\[OUTPATH\]/DGS-JPN\.bin\s*$"
)
MANUAL_RE = re.compile(
    r"^cp\s+-p\s+\$\[OUTPATH\]/manual\.bcma\s+"
    r"\$\[OUTPATH\]/DGS-JPN\.bin\s*$"
)
SCENE_RE = re.compile(r"(?:^|/)_sce(?P<number>\d{2})(?:_|\.)")


def _kind(path: str) -> str:
    suffix = Path(path).suffix.lower().lstrip(".")
    return suffix or "unknown"


def parse_autorun(text: str) -> dict:
    variables: dict[str, str] = {}
    resources: list[dict] = []

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        match = SET_RE.match(line)
        if match:
            variables[match.group(1)] = match.group(2)
            continue

        match = COPY_RE.match(line)
        if match:
            path = match.group("path")
            scene_match = SCENE_RE.search(path)
            resources.append(
                {
                    "order": len(resources),
                    "line": line_number,
                    "source": "game",
                    "path": path,
                    "kind": _kind(path),
                    "scene_number": int(scene_match.group("number")) if scene_match else None,
                }
            )
            continue

        if MANUAL_RE.match(line):
            resources.append(
                {
                    "order": len(resources),
                    "line": line_number,
                    "source": "extracted_manual",
                    "path": "manual.bcma",
                    "kind": "bcma",
                    "scene_number": None,
                }
            )

    if not resources:
        raise ValueError("autorun script contains no patch input resources")

    counts: dict[str, int] = {}
    for resource in resources:
        counts[resource["kind"]] = counts.get(resource["kind"], 0) + 1

    encoded = text.encode("utf-8")
    return {
        "schema": 1,
        "source_sha256": hashlib.sha256(encoded).hexdigest(),
        "variables": variables,
        "summary": {
            "resource_count": len(resources),
            "kinds": dict(sorted(counts.items())),
        },
        "resources": resources,
    }


def parse_autorun_file(path: Path) -> dict:
    return parse_autorun(path.read_text(encoding="utf-8"))


def save_manifest(manifest: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check_romfs(manifest: dict, root: Path) -> dict:
    root = root.resolve()
    found: list[dict] = []
    missing: list[str] = []

    for resource in manifest["resources"]:
        if resource["source"] != "game":
            continue

        relative = Path(resource["path"])
        if root.name.lower() == "romfs" and relative.parts and relative.parts[0].lower() == "romfs":
            relative = Path(*relative.parts[1:])
        candidate = root / relative
        if not candidate.is_file():
            missing.append(resource["path"])
            continue
        stat = candidate.stat()
        found.append({"path": resource["path"], "size": stat.st_size})

    return {
        "root": str(root),
        "expected_game_files": len(found) + len(missing),
        "found": len(found),
        "missing_count": len(missing),
        "missing": missing,
        "files": found,
    }
