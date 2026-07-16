import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from dgs2tool.arc import build_arc_bytes, extract_arc, parse_arc, rebuild_arc


def make_arc(payload: bytes, compressed: bool) -> bytes:
    stored = zlib.compress(payload) if compressed else payload
    file_offset = 0x100
    archive = bytearray(file_offset + len(stored))
    archive[:8] = struct.pack("<4shh", b"ARC\0", 7, 1)
    name = b"script/test".ljust(0x40, b"\0")
    archive[8 : 8 + 0x50] = struct.pack(
        "<64sIiii", name, 0xA42BB29A, len(stored), len(payload), file_offset
    )
    archive[file_offset:] = stored
    return bytes(archive)


class ArcTests(unittest.TestCase):
    def test_uncompressed(self):
        archive = parse_arc(make_arc(b"GMD\0data", False))
        self.assertEqual(archive["entries"][0].name, "script/test.gmd")
        self.assertEqual(archive["entries"][0].data, b"GMD\0data")

    def test_compressed_extract(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "test.arc"
            source.write_bytes(make_arc(b"GMD\0compressed", True))
            report = extract_arc(source, root / "out", only_gmd=True)
            self.assertEqual(report["extracted_count"], 1)
            self.assertEqual((root / "out" / "script" / "test.gmd").read_bytes(), b"GMD\0compressed")

    def test_rebuild_without_changes_is_identical(self):
        original = make_arc(b"GMD\0unchanged", True)
        rebuilt = build_arc_bytes(parse_arc(original))
        self.assertEqual(rebuilt, original)

    def test_rebuild_with_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "test.arc"
            source.write_bytes(make_arc(b"GMD\0original", True))
            replacement = root / "replacement" / "script" / "test.gmd"
            replacement.parent.mkdir(parents=True)
            replacement.write_bytes(b"GMD\0official English")

            report = rebuild_arc(source, root / "replacement", root / "rebuilt.arc")
            rebuilt = parse_arc((root / "rebuilt.arc").read_bytes())
            self.assertEqual(report["replaced_count"], 1)
            self.assertEqual(rebuilt["entries"][0].data, b"GMD\0official English")


if __name__ == "__main__":
    unittest.main()
