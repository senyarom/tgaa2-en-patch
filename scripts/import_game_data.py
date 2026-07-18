#!/usr/bin/env python3
"""Recreate build inputs from Japanese, Scarlet Study, and Steam releases."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dgs2tool.arc import extract_arc  # noqa: E402
from scripts.legacy_delta import apply as apply_legacy_delta  # noqa: E402


SUPPORTED_SHA256 = {
    "tgaa1_base": "74b7b13bbee7d57ba93cec26af2f6f02e99ce7aa052ca99ba72b5d92de98a71b",
    "tgaa1_scarlet": "514b3e5c044cf486d7b541a446a2a1071c6dfcc88e839432f9af95456b3880df",
    "tgaa2_base": "435a44807bb4568167ad98c0c20e1658f8977ab14b38bd08be87c3802ef3774e",
    "tgaa2_scarlet": "09c1d69e8e4bc6939ec5b3546e7545997a2751daead143efc08e6d7ed10b6366",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_input(name: str, path: Path) -> None:
    actual = sha256(path)
    expected = SUPPORTED_SHA256[name]
    if actual != expected:
        raise ValueError(f"unsupported {name} CIA: {actual} (expected {expected})")
    print(f"Verified {name}: {actual}")


def run(*command: str | Path) -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT)
    subprocess.run(
        [str(item) for item in command], check=True, cwd=ROOT, env=environment
    )


def run_with_expected_incompatibilities(*command: str | Path) -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT)
    result = subprocess.run([str(item) for item in command], cwd=ROOT, env=environment)
    if result.returncode not in (0, 4):
        raise subprocess.CalledProcessError(result.returncode, result.args)


def extract_cia(
    ctrtool: Path,
    cia: Path,
    output: Path,
    *,
    seeddb: Path | None = None,
) -> Path:
    output.mkdir(parents=True)
    prefix = output / "content"
    cia_options: list[str | Path] = [ctrtool, "-q"]
    if seeddb:
        cia_options.append(f"--seeddb={seeddb.resolve()}")
    run(*cia_options, f"--contents={prefix}", cia)
    contents = sorted(output.glob("content.*"), key=lambda path: path.stat().st_size)
    if not contents:
        raise RuntimeError(f"ctrtool extracted no contents from {cia}")
    application = contents[-1]
    common = [ctrtool, "-q"]
    if seeddb:
        common.append(f"--seeddb={seeddb.resolve()}")
    run(*common, f"--romfsdir={output / 'romfs'}", application)
    run(
        *common,
        f"--exefsdir={output / 'exefs'}",
        "--decompresscode",
        application,
    )
    run(*common, f"--exheader={output / 'exheader.bin'}", application)
    return application


def consolidated_pc_scripts(steam: Path, game: str, output: Path) -> Path:
    output.mkdir(parents=True)
    direct = steam / game / "script" / "output"
    for path in direct.glob("*.gmd"):
        shutil.copy2(path, output / path.name)
    for scene in range(5):
        archive = steam / "archive" / game / f"sce{scene:02}_eng.arc"
        extracted = output.parent / f"sce{scene:02}"
        extract_arc(archive, extracted)
        for path in extracted.rglob("*.gmd"):
            shutil.copy2(path, output / path.name)
    return output


def port_official(
    game: str,
    japanese: Path,
    scarlet: Path,
    steam: Path,
    work: Path,
) -> Path:
    game_code = "GO" if game == "tgaa1" else "BB"
    pc_scripts = consolidated_pc_scripts(
        steam, game_code, work / "pc-scripts" / game_code / "script" / "output"
    )
    official = work / "official"
    run_with_expected_incompatibilities(
        sys.executable,
        "-m",
        "dgs2tool",
        "port-official-tree",
        japanese / "romfs" / "script" / "_output",
        pc_scripts,
        official,
        "-o",
        work / "script-report.json",
    )
    if game == "tgaa1":
        run(
            sys.executable,
            ROOT / "scripts/port_tgaa1_script_exceptions.py",
            "--japanese-root",
            japanese / "romfs" / "script" / "_output",
            "--official-root",
            pc_scripts,
            "--scarlet-root",
            scarlet / "romfs" / "script" / "_output",
            "--output-root",
            official / "romfs" / "script" / "_output",
            "--report",
            work / "script-exceptions.json",
        )
    run_with_expected_incompatibilities(
        sys.executable,
        "-m",
        "dgs2tool",
        "port-official-messages",
        japanese / "romfs" / "msg",
        steam / game_code / "msg",
        official,
        "-o",
        work / "message-report.json",
    )
    if game == "tgaa1":
        run(
            sys.executable,
            ROOT / "scripts/port_tgaa1_message_exceptions.py",
            japanese / "romfs" / "msg",
            official / "romfs" / "msg",
            work / "message-exceptions.json",
        )
    return official


def materialize_game(
    game: str,
    japanese: Path,
    scarlet: Path,
    steam: Path,
    work: Path,
    output: Path,
) -> None:
    official = port_official(game, japanese, scarlet, steam, work)
    candidate = work / "candidate"
    shutil.copytree(scarlet / "romfs", candidate / "romfs")
    shutil.copytree(official / "romfs", candidate / "romfs", dirs_exist_ok=True)
    component_source = work / "component-source"
    component_source.mkdir()
    shutil.copy2(scarlet / "exefs" / "code.bin", component_source / "code.bin")
    shutil.copy2(scarlet / "exefs" / "icon.bin", component_source / "icon.bin")
    shutil.copy2(scarlet / "exheader.bin", component_source / "exheader.bin")

    patched_romfs = work / "patched-romfs"
    apply_legacy_delta(
        candidate / "romfs", ROOT / "patches/legacy" / f"{game}-romfs", patched_romfs
    )
    patched_components = work / "patched-components"
    apply_legacy_delta(
        component_source,
        ROOT / "patches/legacy" / f"{game}-components",
        patched_components,
    )
    output.mkdir(parents=True)
    shutil.move(patched_romfs, output / "romfs")
    for name in ("code.bin", "exheader.bin", "icon.bin"):
        shutil.move(patched_components / name, output / name)

    template = (ROOT / "config" / f"{game}-update.rsf.in").read_text()
    (output / "update.rsf").write_text(template.replace("@ROMFS@", str(output / "romfs")))

    ui_extract = work / "ui-final"
    extract_arc(output / "romfs" / "archive" / "UI_cmn_jpn.arc", ui_extract)
    font = next(ui_extract.rglob("font00_jpn.gfd"))
    shutil.copy2(font, output / "font.gfd")
    if game == "tgaa1":
        tutorial = output / "romfs/script/_output/_sce00_c001_0002_jpn.gmd"
        shutil.copy2(tutorial, output / "tutorial.gmd")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tgaa1-base-cia", required=True, type=Path)
    parser.add_argument("--tgaa1-scarlet-cia", required=True, type=Path)
    parser.add_argument("--tgaa2-base-cia", required=True, type=Path)
    parser.add_argument("--tgaa2-scarlet-cia", required=True, type=Path)
    parser.add_argument("--seeddb", required=True, type=Path)
    parser.add_argument("--steam-root", required=True, type=Path)
    parser.add_argument("--ctrtool", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--resume", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"output already exists: {args.output}")
    for name in SUPPORTED_SHA256:
        check_input(name, getattr(args, f"{name}_cia"))
    staging = args.output.parent / f".{args.output.name}-staging"
    if staging.exists() and not args.resume:
        raise FileExistsError(f"staging directory already exists: {staging}")
    staging.mkdir(parents=True, exist_ok=True)
    extracted = staging / "extracted"
    t1_base = extracted / "tgaa1-base"
    t1_scarlet = extracted / "tgaa1-scarlet"
    t2_base = extracted / "tgaa2-base"
    t2_scarlet = extracted / "tgaa2-scarlet"
    if not args.resume:
        extract_cia(args.ctrtool, args.tgaa1_base_cia, t1_base, seeddb=args.seeddb)
        extract_cia(
            args.ctrtool, args.tgaa1_scarlet_cia, t1_scarlet, seeddb=args.seeddb
        )
        extract_cia(args.ctrtool, args.tgaa2_base_cia, t2_base, seeddb=args.seeddb)
        extract_cia(
            args.ctrtool, args.tgaa2_scarlet_cia, t2_scarlet, seeddb=args.seeddb
        )
    prepared = staging / "prepared"
    materialize_game("tgaa1", t1_base, t1_scarlet, args.steam_root, staging / "tgaa1", prepared / "tgaa1")
    materialize_game("tgaa2", t2_base, t2_scarlet, args.steam_root, staging / "tgaa2", prepared / "tgaa2")
    shutil.move(prepared, args.output)
    print(f"Prepared reproducible game data at {args.output}")


if __name__ == "__main__":
    main()
