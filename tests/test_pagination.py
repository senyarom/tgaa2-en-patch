import unittest

from dgs2tool.location_captions import compact_location_captions
from dgs2tool.pagination import dialogue_page_line_counts, paginate_dialogue_text, visible_text


class PaginationTests(unittest.TestCase):
    def test_splits_three_line_dialogue_and_is_idempotent(self):
        source = (
            "\r\n<E800 261><E041 27 23><E025 2.5>The only way to fight an enemy\r\n"
            "who's using underhand tactics<E169 27 0><E003 12>\r\n"
            "<E169 27 3><E025 1.5><E331>is with a tit-for-tat strategy!<E023><PAGE>"
        )
        result, reports = paginate_dialogue_text(source)
        self.assertEqual(visible_text(result), visible_text(source))
        self.assertEqual(dialogue_page_line_counts(result), [2, 1])
        self.assertEqual(len(reports), 1)
        self.assertIn("<E023><PAGE>\r\n<E041 27 23>", result)
        rerun, rerun_reports = paginate_dialogue_text(result)
        self.assertEqual(rerun, result)
        self.assertEqual(rerun_reports, [])

    def test_prefers_a_sentence_boundary(self):
        source = (
            "<E800 1><E041 1 0><E025 2.5>That settles it.\r\n"
            "Now we can finally go\r\nback home together.<E023><PAGE>"
        )
        result, reports = paginate_dialogue_text(source)
        self.assertEqual(dialogue_page_line_counts(result), [1, 2])
        self.assertEqual(reports[0]["split_after_line"], 1)

    def test_does_not_split_an_emphasis_pair_when_another_boundary_exists(self):
        source = (
            "<E800 1><E041 1 0><E025 2.5>Think carefully.\r\n"
            "Now <E006>squeeze\r\nevery penny<E005> from them!<E023><PAGE>"
        )
        result, reports = paginate_dialogue_text(source)
        self.assertEqual(dialogue_page_line_counts(result), [1, 2])
        self.assertEqual(reports[0]["split_after_line"], 1)

    def test_preserves_a_final_e024(self):
        source = (
            "<E800 1><E041 1 0><E025 2.5>First line\r\n"
            "second line\r\nthird line<E024><PAGE>"
        )
        result, _reports = paginate_dialogue_text(source)
        self.assertTrue(result.endswith("third line<E024><PAGE>"))
        self.assertEqual(dialogue_page_line_counts(result), [2, 1])


class LocationCaptionTests(unittest.TestCase):
    def setUp(self):
        self.widths = {codepoint: 1 for codepoint in range(128)}

    def test_compacts_standard_caption(self):
        source = (
            "<CNTR><E008><E025 7.5><E003 10>22nd November, 3:08 p.m.\r\n"
            "<CNTR><E003 5>Supreme Court of Judicature, Defendants' Antechamber 5"
            "<E023><PAGE>"
        )
        result, reports = compact_location_captions(source, self.widths, 42)
        self.assertIn("Supreme Court, Defendants' Antechamber 5", result)
        self.assertNotIn("of Judicature", result)
        self.assertEqual(reports[0]["status"], "reflowed")
        self.assertLessEqual(reports[0]["new_widths"][0], 42)

    def test_compacts_special_issue_caption(self):
        source = (
            "<CNTR><E008><E025 8><E003 10><E042><CNTR><E008>"
            "9th July, 9:00 a.m.\r\n"
            "Supreme Court of Judicature, Courtroom No. 2"
            "<CNTR><E003 5><E042><CNTR><E023><PAGE>"
        )
        result, reports = compact_location_captions(source, self.widths, 42)
        self.assertIn("Supreme Court, Courtroom No. 2", result)
        self.assertEqual(reports[0]["status"], "reflowed")

    def test_reports_unknown_overflow_without_changing_it(self):
        location = "An Unknown Location Name That Is Far Too Long"
        source = (
            "<CNTR><E008><E025 7.5><E003 10>Today\r\n"
            f"<CNTR><E003 5>{location}<E023>"
        )
        result, reports = compact_location_captions(source, self.widths, 20)
        self.assertEqual(result, source)
        self.assertEqual(reports[0]["status"], "overflow")


if __name__ == "__main__":
    unittest.main()
