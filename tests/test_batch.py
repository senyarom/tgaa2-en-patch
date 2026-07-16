import tempfile
import unittest
from pathlib import Path

from dgs2tool.batch import (
    _adapt_pc_control_icons,
    dump_gmd_tree,
    port_official_gmd_tree,
    port_official_message_tree,
    stage_layeredfs,
)
from dgs2tool.gmd import VERSION_V2, build_gmd_bytes, parse_gmd_bytes


def sample_gmd() -> bytes:
    return build_gmd_bytes(
        {
            "format": "gmd",
            "metadata": {
                "endian": "little",
                "version": VERSION_V2,
                "language": 0,
                "unknown": 0,
                "name": "tree",
                "platform": "default",
                "xor_keypair": -1,
                "label_obscure": 0,
                "mobile_padding": 0,
            },
            "entries": [{"index": 0, "label": "A", "text": "Line", "text_hex": ""}],
        }
    )


def labelled_gmd(name: str, platform: str, language: int, keypair: int, entries: list[tuple[str, str]]) -> bytes:
    return build_gmd_bytes(
        {
            "schema": 1,
            "format": "gmd",
            "metadata": {
                "endian": "little",
                "version": VERSION_V2,
                "language": language,
                "unknown": 0,
                "name": name,
                "platform": platform,
                "xor_keypair": keypair,
                "label_obscure": 0,
                "mobile_padding": 0,
            },
            "entries": [
                {"index": index, "label": label, "text": text, "text_hex": ""}
                for index, (label, text) in enumerate(entries)
            ],
        }
    )


class BatchTests(unittest.TestCase):
    def test_pc_control_icons_are_adapted_to_3ds_wording(self):
        text = (
            "use <E687><ICON PIPE_PAD_BLANK> to open; "
            "rotate with <E705><ICON PIPE_PAD_BLANK><E003 2><E086 0 0>"
            "<E696><ICON PIPE_PAD_BLANK><E003 2><E086 0 0>"
            "<E706><ICON PIPE_PAD_BLANK><E003 2><E086 0 0>"
            "<E704><ICON PIPE_PAD_BLANK>; "
            "move with <E698><ICON PIPE_PAD_BLANK><E003 2><E086 0 1>"
            "<E710><ICON PIPE_PAD_BLANK>"
        )
        adapted, report = _adapt_pc_control_icons(text)
        self.assertEqual(
            adapted,
            "use the touch screen to open; rotate with the touch-screen dials; "
            "move with the touch screen",
        )
        self.assertEqual(
            report,
            {"touch screen": 1, "touch-screen dials": 1, "juror touch screen": 1},
        )

    def test_dump_and_stage(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source" / "romfs" / "script"
            source.mkdir(parents=True)
            (source / "test.gmd").write_bytes(sample_gmd())

            report = dump_gmd_tree(root / "source" / "romfs", root / "json")
            self.assertEqual(report["count"], 1)
            self.assertTrue((root / "json" / "script" / "test.gmd.json").is_file())

            staged = stage_layeredfs(root / "source", root / "sd")
            self.assertEqual(staged["file_count"], 1)
            self.assertTrue(
                (root / "sd" / "luma" / "titles" / "00040000001AE200" / "romfs" / "script" / "test.gmd").is_file()
            )

    def test_port_official_tree_keeps_3ds_container_and_copies_text_by_label(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            japanese = root / "japanese"
            english = root / "english"
            japanese.mkdir()
            english.mkdir()
            (japanese / "_sce03_test_jpn.gmd").write_bytes(
                labelled_gmd(
                    "japanese",
                    "default",
                    0,
                    1,
                    [
                        ("A", "<RDFG 1><E800 10><E041 1 0><E025 4>日本語A<E800 11><E003 5><E023><PAGE><E800 12><E004 1><E001>"),
                        ("B", "<RDFG 2><E800 20><E041 1 0><E025 4>日本語B<E023><PAGE><E800 21><E004 1><E001>"),
                    ],
                )
            )
            # Reversed order proves that transfer is by label, not by index.
            (english / "_sce03_test_eng.gmd").write_bytes(
                labelled_gmd(
                    "english",
                    "mobile",
                    1,
                    -1,
                    [
                        ("B", "<RDFG 2><E800 120><E041 1 0><E025 2>Official ‘B’<E566><E023><PAGE><E800 121><E004 1><E001>"),
                        ("A", "<RDFG 1><E800 110><E041 1 0><E025 2>Official A<E800 111><E003 7><E023><PAGE><E800 112><E004 1><E001>"),
                        ("PC", "Extra"),
                    ],
                )
            )
            (japanese / "_sce04_missing_jpn.gmd").write_bytes(
                labelled_gmd("missing", "default", 0, 1, [("A", "日本語")])
            )

            report = port_official_gmd_tree(japanese, english, root / "ported")
            self.assertEqual(report["selected_files"], 2)
            self.assertEqual(report["written_files"], 1)
            self.assertEqual(report["written_entries"], 2)
            self.assertEqual(report["counts"]["official_superset"], 1)
            self.assertEqual(report["counts"]["missing_official_english"], 1)
            self.assertTrue(report["official_text_integrity_verified"])
            self.assertTrue(report["3ds_event_blocks_verified"])
            self.assertEqual(report["removed_pc_commands"], {"E566": 1})
            self.assertEqual(
                report["3ds_layout_adaptations"],
                {"E025 Latin half-step": 2, "typography U+2018": 1, "typography U+2019": 1},
            )

            output = parse_gmd_bytes(
                (root / "ported" / "romfs" / "script" / "_output" / "_sce03_test_jpn.gmd").read_bytes()
            )
            self.assertEqual(output["metadata"]["platform"], "default")
            self.assertEqual(output["metadata"]["language"], 0)
            self.assertEqual(output["metadata"]["xor_keypair"], 1)
            by_label = {entry["label"]: entry["text"] for entry in output["entries"]}
            self.assertIn("<E800 10><E041 1 0><E025 2.5>Official A<E800 11><E003 5>", by_label["A"])
            self.assertIn("<E800 20><E041 1 0><E025 2.5>Official 'B'<E023>", by_label["B"])
            self.assertNotIn("E566", by_label["B"])

    def test_port_messages_falls_back_to_index_for_unlabelled_3ds_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            japanese = root / "japanese"
            english = root / "english"
            japanese.mkdir()
            english.mkdir()
            (japanese / "help_jpn.gmd").write_bytes(
                labelled_gmd("help", "default", 0, 1, [("FIRST", "一"), (None, "二")])
            )
            (english / "help_eng.gmd").write_bytes(
                labelled_gmd(
                    "help",
                    "mobile",
                    1,
                    -1,
                    [("FIRST", "<E025 2>‘One’"), ("SECOND", "Two")],
                )
            )
            report = port_official_message_tree(japanese, english, root / "ported")
            self.assertEqual(report["written_files"], 1)
            self.assertEqual(report["files"][0]["match_mode"], "index")
            output = parse_gmd_bytes((root / "ported" / "romfs" / "msg" / "help_jpn.gmd").read_bytes())
            self.assertEqual(
                [entry["text"] for entry in output["entries"]],
                ["<E025 2.5>'One'", "Two"],
            )

    def test_port_messages_partially_matches_platform_specific_table(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            japanese = root / "japanese"
            english = root / "english"
            japanese.mkdir()
            english.mkdir()
            (japanese / "ui_jpn.gmd").write_bytes(
                labelled_gmd(
                    "ui",
                    "default",
                    0,
                    1,
                    [("PAD_A", "Aボタン"), ("MOVE", "移動"), ("PRESENT", "つきつける")],
                )
            )
            (english / "ui_eng.gmd").write_bytes(
                labelled_gmd("ui", "mobile", 1, -1, [("MOVE", "Move"), ("PRESENT", "Present")])
            )
            report = port_official_message_tree(japanese, english, root / "ported")
            self.assertEqual(report["written_entries"], 2)
            self.assertEqual(report["files"][0]["match_mode"], "partial_label")
            self.assertEqual(report["files"][0]["preserved_entries"], 1)
            output = parse_gmd_bytes((root / "ported" / "romfs" / "msg" / "ui_jpn.gmd").read_bytes())
            self.assertEqual([entry["text"] for entry in output["entries"]], ["Aボタン", "Move", "Present"])


if __name__ == "__main__":
    unittest.main()
