#!/usr/bin/env python3
"""Recreate build inputs semantically from Japanese, Scarlet, and Steam releases."""

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

from dgs2tool.arc import build_arc_bytes, extract_arc, parse_arc  # noqa: E402
from dgs2tool.gmd import build_gmd_bytes, parse_gmd_bytes  # noqa: E402
from scripts.build_3ds_official_layout import (  # noqa: E402
    adapt_3ds_gfd,
    read_pc_v3_advances,
)
from scripts.patch_tgaa1_3ds_ui import apply_layout_overrides  # noqa: E402
from scripts.restore_title_dlc_gui import patch_gui  # noqa: E402


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


def steam_archive(steam: Path, game_code: str, filename: str) -> Path:
    all_candidates = [
        path
        for path in steam.rglob("*.arc")
        if path.name.casefold() == filename.casefold()
    ]
    game_candidates = [
        path
        for path in all_candidates
        if game_code.casefold() in {part.casefold() for part in path.parts}
    ]
    candidates = game_candidates or all_candidates
    if len(candidates) != 1:
        raise ValueError(
            f"expected one Steam {game_code}/{filename}, found {len(candidates)}: "
            f"{candidates}"
        )
    return candidates[0]


def rebuild_font_archive(
    game_code: str, steam: Path, romfs: Path, work: Path
) -> tuple[Path, Path]:
    archive_path = romfs / "archive" / "UI_cmn_jpn.arc"
    source = work / "ui-3ds"
    pc = work / "ui-pc"
    extract_arc(archive_path, source)
    extract_arc(steam_archive(steam, game_code, "font_eng.arc"), pc)
    source_gfd = next(source.rglob("font00_jpn.gfd"))
    dialogue_gfd = (
        next(source.rglob("font03_jpn.gfd")) if game_code == "GO" else source_gfd
    )
    source_atlas = next(source.rglob("font00_jpn_00_AM_NOMIP.tex"))
    # TGAA1 intentionally uses the broad font02 character set.  Besides
    # covering the complete English script, its wider advances are the ones
    # used by the released 3DS layout.  TGAA2 retains Scarlet Study's narrower
    # font00-based metrics.
    pc_font_name = "font02.gfd" if game_code == "GO" else "font00_eng.gfd"
    pc_gfd = next(pc.rglob(pc_font_name))
    adapted = work / "font00_jpn.gfd"
    adapt_3ds_gfd(
        source_gfd,
        read_pc_v3_advances(pc_gfd),
        source_atlas,
        adapted,
        1 / 3,
    )
    archive = parse_arc(archive_path.read_bytes())
    entry = next(item for item in archive["entries"] if item.name.endswith("font00_jpn.gfd"))
    archive_path.write_bytes(build_arc_bytes(archive, {entry.name: adapted.read_bytes()}))
    return adapted, dialogue_gfd


def rebuild_message_archive(
    game: str, game_code: str, steam: Path, romfs: Path, work: Path
) -> None:
    archive_path = romfs / "archive" / "msg_cmn_jpn.arc"
    source = work / "msg-3ds"
    pc = work / "msg-pc"
    pc_merged = work / "msg-pc-merged"
    ported = work / "msg-ported"
    extract_arc(archive_path, source)
    for archive_name in (
        "msg_cmn_eng.arc",
        "msg_title_eng.arc",
        "msg_sys_eng.arc",
        "special_cmn_eng.arc",
        "UI_cmn_eng.arc",
        "UI_sys_eng.arc",
    ):
        extracted = pc / archive_name.removesuffix(".arc")
        extract_arc(steam_archive(steam, game_code, archive_name), extracted)
        for localized in extracted.rglob("*_eng.gmd"):
            destination = pc_merged / localized.name
            if destination.exists() and destination.read_bytes() != localized.read_bytes():
                # Prefer the game-specific GO/BB table over a shared variant.
                if game_code.casefold() not in {
                    part.casefold() for part in localized.parts
                }:
                    continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(localized, destination)
    run_with_expected_incompatibilities(
        sys.executable,
        "-m",
        "dgs2tool",
        "port-official-messages",
        source / "msg",
        pc_merged,
        ported,
        "-o",
        work / "msg-archive-report.json",
    )
    replacements_root = ported / "romfs" / "msg"
    for original in (source / "msg").glob("*.gmd"):
        destination = replacements_root / original.name
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, destination)
    if game == "tgaa1":
        # These five tables describe 3DS-native menus.  Keep Scarlet Study's
        # controller/touch wording instead of importing PC menu terminology.
        for filename in (
            "UI_jpn.gmd",
            "saveload_jpn.gmd",
            "system_jpn.gmd",
            "system_title_jpn.gmd",
            "title_jpn.gmd",
        ):
            document = parse_gmd_bytes((source / "msg" / filename).read_bytes())
            apply_layout_overrides(filename, document)
            if filename == "system_title_jpn.gmd":
                for entry in document["entries"]:
                    label = entry.get("label") or ""
                    suffix = label.removeprefix("DLC_M_CONTENT_")
                    if label == "DLC_M_CONTENT_00":
                        entry["text"] = "Special Episode"
                        entry["text_hex"] = ""
                    elif label.startswith("DLC_M_CONTENT_") and suffix.isdigit():
                        number = int(suffix)
                        entry["text"] = f"No.{number}"
                        entry["text_hex"] = ""
            (replacements_root / filename).write_bytes(build_gmd_bytes(document))
    else:
        system_title = replacements_root / "system_title_jpn.gmd"
        document = parse_gmd_bytes(system_title.read_bytes())
        entry = next(item for item in document["entries"] if item.get("label") == "DLC")
        entry["text"] = "<FONT 2><CNTR>DLC"
        entry["text_hex"] = ""
        system_title.write_bytes(build_gmd_bytes(document))
    archive = parse_arc(archive_path.read_bytes())
    replacements = {
        item.name: (replacements_root / Path(item.name).name).read_bytes()
        for item in archive["entries"]
        if (replacements_root / Path(item.name).name).is_file()
    }
    archive_path.write_bytes(build_arc_bytes(archive, replacements))


def rebuild_title_archive(japanese: Path, romfs: Path, work: Path) -> None:
    relative = Path("archive/title_jpn.arc")
    base = parse_arc((japanese / "romfs" / relative).read_bytes())
    archive_path = romfs / relative
    scarlet = parse_arc(archive_path.read_bytes())
    gui_name = "UI/4_menu/40_title/title_top.gui"
    texture_name = "UI/4_menu/40_title/tex/nocopy_GSM_NOMIP.tex"
    base_by_name = {item.name: item.data for item in base["entries"]}
    scarlet_by_name = {item.name: item.data for item in scarlet["entries"]}
    replacements = {
        gui_name: patch_gui(base_by_name[gui_name], scarlet_by_name[gui_name]),
        # Keep Capcom's original atlas instead of Scarlet Study's splash.
        texture_name: base_by_name[texture_name],
    }
    archive_path.write_bytes(build_arc_bytes(scarlet, replacements))


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
    else:
        # Resolve reuses Adventures' localized opening-movie table.  The PC
        # BB message directory does not contain a second copy, while the 3DS
        # release keeps a game-local container.
        destination = official / "romfs" / "msg" / "movie_subtitle_jpn.gmd"
        if not destination.exists():
            source = steam / "GO" / "msg" / "movie_subtitle_eng.gmd"
            japanese_path = japanese / "romfs" / "msg" / "movie_subtitle_jpn.gmd"
            japanese_document = parse_gmd_bytes(japanese_path.read_bytes())
            english_document = parse_gmd_bytes(source.read_bytes())
            if len(japanese_document["entries"]) != len(english_document["entries"]):
                raise ValueError("TGAA2 opening-movie table does not match Steam")
            for target, localized in zip(
                japanese_document["entries"], english_document["entries"]
            ):
                target["text"] = localized["text"]
                target["text_hex"] = ""
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(build_gmd_bytes(japanese_document))
    return official


def materialize_game(
    game: str,
    japanese: Path,
    scarlet: Path,
    steam: Path,
    work: Path,
    output: Path,
) -> None:
    game_code = "GO" if game == "tgaa1" else "BB"
    official = port_official(game, japanese, scarlet, steam, work)
    candidate = work / "candidate"
    shutil.copytree(scarlet / "romfs", candidate / "romfs")
    shutil.copytree(official / "romfs", candidate / "romfs", dirs_exist_ok=True)
    if game == "tgaa1":
        run(
            sys.executable,
            ROOT / "scripts/apply_tgaa1_3ds_wording.py",
            candidate / "romfs" / "script" / "_output",
        )
    font, dialogue_font = rebuild_font_archive(
        game_code, steam, candidate / "romfs", work
    )
    rebuild_message_archive(game, game_code, steam, candidate / "romfs", work)
    rebuild_title_archive(japanese, candidate / "romfs", work)
    component_source = work / "component-source"
    component_source.mkdir()
    shutil.copy2(scarlet / "exefs" / "code.bin", component_source / "code.bin")
    shutil.copy2(scarlet / "exefs" / "icon.bin", component_source / "icon.bin")
    shutil.copy2(scarlet / "exheader.bin", component_source / "exheader.bin")

    output.mkdir(parents=True)
    shutil.move(candidate / "romfs", output / "romfs")

    # Reapply the small executable changes by purpose instead of preserving
    # an opaque binary delta against Scarlet Study's code.bin.
    if game == "tgaa1":
        offline_code = work / "code-offline.bin"
        run(
            sys.executable,
            ROOT / "scripts/patch_tgaa1_dlc_offline.py",
            component_source / "code.bin",
            offline_code,
        )
        run(
            sys.executable,
            ROOT / "scripts/patch_tgaa1_code_version.py",
            offline_code,
            output / "code.bin",
            "--to-version",
            "ENG 2.8.5",
        )
        short_title = "The Great Ace Attorney"
        long_title = "The Great Ace Attorney: Adventures"
    else:
        run(
            sys.executable,
            ROOT / "scripts/patch_dlc_offline.py",
            component_source / "code.bin",
            output / "code.bin",
        )
        short_title = "The Great Ace Attorney 2"
        long_title = "The Great Ace Attorney 2: Resolve"
    run(
        sys.executable,
        ROOT / "scripts/patch_title_metadata.py",
        "smdh",
        component_source / "icon.bin",
        output / "icon.bin",
        "--short",
        short_title,
        "--long",
        long_title,
    )
    shutil.copy2(component_source / "exheader.bin", output / "exheader.bin")

    template = (ROOT / "config" / f"{game}-update.rsf.in").read_text()
    (output / "update.rsf").write_text(template.replace("@ROMFS@", str(output / "romfs")))

    shutil.copy2(font, output / "font.gfd")
    if game == "tgaa1":
        # TGAA1's normal dialogue uses font03.  font00 is deliberately wider
        # and is retained separately for the Court Record and its tutorial.
        shutil.copy2(dialogue_font, output / "dialogue-font.gfd")
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
