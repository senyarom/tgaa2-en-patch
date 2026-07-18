import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_3ds_official_layout import (
    line_width,
    load_court_record_overrides,
    normalize_court_record_wording,
    reflow_court_record_caption,
    visible,
)


class CourtRecordLayoutTests(unittest.TestCase):
    def setUp(self):
        self.widths = {codepoint: 1 for codepoint in range(128)}

    def test_reports_overflow_instead_of_adding_ignored_size_tag(self):
        source = (
            "aaaa aaaa aaaa\r\n"
            "aaaa aaaa aaaa\r\n"
            "aaaa aaaa aaaa\r\n"
            "aaaa aaaa aaaa"
        )
        result, reports = reflow_court_record_caption(
            source,
            self.widths,
            physical_maximum=10,
        )
        self.assertEqual(result, source)
        self.assertEqual(reports[0]["status"], "overflow")
        self.assertNotIn("<SIZE ", result)

    def test_keeps_normal_size_when_reflow_is_enough(self):
        source = "alpha beta gamma delta"
        result, reports = reflow_court_record_caption(
            source,
            self.widths,
            physical_maximum=11,
        )
        self.assertNotIn("<SIZE ", result)
        self.assertTrue(
            all(
                line_width(line, self.widths) <= 11
                for line in visible(result).splitlines()
            )
        )

    def test_is_idempotent(self):
        source = "alpha beta gamma delta"
        first, _reports = reflow_court_record_caption(
            source,
            self.widths,
            physical_maximum=11,
        )
        second, reports = reflow_court_record_caption(
            first,
            self.widths,
            physical_maximum=11,
        )
        self.assertEqual(second, first)
        self.assertEqual(reports, [])

    def test_loads_wording_override_independently_of_line_breaks(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "overrides.jsonl"
            path.write_text(
                '{"file":"evidence_caption_jpn.gmd","label":"item1",'
                '"source":"alpha\\r\\nbeta","text":"short text"}\n'
            )
            overrides = load_court_record_overrides(path)
        key = (
            "evidence_caption_jpn.gmd",
            "item1",
            normalize_court_record_wording("alpha beta"),
        )
        self.assertEqual(overrides[key], "short text")


if __name__ == "__main__":
    unittest.main()
