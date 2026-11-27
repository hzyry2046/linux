#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline protocol and local-output tests using synthetic calibration data."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOL = Path(__file__).resolve().parents[1] / "wifi-nvram-prepare.py"
if not TOOL.exists():
    TOOL = Path(__file__).resolve().with_name("wifi-nvram-prepare.py")
SPEC = importlib.util.spec_from_file_location("nvram_prepare", TOOL)
PREP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREP)


def fixture():
    # Fixed nonzero endpoints catch both accidental NUL-prefix insertion and
    # replacement of the OPLUS version byte by the report's claimed padding.
    record = bytearray((index * 13 + 3) % 256 for index in range(6144))
    record[-1] = 2
    return bytes(record) + bytes((0xaa, PREP.checksum(record)))


class ProtocolTests(unittest.TestCase):
    def test_exact_handler_bytes(self):
        blob = fixture()
        frame = PREP.prepare(blob)
        self.assertEqual(frame[:12], b"WR-BUF:NVRAM")
        self.assertEqual(len(frame), 6156)
        self.assertEqual(frame[12:], blob[:-2])
        self.assertEqual(frame[-1], 2)

    def test_no_nul_between_prefix_and_record(self):
        self.assertEqual(PREP.prepare(fixture())[12], 3)

    def test_checksum_known_vector(self):
        self.assertEqual(PREP.checksum(bytes((1, 2, 3, 4))), 2)

    def test_bad_marker(self):
        blob = fixture()
        with self.assertRaises(ValueError):
            PREP.prepare(blob[:-2] + b"\x00" + blob[-1:])

    def test_corrupt_record(self):
        blob = bytearray(fixture())
        blob[42] ^= 1
        with self.assertRaises(ValueError):
            PREP.prepare(blob)

    def test_reject_wrong_sizes(self):
        blob = fixture()
        for bad in (b"", blob[:-2], blob[:-1], blob + b"\0", blob * 3):
            with self.subTest(size=len(bad)), self.assertRaises(ValueError):
                PREP.prepare(bad)

    def test_override_changes_only_mac(self):
        plain = PREP.prepare(fixture())
        patched = PREP.prepare(fixture(), b"02:12:34:56:78:9a\n")
        self.assertEqual(patched[:16], plain[:16])
        self.assertEqual(patched[16:22], bytes.fromhex("02123456789a"))
        self.assertEqual(patched[22:], plain[22:])

    def test_strict_override(self):
        for text in (b"zz:12:34:56:78:9a", b"02-12-34-56-78-9a",
                     b"02:12:34:56:78:9a extra", b""):
            with self.subTest(text=text), self.assertRaises(ValueError):
                PREP.prepare(fixture(), text)

    def test_regular_file_and_exclusive_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "frame"
            PREP.save_new(path, PREP.prepare(fixture()))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                PREP.save_new(path, b"replaced")
            self.assertEqual(PREP.read_regular(path, 6156), PREP.prepare(fixture()))

    def test_reject_special_input(self):
        with self.assertRaises(ValueError):
            PREP.read_regular("/dev/null", 6146)

    def test_reject_symlink_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "link"
            path.symlink_to("/dev/null")
            with self.assertRaises(FileExistsError):
                PREP.save_new(path, b"frame")

    def test_cli_only_emits_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "WIFI"
            path.write_bytes(fixture())
            result = subprocess.run([sys.executable, str(TOOL), str(path)],
                                    capture_output=True, text=True, check=True)
            metadata = json.loads(result.stdout)
            self.assertEqual(metadata["frame_size"], 6156)
            self.assertFalse(metadata["local_frame_created"])
            self.assertFalse(metadata["device_submission"])
            self.assertEqual(os.listdir(directory), ["WIFI"])


if __name__ == "__main__":
    unittest.main()
