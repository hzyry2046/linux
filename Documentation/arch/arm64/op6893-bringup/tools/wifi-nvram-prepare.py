#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Validate an op6893 nvdata WIFI file and optionally prepare a local frame.

Host-side preparation only: never opens /dev/wmtWifi or sends to a device.
Protocol reference: wlan_assistant SHA256 7ca456c570ceaada7483cbf9bafe983d5
e67fac4be6bd8ee3d7d40c78da84c1d, function 0x165c; ACK WIFI_write and
wlanNvramBufHandler. A prepared frame contains private calibration data.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat

PREFIX = b"WR-BUF:NVRAM"
RECORD_SIZE = 6144


def checksum(data):
    acc = 0
    for index, value in enumerate(data):
        acc = acc ^ value if index & 1 else acc + value
    return acc & 255


def read_regular(path, maximum):
    """Bound reads and reject special files, including character devices."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
            raise ValueError("expected a bounded regular input file")
        data = source.read(maximum + 1)
        after = os.fstat(source.fileno())
        if (len(data) != before.st_size or len(data) > maximum or
                (before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError("input size or timestamps changed during read")
    return data


def prepare(blob, mac_text=None):
    """Strict board-specific shape; retain all record bytes unless MAC overridden."""
    if len(blob) != RECORD_SIZE + 2:
        raise ValueError("expected the op6893 6144-byte record plus 2-byte trailer")
    record = bytearray(blob[:-2])
    if blob[-2] != 0xaa or checksum(record) != blob[-1]:
        raise ValueError("invalid nvdata trailer marker or checksum")
    if mac_text is not None:
        # Strict parsing rather than reproducing strtol's partial conversions.
        if re.fullmatch(rb"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\n?", mac_text) is None:
            raise ValueError("invalid explicit MAC override format")
        record[4:10] = bytes.fromhex(mac_text.strip().decode("ascii").replace(":", ""))
    return PREFIX + record


def describe(blob, frame):
    return {
        "input_size": len(blob),
        "input_sha256": hashlib.sha256(blob).hexdigest(),
        "record_size": len(frame) - len(PREFIX),
        "prefix_size": len(PREFIX),
        "frame_size": len(frame),
        "frame_sha256": hashlib.sha256(frame).hexdigest(),
        "record_version_byte_preserved": frame[-1] == blob[-3],
        "extra_zero_padding": False,
        "device_submission": False,
    }


def save_new(path, frame):
    # O_EXCL rejects existing files, symlinks and device nodes; mode keeps
    # private calibration out of files readable by other users.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as target:
        target.write(frame)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--mac-file", type=Path,
                        help="explicit override only; no implicit Android path lookup")
    parser.add_argument("--output", type=Path,
                        help="create a NEW private local file; never overwrite")
    args = parser.parse_args()
    try:
        blob = read_regular(args.input, RECORD_SIZE + 2)
        mac = read_regular(args.mac_file, 18) if args.mac_file else None
        frame = prepare(blob, mac)
        if args.output:
            save_new(args.output, frame)
        result = describe(blob, frame)
        result["mac_override"] = mac is not None
        result["local_frame_created"] = args.output is not None
        print(json.dumps(result, indent=2))
    except (OSError, ValueError) as error:
        parser.exit(1, f"preparation failed: {error}\n")


if __name__ == "__main__":
    main()
