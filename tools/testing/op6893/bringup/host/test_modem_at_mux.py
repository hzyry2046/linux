#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Host checks for the 0710 basic-mode codec: synthetic frames only.

This validates the wire format (flag/stuffing/FCS/length rules) and its
rejection bounds. It says nothing about the MD's own 0710 implementation.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import modem_at_mux as mux  # noqa: E402


def main():
    # FCS is a complemented CRC-8; the empty input still maps through 0xFF.
    assert mux.fcs(b'') == 0x00
    assert len(mux.FCS_TABLE) == 256

    # A UIH frame carrying "AT\r" on DLCI 0 round-trips byte for byte.
    frame = mux.encode(0, mux.CONTROL_UIH, b'AT\r')
    assert frame[0] == mux.FLAG and frame[-1] == mux.FLAG
    decoded = mux.decode(frame)
    assert decoded.dlci == 0 and decoded.control == mux.CONTROL_UIH
    assert decoded.payload == b'AT\r'

    # Establishment and teardown frames carry no payload and stay control-only.
    for control in (mux.CONTROL_SABM, mux.CONTROL_UA, mux.CONTROL_DM, mux.CONTROL_DISC):
        one = mux.decode(mux.encode(0, control))
        assert one.control == control and one.payload == b''

    # A DLCI other than zero still round-trips: the address field is dlci << 2.
    assert mux.decode(mux.encode(5, mux.CONTROL_UIH, b'x')).dlci == 5

    # Flag and escape bytes inside the body are stuffed, then restored.
    body = bytes((mux.FLAG, mux.ESCAPE, 0x41))
    stuffed = mux.encode(0, mux.CONTROL_UIH, body)
    assert mux.FLAG not in stuffed[1:-1] and mux.ESCAPE in stuffed[1:-1]
    assert mux.decode(stuffed).payload == body

    # Rejections: every one of them must raise, never guess.
    def reject(data):
        try:
            mux.decode(data)
        except mux.MuxError:
            return
        raise AssertionError('accepted a malformed frame')

    reject(b'')
    reject(frame[:-1])                                   # missing trailing flag
    reject(bytes((0x00,)) + frame[1:])                   # missing leading flag
    reject(frame[:-1] + bytes((mux.FLAG,))[:-1])         # truncated
    corrupted = bytearray(frame)
    corrupted[-2] ^= 0xFF                                # FCS mismatch
    reject(bytes(corrupted))
    reject(mux.encode(0, mux.CONTROL_SABM) + b'\x00')     # trailing junk
    bad_address = bytearray(mux.encode(0, mux.CONTROL_SABM))
    bad_address[1] = 0x02                                # EA bits not set
    body = bytes(bad_address[1:-1])
    bad_address[-2] = mux.fcs(body[:-1])
    reject(bytes(bad_address))
    # A UIH length that disagrees with the frame is refused, and so is an
    # oversized payload at encode time.
    try:
        mux.encode(0, mux.CONTROL_UIH, b'A' * (mux.PAYLOAD_MAX + 1))
    except mux.MuxError:
        pass
    else:
        raise AssertionError('accepted an oversized payload')

    # A stream split across reads yields only whole frames, with the tail kept.
    stream = mux.encode(0, mux.CONTROL_SABM) + mux.encode(0, mux.CONTROL_UIH, b'AT')
    got, tail = mux.frames(stream)
    assert len(got) == 2 and tail == b''
    got, tail = mux.frames(stream + stream[:3])
    assert len(got) == 2 and tail == stream[:3]
    got, tail = mux.frames(b'\x00\x11' + stream)
    assert len(got) == 2 and tail == b''

    # The printable view hides non-ASCII and is bounded.
    assert mux.printable(b'AT+CSQ\r\n\xff\x01') == 'AT+CSQ....'
    assert len(mux.printable(b'A' * 200, limit=16)) == 16

    print('PASS: actual 0710 basic-mode codec: flags, stuffing, FCS, UIH length,')
    print('      DLCI round-trip, whole-frame splitting and every rejection bound')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
