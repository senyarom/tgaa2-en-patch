from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "inject_court_record_hook.py"
SPEC = importlib.util.spec_from_file_location("inject_court_record_hook", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class InjectCourtRecordHookTests(unittest.TestCase):
    def test_arm_blx_to_tgaa2_thumb_cave(self) -> None:
        self.assertEqual(
            MODULE.arm_branch_link_exchange(0x0026_FC84, 0x0056_9A3C),
            bytes.fromhex("6c e7 0b fa"),
        )

    def test_arm_blx_encodes_halfword_bit(self) -> None:
        self.assertEqual(
            MODULE.arm_branch_link_exchange(0x1000, 0x100A),
            bytes.fromhex("00 00 00 fb"),
        )

    def test_arm_blx_rejects_odd_target(self) -> None:
        with self.assertRaisesRegex(ValueError, "halfword-aligned"):
            MODULE.arm_branch_link_exchange(0x1000, 0x1009)


if __name__ == "__main__":
    unittest.main()
