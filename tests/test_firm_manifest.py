import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from dgs2tool.firm import extract_firm
from dgs2tool.manifest import parse_autorun


class FirmManifestTests(unittest.TestCase):
    def test_extract_prefixed_ustar(self):
        payload = b"set DGS_VERSION 9.9.9\n"
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w", format=tarfile.USTAR_FORMAT) as tar:
            info = tarfile.TarInfo("autorun.gm9")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            firm = root / "test.firm"
            firm.write_bytes(b"\0" * 512 + archive.getvalue())
            entries = extract_firm(firm, root / "out")
            self.assertEqual(entries[0].name, "autorun.gm9")
            self.assertEqual((root / "out" / "autorun.gm9").read_bytes(), payload)

    def test_manifest(self):
        script = """\
set DGS_VERSION 2.1.0
set DGS_EPISODE 3
cp -p $[SOURCE]/romfs/script/_output/_sce04_test_jpn.gmd $[OUTPATH]/DGS-JPN.bin
cp -p $[OUTPATH]/manual.bcma $[OUTPATH]/DGS-JPN.bin
"""
        manifest = parse_autorun(script)
        self.assertEqual(manifest["variables"]["DGS_VERSION"], "2.1.0")
        self.assertEqual(manifest["summary"]["resource_count"], 2)
        self.assertEqual(manifest["resources"][0]["scene_number"], 4)


if __name__ == "__main__":
    unittest.main()
