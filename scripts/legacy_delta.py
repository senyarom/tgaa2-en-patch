#!/usr/bin/env python3
"""Create or apply the small legacy delta after the Scarlet+Steam stage."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dgs2tool.bps import apply_bps, create_bps


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def files(root: Path) -> dict[str, Path]:
    return {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file()
    }


def create(source: Path, target: Path, bundle: Path) -> None:
    source_files = files(source)
    target_files = files(target)
    if source_files.keys() != target_files.keys():
        raise ValueError(
            "legacy-delta trees have different file sets: "
            f"only_source={sorted(source_files.keys() - target_files.keys())}, "
            f"only_target={sorted(target_files.keys() - source_files.keys())}"
        )
    records = []
    for relative in sorted(source_files):
        before = source_files[relative].read_bytes()
        after = target_files[relative].read_bytes()
        if before == after:
            continue
        patch = create_bps(before, after, relative.encode())
        patch_path = bundle / "patches" / f"{len(records):04d}.bps"
        patch_path.parent.mkdir(parents=True, exist_ok=True)
        patch_path.write_bytes(patch)
        records.append(
            {
                "path": relative,
                "patch": patch_path.relative_to(bundle).as_posix(),
                "source_sha256": digest(before),
                "target_sha256": digest(after),
            }
        )
    manifest = {"schema": 1, "files": len(target_files), "patches": records}
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"created {len(records)} legacy patches for {len(target_files)} files")


def apply(source: Path, bundle: Path, output: Path) -> None:
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != 1:
        raise ValueError("unsupported legacy-delta manifest")
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    shutil.copytree(source, output)
    for record in manifest["patches"]:
        path = output / record["path"]
        before = path.read_bytes()
        if digest(before) != record["source_sha256"]:
            raise ValueError(f"legacy-delta source hash mismatch: {record['path']}")
        after = apply_bps(before, (bundle / record["patch"]).read_bytes())
        if digest(after) != record["target_sha256"]:
            raise ValueError(f"legacy-delta target hash mismatch: {record['path']}")
        path.write_bytes(after)
    print(f"applied {len(manifest['patches'])} legacy patches")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    creator = subparsers.add_parser("create")
    creator.add_argument("source", type=Path)
    creator.add_argument("target", type=Path)
    creator.add_argument("bundle", type=Path)
    applier = subparsers.add_parser("apply")
    applier.add_argument("source", type=Path)
    applier.add_argument("bundle", type=Path)
    applier.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.command == "create":
        create(args.source, args.target, args.bundle)
    else:
        apply(args.source, args.bundle, args.output)


if __name__ == "__main__":
    main()
