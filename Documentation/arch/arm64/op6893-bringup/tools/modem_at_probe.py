#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Minimal AT client for the MD AT/MUX byte pipe.

The MD is the modem: this tool establishes the 0710 control channel, sends AT
commands and prints the MD's own answers. It never answers AT itself. Output is
bounded and printable-only, so a response line cannot leak binary payload.

--self-test runs the same state machine against an in-memory modem model, which
is the only path that is exercised without hardware.
"""
from pathlib import Path
import argparse
import os
import select
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import modem_at_mux as mux  # noqa: E402

LINE_MAX = 256
READ_MAX = 1024


class AtError(RuntimeError):
    """Transport or protocol failure; messages carry no payload text."""


class FdReader:
    """select/read wrapper so the same state machine runs on a real fd or a model."""

    def __init__(self, fd, reader=os.read):
        self.fd = fd
        self.reader = reader

    def fileno(self):
        return self.fd

    def read(self, size):
        return self.reader(self.fd, size)


def _drain(reader, buffer, deadline):
    """Read whatever is available until the deadline; returns (frames, buffer)."""
    out = []
    while time.monotonic() < deadline:
        ready, _, _ = select.select([reader], [], [],
                                    max(0.0, deadline - time.monotonic()))
        if not ready:
            break
        chunk = reader.read(READ_MAX)
        if not chunk:
            raise AtError('endpoint closed')
        buffer += chunk
        got, buffer = mux.frames(buffer)
        out.extend(got)
        if got:
            break
    return out, buffer


def establish(reader, write, timeout):
    """SABM on DLCI 0, then wait for UA. Any DM is a refusal, not a retry."""
    write(mux.encode(0, mux.CONTROL_SABM))
    deadline = time.monotonic() + timeout
    buffer = b''
    while time.monotonic() < deadline:
        got, buffer = _drain(reader, buffer, deadline)
        for frame in got:
            if frame.dlci == 0 and frame.control == mux.CONTROL_UA:
                return
            if frame.dlci == 0 and frame.control == mux.CONTROL_DM:
                raise AtError('modem refused the control channel')
    raise AtError('no UA within the deadline')


def command(reader, write, text, timeout):
    """Send one AT command and return the printable response lines."""
    if not text or len(text) > mux.PAYLOAD_MAX - 2:
        raise AtError('command length out of range')
    if any(not 0x20 <= ord(char) < 0x7f for char in text):
        raise AtError('command must be printable ASCII')
    write(mux.encode(0, mux.CONTROL_UIH, (text + '\r').encode('ascii')))
    deadline = time.monotonic() + timeout
    buffer = b''
    lines = []
    while time.monotonic() < deadline:
        got, buffer = _drain(reader, buffer, deadline)
        for frame in got:
            if frame.dlci != 0 or frame.control != mux.CONTROL_UIH:
                continue
            for line in mux.printable(frame.payload, LINE_MAX).split('.'):
                if not line:
                    continue
                lines.append(line)
                if line in ('OK', 'ERROR', '+CME ERROR', 'NO CARRIER'):
                    return lines
        if got and not lines:
            return lines
    return lines


class ModelModem:
    """In-memory stand-in for --self-test only; it is not the MD."""

    def __init__(self):
        self.inbox = bytearray()
        self.outbox = bytearray()
        self.established = False
        self.commands = []

    def write(self, data):
        self.inbox += data
        got, rest = mux.frames(bytes(self.inbox))
        self.inbox = bytearray(rest)
        for frame in got:
            if frame.control == mux.CONTROL_SABM:
                self.established = True
                self.outbox += mux.encode(0, mux.CONTROL_UA)
            elif frame.control == mux.CONTROL_UIH and self.established:
                text = frame.payload.decode('ascii', 'replace').strip()
                self.commands.append(text)
                if text == 'AT':
                    reply = b'\r\nOK\r\n'
                elif text == 'AT+CSQ':
                    reply = b'\r\n+CSQ: 20,99\r\n\r\nOK\r\n'
                elif text == 'AT+CREG?':
                    reply = b'\r\n+CREG: 0,2\r\n\r\nOK\r\n'
                else:
                    reply = b'\r\nERROR\r\n'
                self.outbox += mux.encode(0, mux.CONTROL_UIH, reply)

    def read(self, size):
        chunk = bytes(self.outbox[:size])
        del self.outbox[:len(chunk)]
        return chunk


def self_test():
    model = ModelModem()
    rfd, wfd = os.pipe()
    try:
        reader = FdReader(rfd)

        def write(data):
            model.write(data)
            reply = model.read(READ_MAX)
            if reply:
                os.write(wfd, reply)

        establish(reader, write, 1.0)
        assert model.established
        assert command(reader, write, 'AT', 1.0) == ['OK']
        assert command(reader, write, 'AT+CSQ', 1.0) == ['+CSQ: 20,99', 'OK']
        assert command(reader, write, 'AT+CREG?', 1.0) == ['+CREG: 0,2', 'OK']
        assert command(reader, write, 'AT+NOPE', 1.0) == ['ERROR']
        assert model.commands == ['AT', 'AT+CSQ', 'AT+CREG?', 'AT+NOPE']
        for bad in ('', 'AT\x01', 'A' * 300):
            try:
                command(reader, write, bad, 1.0)
            except AtError:
                pass
            else:
                raise AssertionError('accepted an invalid command')
    finally:
        os.close(rfd)
        os.close(wfd)
    print('PASS: AT client state machine: SABM/UA, UIH round-trip, response lines,')
    print('      ERROR termination and command validation (in-memory model only)')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', help='AT byte pipe, e.g. /dev/ccci-at-<devname>')
    parser.add_argument('--command', action='append', default=[],
                        help='AT command to send; repeatable')
    parser.add_argument('--timeout', type=float, default=3.0)
    parser.add_argument('--self-test', action='store_true',
                        help='run the client against an in-memory model')
    args = parser.parse_args(argv)

    if args.self_test:
        self_test()
        return 0
    if not args.device or not args.command:
        parser.error('--device and at least one --command are required')

    fd = os.open(args.device, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    reader = FdReader(fd)
    try:
        establish(reader, os.write, args.timeout)
        for text in args.command:
            lines = command(reader, os.write, text, args.timeout)
            sys.stdout.write('%s -> %s\n' % (text, ' | '.join(lines) if lines else '<no reply>'))
    finally:
        os.close(fd)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
