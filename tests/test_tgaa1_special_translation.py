import json
import re
import unittest
from pathlib import Path

from scripts.apply_tgaa1_special_translation import replace_visible


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "translation" / "tgaa1-special-en.json"
JP_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uff01-\uff60]")


class Tgaa1SpecialTranslationTests(unittest.TestCase):
    def test_complete_source_controlled_ledger(self):
        translations = json.loads(LEDGER.read_text(encoding="utf-8"))
        self.assertEqual(
            {label: len(segments) for label, segments in translations.items()},
            {
                "L_START": 20,
                "L_EVENT_1": 23,
                "L_EVENT_2": 39,
                "L_EVENT_3": 38,
                "L_EVENT_4": 41,
                "L_EVENT_5": 18,
            },
        )
        self.assertEqual(sum(map(len, translations.values())), 179)
        for segments in translations.values():
            for segment in segments:
                self.assertTrue(segment.strip())
                self.assertNotRegex(segment, JP_RE)
                self.assertNotIn("<", segment)

    def test_ledger_text_can_replace_visible_japanese_without_touching_tags(self):
        translation = json.loads(LEDGER.read_text(encoding="utf-8"))["L_EVENT_1"][0]
        source = "<E800 1><E041 2 3>日本語<E003 4><E023><PAGE>"
        self.assertEqual(
            replace_visible(source, translation),
            f"<E800 1><E041 2 3>{translation}<E003 4><E023><PAGE>",
        )


if __name__ == "__main__":
    unittest.main()
