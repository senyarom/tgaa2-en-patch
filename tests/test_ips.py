import unittest

from dgs2tool.ips import apply_ips, create_ips


class IpsTests(unittest.TestCase):
    def test_create_and_apply(self):
        source = bytearray(b"unchanged-" * 20)
        target = bytearray(source)
        target[3:8] = b"HELLO"
        target[80:86] = b"WORLD!"
        patch = create_ips(bytes(source), bytes(target))
        self.assertTrue(patch.startswith(b"PATCH"))
        self.assertTrue(patch.endswith(b"EOF"))
        self.assertEqual(apply_ips(bytes(source), patch), bytes(target))

    def test_rle_apply(self):
        patch = b"PATCH" + (2).to_bytes(3, "big") + b"\0\0\0\x04Z" + b"EOF"
        self.assertEqual(apply_ips(b"abcdefgh", patch), b"abZZZZgh")


if __name__ == "__main__":
    unittest.main()
