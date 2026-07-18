import struct
import unittest
import zlib

from dgs2tool.bps import apply_bps, create_bps, inspect_bps


def encode_number(value: int) -> bytes:
    output = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value == 0:
            output.append(byte | 0x80)
            return bytes(output)
        output.append(byte)
        value -= 1


def literal_patch(source: bytes, target: bytes) -> bytes:
    patch = bytearray(b"BPS1")
    patch += encode_number(len(source))
    patch += encode_number(len(target))
    patch += encode_number(0)
    patch += encode_number(((len(target) - 1) << 2) | 1)
    patch += target
    patch += struct.pack("<I", zlib.crc32(source) & 0xFFFFFFFF)
    patch += struct.pack("<I", zlib.crc32(target) & 0xFFFFFFFF)
    patch += struct.pack("<I", zlib.crc32(patch) & 0xFFFFFFFF)
    return bytes(patch)


class BpsTests(unittest.TestCase):
    def test_created_patch_round_trips_mixed_runs(self):
        source = b"same-OLD-same-tail"
        target = b"same-NEW-same-longer-tail!"
        patch = create_bps(source, target, b"test")
        self.assertEqual(apply_bps(source, patch), target)
        report = inspect_bps(patch)
        self.assertTrue(report["patch_crc_valid"])
        self.assertEqual(report["metadata"], "test")

    def test_literal_patch(self):
        source = b"abc"
        target = b"translated"
        patch = literal_patch(source, target)
        self.assertEqual(apply_bps(source, patch), target)
        info = inspect_bps(patch)
        self.assertTrue(info["patch_crc_valid"])
        self.assertEqual(info["target_size"], len(target))
        self.assertEqual(info["actions"]["target_read"], 1)


if __name__ == "__main__":
    unittest.main()
