import unittest

from scripts.patch_tgaa1_3ds_ui import apply_layout_overrides


class Tgaa1UiLayoutTests(unittest.TestCase):
    def test_shrinks_court_record_tab_only(self):
        document = {
            "entries": [
                {
                    "label": "PANEL_TR_0",
                    "text": "<FONT 0><SIZE 16><CNTR>Court Record",
                    "text_hex": "old",
                },
                {
                    "label": "PANEL_TR_1",
                    "text": "<FONT 0><SIZE 16><CNTR>Present",
                    "text_hex": "untouched",
                },
            ]
        }

        changed = apply_layout_overrides("UI_jpn.gmd", document)

        self.assertEqual(changed, ["PANEL_TR_0"])
        self.assertEqual(
            document["entries"][0]["text"],
            "<FONT 0><SIZE 13><CNTR>Court Record",
        )
        self.assertEqual(document["entries"][0]["text_hex"], "")
        self.assertEqual(document["entries"][1]["text_hex"], "untouched")

    def test_rejects_an_unexpected_source_string(self):
        document = {
            "entries": [
                {"label": "PANEL_TR_0", "text": "Unexpected text"},
            ]
        }

        with self.assertRaisesRegex(ValueError, "unexpected UI layout text"):
            apply_layout_overrides("UI_jpn.gmd", document)


if __name__ == "__main__":
    unittest.main()
