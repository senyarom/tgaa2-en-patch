import unittest

from dgs2tool.location_captions import compact_location_captions
from dgs2tool.pagination import dialogue_page_line_counts, paginate_dialogue_text, visible_text
from scripts.build_3ds_official_layout import (
    apply_interactive_tutorial_overrides,
    line_width,
    reflow_scenario_text,
)


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

    def test_can_skip_non_dialogue_three_line_widgets(self):
        source = (
            "<E800 1><E260 27 23><E025 2.5>First line\r\n"
            "second line\r\nthird line<E023><PAGE>"
        )
        result, reports = paginate_dialogue_text(
            source,
            skip_without_speaker=True,
        )
        self.assertEqual(result, source)
        self.assertEqual(reports, [])

    def test_reflows_width_then_paginates_to_two_lines(self):
        widths = {codepoint: 1 for codepoint in range(128)}
        source = (
            "<E800 1><E041 1 0><E025 2.5>alpha beta gamma\r\n"
            "delta epsilon zeta<E023><PAGE>"
        )
        reflowed, reports = reflow_scenario_text(
            source,
            widths,
            maximum=100,
            max_lines=3,
            dialogue_maximum=12,
        )
        result, pagination_reports = paginate_dialogue_text(
            reflowed,
            skip_without_speaker=True,
        )
        self.assertTrue(reports)
        self.assertTrue(pagination_reports)
        self.assertTrue(all(count <= 2 for count in dialogue_page_line_counts(result)))
        for page in result.split("<PAGE>"):
            for line in visible_text(page).splitlines():
                if line.strip():
                    self.assertLessEqual(line_width(line, widths), 12)

    def test_can_skip_special_layout_dialogue(self):
        source = (
            "<E800 1><E041 1 0><CNTR><SIZE 12>First line\r\n"
            "second line\r\nthird line</SIZE><E023><PAGE>"
        )
        result, reports = paginate_dialogue_text(
            source,
            skip_without_speaker=True,
            skip_tags=("<CNTR>", "<SIZE "),
        )
        self.assertEqual(result, source)
        self.assertEqual(reports, [])

    def test_preserves_interactive_tutorial_instruction_as_one_page(self):
        source = (
            "<E800 146><E041 21 14><E025 2.5>This is the list of evidence you've\r\n"
            "collected.<E358><E003 13> Now try switching\r\n"
            "to '<E014><E436><FONT 2>People<E437></FONT><E005>' instead with "
            "<E086 0 0><E683>.<E027><E800 147><E650 1><E800 148><E024><PAGE>"
        )
        result, reports = paginate_dialogue_text(source)
        self.assertEqual(result, source)
        self.assertEqual(reports, [])

        widths = {codepoint: 1 for codepoint in range(128)}
        reflowed, reflow_reports = reflow_scenario_text(
            source,
            widths,
            maximum=10,
            max_lines=3,
            dialogue_maximum=10,
        )
        self.assertEqual(reflowed, source)
        self.assertEqual(len(reflow_reports), 1)
        self.assertEqual(reflow_reports[0]["status"], "overflow")

    def test_does_not_treat_e027_without_e650_as_interactive_wait(self):
        source = (
            "<E800 1><E041 1 0><E025 2.5>First line\r\n"
            "second line\r\nthird line<E027><E023><PAGE>"
        )
        result, reports = paginate_dialogue_text(source)
        self.assertEqual(dialogue_page_line_counts(result), [2, 1])
        self.assertEqual(len(reports), 1)

    def test_shortens_tgaa1_interactive_tutorial_without_changing_tags(self):
        source = (
            "<E800 137><E041 1 0><E025 3.5><E007>"
            "(I just have to press <E005><E683><E007> for the "
            "<E014><E436><FONT 2>Court Record<E437></FONT><E007>?<E003 14>\r\n"
            "<E025 2.5>Alright, <E003 8><E341>there's no time to lose!)"
            "<E027><E650 0><E024><PAGE>"
            "<E041 21 14><E025 2.5>"
            "This is the list of evidence you've collected.<E358><E003 13>\r\n"
            "Now try switching to '<E014><E436><FONT 2>People<E437></FONT><E005>' "
            "instead with <E086 0 0><E683>.<E027><E650 1><E024><PAGE>"
            "<E041 21 14><E025 2.5>"
            "You'll find details about the victim in here.<E358><E003 13>\r\n"
            "When you're done,<E358><E003 6> just press <E684> to go "
            "<E014><E436><FONT 2>back<E437></FONT><E005>."
            "<E027><E650 2><E024><PAGE>"
        )
        result = apply_interactive_tutorial_overrides(
            "_sce00_c001_0002_jpn.gmd",
            "L_FLASH_END_00_00",
            source,
        )
        self.assertIn("Here's your evidence.", result)
        self.assertIn("The victim's details are here.", result)
        self.assertEqual(result.count("<E027>"), 3)
        self.assertEqual(result.count("<E650 "), 3)


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
