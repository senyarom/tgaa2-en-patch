import unittest

from dgs2tool.gmd import VERSION_V1, VERSION_V2, build_gmd_bytes, parse_gmd_bytes, semantic_signature


def document(version: int, platform: str = "default", keypair: int = -1) -> dict:
    return {
        "schema": 1,
        "format": "gmd",
        "metadata": {
            "endian": "little",
            "version": version,
            "language": 0,
            "unknown": 0,
            "name": "test",
            "platform": platform,
            "xor_keypair": keypair,
            "label_obscure": 32,
            "mobile_padding": 0,
        },
        "entries": [
            {"index": 0, "label": "START", "text": "Japanese/English", "text_hex": ""},
            {"index": 1, "label": None, "text": "Second line", "text_hex": ""},
        ],
    }


class GmdTests(unittest.TestCase):
    def assert_roundtrip(self, source: dict):
        first = build_gmd_bytes(source)
        parsed = parse_gmd_bytes(first)
        second = build_gmd_bytes(parsed)
        reparsed = parse_gmd_bytes(second)
        self.assertEqual(semantic_signature(parsed), semantic_signature(reparsed))
        self.assertEqual(first, second)

    def test_v1(self):
        self.assert_roundtrip(document(VERSION_V1))

    def test_v2_default(self):
        self.assert_roundtrip(document(VERSION_V2))

    def test_v2_mobile_encrypted(self):
        self.assert_roundtrip(document(VERSION_V2, platform="mobile", keypair=1))

    def test_keypair_one_with_zero_ciphertext_tail(self):
        source = document(VERSION_V2, keypair=1)
        # Key pair 1 has a zero at position 18.  A raw text body of 19 bytes
        # therefore has an encrypted NUL terminator and used to be detected as
        # plaintext even though the rest of the body is XOR-obfuscated.
        source["entries"] = [
            {"index": 0, "label": "START", "text": "123456789012345678", "text_hex": ""}
        ]
        blob = build_gmd_bytes(source)
        self.assertEqual(blob[-1], 0)
        parsed = parse_gmd_bytes(blob)
        self.assertEqual(parsed["metadata"]["xor_keypair"], 1)
        self.assertEqual(parsed["entries"][0]["text"], "123456789012345678")
        self.assert_roundtrip(source)


if __name__ == "__main__":
    unittest.main()
