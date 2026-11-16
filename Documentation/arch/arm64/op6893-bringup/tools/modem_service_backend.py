#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Explicit experimental FS endpoint runner, not a modem launch/ready service.

The 32-byte record header is LE <IIQQII>: version, kind, generation, token,
slot, canonical packet length. Each read/write must transfer ONE WHOLE record.
There is no stream reassembly or retry after a short read/write. Any unsupported
request or failure closes the endpoint so the kernel can revoke the lease.

Only the caller's marked private WorkingCopy is used. RPC is deliberately not
implemented. No operation logs paths, packet bytes, contents or exception text.
The caller must explicitly provide --endpoint, --root and --generation; this
program does not start the modem, provision data, or claim services are ready.
"""

import argparse
from dataclasses import dataclass, field
import os
import stat
import struct
import sys

from modem_fs_backend import WorkingCopy, UnsupportedOperation
from modem_fs_wire import MESSAGE_MAX, StaleGeneration, respond

VERSION = 1
FS = 0
RPC = 1
HEADER = struct.Struct('<IIQQII')
RPC_MAX = 2048
RECORD_MAX = HEADER.size + MESSAGE_MAX


class RecordError(ValueError):
    """Malformed endpoint record; messages contain no untrusted input."""


@dataclass(frozen=True)
class Record:
    kind: int
    generation: int
    token: int
    slot: int
    packet: bytes = field(repr=False)


def _generation(value):
    if type(value) is not int or not 0 < value <= 0xffffffffffffffff:
        raise RecordError('invalid expected generation')


def decode_record(data, expected_generation):
    """Reject stale/malformed metadata before any backend file operation."""
    _generation(expected_generation)
    if not isinstance(data, bytes) or not HEADER.size + 24 <= len(data) <= RECORD_MAX:
        raise RecordError('invalid record size')
    version, kind, generation, token, slot, length = HEADER.unpack_from(data)
    if version != VERSION or kind not in (FS, RPC) or token == 0:
        raise RecordError('invalid record metadata')
    if generation != expected_generation:
        raise StaleGeneration('record generation revoked')
    limit, slots, channel = ((MESSAGE_MAX, 5, 14) if kind == FS else (RPC_MAX, 3, 32))
    if length < 24 or length > limit or slot >= slots or len(data) != HEADER.size + length:
        raise RecordError('invalid record bounds')
    packet = data[HEADER.size:]
    data0, canonical_length, channel_sequence, canonical_slot = struct.unpack_from('<4I', packet)
    if ((kind == FS and data0 & 0x80000000) or canonical_length != length or
            channel_sequence & 0xffff != channel or canonical_slot != slot):
        raise RecordError('canonical header and record disagree')
    return Record(kind, generation, token, slot, packet)


def _reply(record, packet):
    if record.kind != FS:
        raise UnsupportedOperation('RPC service is not implemented')
    if not isinstance(packet, bytes) or not 24 <= len(packet) <= MESSAGE_MAX:
        raise RecordError('invalid canonical response size')
    length, sequence, slot, operation = struct.unpack_from('<4I', packet, 4)
    request_operation, = struct.unpack_from('<I', record.packet, 16)
    if (length != len(packet) or sequence & 0xffff != 15 or slot != record.slot or
            operation != request_operation):
        raise RecordError('invalid canonical response metadata')
    return HEADER.pack(VERSION, record.kind, record.generation, record.token,
                       record.slot, len(packet)) + packet


def serve(backend, generation, fd, *, reader=os.read, writer=os.write):
    """Own/close fd; serve serial atomic records until EOF or an exception.

    The caller owns backend shutdown. Generation mismatch, malformed records,
    unsupported semantics, and short writes propagate AFTER fd closure. There
    are no payload logs or fallback replies. Endpoint closure revokes in-flight
    requests; this function never retries a potentially published response.
    """
    count = 0
    try:
        _generation(generation)
        while True:
            # One extra byte detects an oversized atomic record instead of
            # accidentally accepting its valid-looking truncated prefix.
            data = reader(fd, RECORD_MAX + 1)
            if data == b'':
                return count
            record = decode_record(data, generation)
            if record.kind != FS:
                raise UnsupportedOperation('RPC service is not implemented')
            packet = respond(backend, generation, record.packet)
            reply = _reply(record, packet)
            if writer(fd, reply) != len(reply):
                raise RecordError('short endpoint write')
            count += 1
    finally:
        os.close(fd)


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's normal errors may repeat an arbitrary private path/value.
        self.exit(2, 'invalid backend arguments\n')


def main(argv=None):
    parser = _ArgumentParser(description=__doc__)
    parser.add_argument('--endpoint', required=True, help='explicit kernel endpoint node')
    parser.add_argument('--root', required=True, help='existing marked private working copy')
    parser.add_argument('--generation', required=True, help='explicit nonzero generation')
    args = parser.parse_args(argv)
    backend = None
    fd = -1
    status = 0
    try:
        generation = int(args.generation, 0)
        _generation(generation)
        backend = WorkingCopy(args.root, generation)
        fd = os.open(args.endpoint, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
        if not stat.S_ISCHR(os.fstat(fd).st_mode):
            raise RecordError('endpoint must be a character device')
        owned_fd, fd = fd, -1
        serve(backend, generation, owned_fd)
    except KeyboardInterrupt:
        sys.stderr.write('modem backend interrupted\n')
        status = 130
    except Exception:
        sys.stderr.write('modem backend stopped after an error\n')
        status = 1
    finally:
        cleanup_error = False
        if fd >= 0:
            try:
                os.close(fd)
            except Exception:
                cleanup_error = True
        if backend is not None:
            try:
                cleanup_error |= bool(backend.shutdown())
            except Exception:
                cleanup_error = True
        if cleanup_error and not status:
            sys.stderr.write('modem backend cleanup failed\n')
            status = 1
    return status


if __name__ == '__main__':
    sys.exit(main())
