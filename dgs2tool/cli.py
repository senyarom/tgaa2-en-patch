from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from .align import apply_alignment, make_alignment
from .arc import extract_arc, parse_arc, rebuild_arc
from .batch import (
    dump_gmd_tree,
    port_official_gmd_tree,
    port_official_message_tree,
    stage_layeredfs,
)
from .bps import apply_bps, inspect_bps
from .firm import extract_firm
from .gmd import build_gmd, build_gmd_bytes, dump_gmd, parse_gmd_bytes, semantic_signature
from .ips import apply_ips, create_ips
from .manifest import check_romfs, parse_autorun_file, save_manifest


def _write_json(data: dict, path: Path | None) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if path is None:
        print(text, end="")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dgs2tool")
    sub = parser.add_subparsers(dest="command", required=True)

    command = sub.add_parser("firm-extract", help="extract the embedded ustar files from a FIRM")
    command.add_argument("firm", type=Path)
    command.add_argument("output", type=Path)

    command = sub.add_parser("manifest", help="parse a DGS2 autorun.gm9 build manifest")
    command.add_argument("autorun", type=Path)
    command.add_argument("-o", "--output", type=Path)

    command = sub.add_parser("check-romfs", help="check an extracted RomFS against a manifest")
    command.add_argument("manifest", type=Path)
    command.add_argument("root", type=Path)
    command.add_argument("-o", "--output", type=Path)

    command = sub.add_parser("bps-info", help="inspect and checksum a BPS1 patch")
    command.add_argument("patch", type=Path)

    command = sub.add_parser("bps-apply", help="apply a BPS1 patch")
    command.add_argument("source", type=Path)
    command.add_argument("patch", type=Path)
    command.add_argument("output", type=Path)

    command = sub.add_parser("ips-create", help="create an IPS patch from equal-length files")
    command.add_argument("source", type=Path)
    command.add_argument("target", type=Path)
    command.add_argument("output", type=Path)

    command = sub.add_parser("ips-apply", help="apply an IPS patch")
    command.add_argument("source", type=Path)
    command.add_argument("patch", type=Path)
    command.add_argument("output", type=Path)

    command = sub.add_parser("arc-list", help="list files in an MT Framework ARC")
    command.add_argument("input", type=Path)

    command = sub.add_parser("arc-extract", help="extract an MT Framework ARC")
    command.add_argument("input", type=Path)
    command.add_argument("output", type=Path)
    command.add_argument("--only-gmd", action="store_true")

    command = sub.add_parser(
        "arc-rebuild",
        help="rebuild an MT Framework ARC with replacement files from a directory tree",
    )
    command.add_argument("input", type=Path)
    command.add_argument("replacements_root", type=Path)
    command.add_argument("output", type=Path)

    command = sub.add_parser("gmd-dump", help="export a GMD file to editable JSON")
    command.add_argument("input", type=Path)
    command.add_argument("output", type=Path)

    command = sub.add_parser("gmd-build", help="rebuild a GMD file from JSON")
    command.add_argument("input", type=Path)
    command.add_argument("output", type=Path)

    command = sub.add_parser("gmd-dump-tree", help="export every GMD below a directory")
    command.add_argument("root", type=Path)
    command.add_argument("output", type=Path)

    command = sub.add_parser(
        "port-official-tree",
        help="port official PC English text into Japanese 3DS GMD containers",
    )
    command.add_argument("japanese_root", type=Path)
    command.add_argument("english_root", type=Path)
    command.add_argument("output_root", type=Path)
    command.add_argument("--scenes", nargs="+", default=["00", "01", "02", "03", "04"])
    command.add_argument("--no-macros", action="store_true")
    command.add_argument("-o", "--report", type=Path)

    command = sub.add_parser(
        "port-official-messages",
        help="port official PC message GMDs into Japanese 3DS containers",
    )
    command.add_argument("japanese_root", type=Path)
    command.add_argument("english_root", type=Path)
    command.add_argument("output_root", type=Path)
    command.add_argument("-o", "--report", type=Path)

    command = sub.add_parser("stage-layeredfs", help="stage modified RomFS files for Luma3DS testing")
    command.add_argument("source", type=Path)
    command.add_argument("sd_root", type=Path)
    command.add_argument("--title-id", default="00040000001AE200")

    command = sub.add_parser("gmd-check", help="perform a semantic GMD round-trip check")
    command.add_argument("input", type=Path)

    command = sub.add_parser("align", help="align a Japanese GMD JSON with an English GMD JSON")
    command.add_argument("japanese", type=Path)
    command.add_argument("english", type=Path)
    command.add_argument("output", type=Path)
    command.add_argument("--glossary", type=Path)

    command = sub.add_parser("apply-alignment", help="apply candidate strings to a GMD JSON")
    command.add_argument("source", type=Path)
    command.add_argument("alignment", type=Path)
    command.add_argument("output", type=Path)
    command.add_argument("--reviewed-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "firm-extract":
        entries = extract_firm(args.firm, args.output)
        _write_json(
            {
                "entries": [
                    {
                        "name": entry.name,
                        "size": entry.size,
                        "header_offset": entry.header_offset,
                        "sha256": hashlib.sha256(entry.data).hexdigest(),
                    }
                    for entry in entries
                ]
            },
            None,
        )
        return 0

    if args.command == "manifest":
        manifest = parse_autorun_file(args.autorun)
        if args.output:
            save_manifest(manifest, args.output)
        else:
            _write_json(manifest, None)
        return 0

    if args.command == "check-romfs":
        report = check_romfs(_load_json(args.manifest), args.root)
        _write_json(report, args.output)
        return 2 if report["missing_count"] else 0

    if args.command == "bps-info":
        _write_json(inspect_bps(args.patch.read_bytes()), None)
        return 0

    if args.command == "bps-apply":
        output = apply_bps(args.source.read_bytes(), args.patch.read_bytes())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(output)
        print(f"wrote {len(output)} bytes to {args.output}")
        return 0

    if args.command == "ips-create":
        patch = create_ips(args.source.read_bytes(), args.target.read_bytes())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(patch)
        print(f"wrote {len(patch)} bytes to {args.output}")
        return 0

    if args.command == "ips-apply":
        output = apply_ips(args.source.read_bytes(), args.patch.read_bytes())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(output)
        print(f"wrote {len(output)} bytes to {args.output}")
        return 0

    if args.command == "arc-list":
        archive = parse_arc(args.input.read_bytes())
        _write_json(
            {
                "version": archive["version"],
                "endian": archive["endian"],
                "extended_names": archive["extended_names"],
                "entries": [
                    {
                        "index": entry.index,
                        "name": entry.name,
                        "compressed_size": entry.compressed_size,
                        "decompressed_size": entry.decompressed_size,
                        "compressed": entry.compressed,
                        "extension_hash": f"{entry.extension_hash:08x}",
                    }
                    for entry in archive["entries"]
                ],
            },
            None,
        )
        return 0

    if args.command == "arc-extract":
        _write_json(extract_arc(args.input, args.output, only_gmd=args.only_gmd), None)
        return 0

    if args.command == "arc-rebuild":
        _write_json(rebuild_arc(args.input, args.replacements_root, args.output), None)
        return 0

    if args.command == "gmd-dump":
        document = dump_gmd(args.input, args.output)
        print(f"exported {len(document['entries'])} entries to {args.output}")
        return 0

    if args.command == "gmd-build":
        blob = build_gmd(args.input, args.output)
        print(f"wrote {len(blob)} bytes to {args.output}")
        return 0

    if args.command == "gmd-dump-tree":
        report = dump_gmd_tree(args.root, args.output)
        _write_json(report, None)
        return 0

    if args.command == "port-official-tree":
        report = port_official_gmd_tree(
            args.japanese_root,
            args.english_root,
            args.output_root,
            tuple(args.scenes),
            not args.no_macros,
        )
        if args.report:
            _write_json(report, args.report)
            _write_json(
                {
                    "selected_files": report["selected_files"],
                    "written_files": report["written_files"],
                    "written_entries": report["written_entries"],
                    "counts": report["counts"],
                    "report": str(args.report),
                },
                None,
            )
        else:
            _write_json(report, None)
        unresolved = report["selected_files"] - report["written_files"]
        return 4 if unresolved else 0

    if args.command == "port-official-messages":
        report = port_official_message_tree(args.japanese_root, args.english_root, args.output_root)
        if args.report:
            _write_json(report, args.report)
            _write_json(
                {
                    "selected_files": report["selected_files"],
                    "written_files": report["written_files"],
                    "written_entries": report["written_entries"],
                    "counts": report["counts"],
                    "report": str(args.report),
                },
                None,
            )
        else:
            _write_json(report, None)
        return 4 if report["selected_files"] != report["written_files"] else 0

    if args.command == "stage-layeredfs":
        report = stage_layeredfs(args.source, args.sd_root, args.title_id)
        _write_json(report, None)
        return 0

    if args.command == "gmd-check":
        original_blob = args.input.read_bytes()
        original = parse_gmd_bytes(original_blob)
        rebuilt_blob = build_gmd_bytes(original)
        rebuilt = parse_gmd_bytes(rebuilt_blob)
        result = {
            "byte_identical": original_blob == rebuilt_blob,
            "semantic_identical": semantic_signature(original) == semantic_signature(rebuilt),
            "original_size": len(original_blob),
            "rebuilt_size": len(rebuilt_blob),
            "entries": len(original["entries"]),
        }
        _write_json(result, None)
        return 0 if result["semantic_identical"] else 3

    if args.command == "align":
        glossary = _load_json(args.glossary) if args.glossary else {}
        alignment = make_alignment(_load_json(args.japanese), _load_json(args.english), glossary)
        _write_json(alignment, args.output)
        print(json.dumps(alignment["summary"], ensure_ascii=False))
        return 0

    if args.command == "apply-alignment":
        result = apply_alignment(
            _load_json(args.source), _load_json(args.alignment), reviewed_only=args.reviewed_only
        )
        _write_json(result, args.output)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
