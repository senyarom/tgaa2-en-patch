import unittest

from dgs2tool.titlemeta import (
    SMDH_SIZE,
    patch_dgs2_aoc_labels,
    patch_smdh_titles,
)


class TitleMetadataTests(unittest.TestCase):
    def test_smdh_patch_replaces_all_languages_and_preserves_artwork(self):
        source = bytearray(SMDH_SIZE)
        source[:4] = b"SMDH"
        source[0x2008:] = bytes((index % 251 for index in range(SMDH_SIZE - 0x2008)))

        result = patch_smdh_titles(
            bytes(source),
            short_description="The Great Ace Attorney 2",
            long_description="The Great Ace Attorney 2\n- Resolve -",
            publisher="CAPCOM",
        )

        expected_short = "The Great Ace Attorney 2".encode("utf-16le")
        for language in range(16):
            offset = 0x8 + language * 0x200
            self.assertEqual(result[offset : offset + len(expected_short)], expected_short)
        self.assertEqual(result[0x2008:], source[0x2008:])

    def test_dgs2_aoc_patch_replaces_both_catalogue_entries(self):
        source = bytearray(0x260)
        for offset, size, value in (
            (0x0D0, 0x40, "大逆転裁判２衣装"),
            (0x110, 0x80, "大逆転裁判２衣装"),
            (0x198, 0x40, "大逆転裁判２追加シナリオ"),
            (0x1D8, 0x80, "大逆転裁判２追加シナリオ"),
        ):
            encoded = value.encode("utf-8")
            source[offset : offset + size] = encoded + bytes(size - len(encoded))

        result = patch_dgs2_aoc_labels(bytes(source))

        self.assertIn(b"Costume Pack", result)
        self.assertIn(b"Additional Episodes", result)
        self.assertNotIn("大逆転裁判".encode("utf-8"), result)


if __name__ == "__main__":
    unittest.main()
