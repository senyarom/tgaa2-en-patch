import unittest

from scripts.build_3ds_official_layout import (
    OPENING_MOVIE_MAXIMUM_LINES,
    OPENING_MOVIE_MAXIMUM_WIDTH,
    line_width,
    reflow_opening_movie_caption,
)
from scripts.prepare_hook_romfs import validate_movie_document


class OpeningMovieLayoutTests(unittest.TestCase):
    def setUp(self):
        # Representative advances from TGAA1's adapted proportional font.  A
        # fixed eight-pixel test advance makes the expected fit deterministic.
        self.widths = {codepoint: 8 for codepoint in range(0x20, 0x7F)}

    def test_reflows_case_four_caption_inside_lower_screen(self):
        source = (
            "Indeed, that there may be another part to\r\n"
            "this story that we are yet to discover.'"
        )

        result, reports = reflow_opening_movie_caption(source, self.widths)

        lines = result.split("\r\n")
        self.assertGreater(len(lines), 2)
        self.assertLessEqual(len(lines), OPENING_MOVIE_MAXIMUM_LINES)
        self.assertTrue(reports)
        self.assertTrue(
            all(
                line_width(line, self.widths) <= OPENING_MOVIE_MAXIMUM_WIDTH
                for line in lines
            )
        )
        self.assertEqual(
            "".join(result.split()),
            "".join(source.split()),
        )

    def test_build_guard_rejects_wide_movie_text(self):
        document = {
            "entries": [
                {"label": "wide", "text": "This line is deliberately much too wide for the movie caption."},
            ]
        }
        with self.assertRaisesRegex(RuntimeError, "movie text overflow.*wide"):
            validate_movie_document(document, "fixture", self.widths)


if __name__ == "__main__":
    unittest.main()
