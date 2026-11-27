#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic local record framing; no modem node, original data or device I/O."""

import contextlib
import io
import json
import os
from pathlib import Path
import socket
import stat
from types import SimpleNamespace
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch

from modem_fs_backend import ACKNOWLEDGEMENT, MARKER, WorkingCopy
from modem_fs_wire import StaleGeneration, UnsupportedOperation, request_summary
from modem_service_backend import (FS, HEADER, RECORD_MAX, RPC, VERSION,
                                   RecordError, decode_record, load_rpc_policy, main,
                                   rpc_request_name, serve)


def word(value):
    return struct.pack('<I', value & 0xffffffff)


def packet(operation=0x101c, args=(), channel=14, slot=4):
    body = word(0xffff0000 | operation) + word(len(args))
    for arg in args:
        body += word(len(arg)) + arg + b'\0' * (-len(arg) % 4)
    return struct.pack('<4I', 0x40000000, 16 + len(body), 0x89230000 | channel,
                       slot) + body


def record(body=None, version=VERSION, kind=FS, generation=19, token=0x123456789,
           slot=4, length=None):
    body = packet() if body is None else body
    return HEADER.pack(version, kind, generation, token, slot,
                       len(body) if length is None else length) + body


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='modem-service-synthetic-')
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        marker = self.root / MARKER
        marker.write_bytes(ACKNOWLEDGEMENT)
        marker.chmod(0o600)
        (self.root / 'Z').mkdir()
        (self.root / 'Z' / 'sample').write_bytes(b'\0\xff\x80synthetic')
        self.backend = WorkingCopy(self.root, 19)

    def tearDown(self):
        self.backend.shutdown()
        self.temp.cleanup()

    @staticmethod
    def descriptor():
        # A harmless local pipe fd is the lifetime witness; reads/writes may be
        # mocked. No device node is opened by any test.
        reader, writer = os.pipe()
        os.close(writer)
        return reader

    def assert_closed(self, fd):
        with self.assertRaises(OSError):
            os.fstat(fd)

    def test_socket_seqpacket_one_read_one_write_and_exact_metadata(self):
        peer, endpoint = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        fd = endpoint.detach()
        try:
            peer.sendall(record())
            peer.shutdown(socket.SHUT_WR)
            self.assertEqual(serve(self.backend, 19, fd), 1)
            reply = peer.recv(RECORD_MAX)
            self.assertEqual(HEADER.unpack_from(reply),
                             (1, FS, 19, 0x123456789, 4, len(reply) - 32))
            self.assertEqual(struct.unpack_from('<I', reply, 32 + 8)[0], 0x8923000f)
            self.assertEqual(struct.unpack_from('<I', reply, 32 + 24 + 4)[0], 0)
            self.assertEqual(peer.recv(RECORD_MAX), b'')
            self.assert_closed(fd)
        finally:
            peer.close()

    def test_pipe_read_and_mock_write_whole_record(self):
        fd, producer = os.pipe()
        request = record()
        os.write(producer, request)
        os.close(producer)
        writes = []
        def write_one(target, value):
            self.assertEqual(target, fd)
            writes.append(value)
            return len(value)
        self.assertEqual(serve(self.backend, 19, fd, writer=write_one), 1)
        self.assertEqual(len(writes), 1)
        self.assertEqual(HEADER.unpack_from(writes[0])[:5], (1, 0, 19, 0x123456789, 4))
        self.assert_closed(fd)

    def test_multiple_records_are_individual_syscalls_not_stream_concatenation(self):
        fd = self.descriptor()
        reader = Mock(side_effect=[record(token=12), record(token=3), b''])
        writer = Mock(side_effect=lambda target, value: len(value))
        self.assertEqual(serve(self.backend, 19, fd, reader=reader, writer=writer), 2)
        self.assertEqual(reader.call_count, 3)
        reader.assert_called_with(fd, RECORD_MAX + 1)
        self.assertEqual(writer.call_count, 2)
        self.assertEqual(HEADER.unpack_from(writer.call_args_list[1].args[1])[3], 3)
        self.assert_closed(fd)
        fd = self.descriptor()
        with self.assertRaises(RecordError):
            serve(self.backend, 19, fd, reader=Mock(return_value=record() + record()),
                  writer=Mock())
        self.assert_closed(fd)

    def test_stale_record_is_rejected_before_backend_file_io(self):
        fd = self.descriptor()
        reader, writer = Mock(return_value=record(generation=18)), Mock()
        with patch.object(self.backend, 'operate') as operation:
            with self.assertRaises(StaleGeneration):
                serve(self.backend, 19, fd, reader=reader, writer=writer)
            operation.assert_not_called()
        writer.assert_not_called()
        self.assert_closed(fd)

    def test_rpc_unknown_and_unsupported_close_without_fake_reply(self):
        rpc = struct.pack('<6I', 0, 24, 32, 2, 0x400f, 0)
        requests = [record(rpc, kind=RPC, slot=2), record(kind=2),
                    record(packet(0x1016)),
                    record(packet(0x1022, (("Z:/sample\0").encode('utf-16le'),
                                           struct.pack('<10I', *([0x20] + [0] * 9)))))]
        for request in requests:
            fd = self.descriptor()
            writer = Mock()
            with self.assertRaises((UnsupportedOperation, RecordError)):
                serve(self.backend, 19, fd, reader=Mock(return_value=request), writer=writer)
            writer.assert_not_called()
            self.assert_closed(fd)

    def test_short_read_is_not_reassembled_and_short_write_is_not_retried(self):
        fd = self.descriptor()
        reader = Mock(side_effect=[record()[:31], record()[31:]])
        writer = Mock()
        with self.assertRaises(RecordError):
            serve(self.backend, 19, fd, reader=reader, writer=writer)
        self.assertEqual(reader.call_count, 1)
        writer.assert_not_called()
        self.assert_closed(fd)
        fd = self.descriptor()
        reader, writer = Mock(return_value=record()), Mock(return_value=1)
        with self.assertRaises(RecordError):
            serve(self.backend, 19, fd, reader=reader, writer=writer)
        self.assertEqual(reader.call_count, 1)
        self.assertEqual(writer.call_count, 1)
        self.assert_closed(fd)

    def test_io_errors_also_close_endpoint(self):
        for reader, writer in ((Mock(side_effect=OSError('private error text')), Mock()),
                               (Mock(return_value=record()),
                                Mock(side_effect=OSError('private error text')))):
            fd = self.descriptor()
            with self.assertRaises(OSError):
                serve(self.backend, 19, fd, reader=reader, writer=writer)
            self.assert_closed(fd)

    def test_record_metadata_and_canonical_bounds(self):
        invalid = [record(version=0), record(token=0), record(slot=5),
                   record(length=0), record(length=28), record() + b'x',
                   record(packet(channel=15)), record(packet(slot=3)),
                   b'\0' * (RECORD_MAX + 1)]
        rpc = struct.pack('<6I', 0, 24, 32, 3, 0x400f, 0)
        invalid.append(record(rpc, kind=RPC, slot=3))
        oversized = struct.pack('<4I', 0, 2052, 32, 2) + bytes(2052 - 16)
        invalid.append(record(oversized, kind=RPC, slot=2))
        for request in invalid:
            with self.assertRaises(RecordError):
                decode_record(request, 19)
        for generation in (0, -1, 1 << 64, True, '19'):
            with self.assertRaises(RecordError):
                decode_record(record(), generation)
        parsed = decode_record(record(token=0xffffffffffffffff), 19)
        self.assertEqual(parsed.token, 0xffffffffffffffff)
        self.assertNotIn('packet=', repr(parsed))
        more = bytearray(record())
        struct.pack_into('<I', more, 32, 0x80000000)
        with self.assertRaises(RecordError):
            decode_record(bytes(more), 19)

    def policy(self, value):
        path = self.root / 'rpc-policy.json'
        path.write_text(json.dumps(value))
        path.chmod(0o600)
        return path

    @staticmethod
    def rpc_packet(operation, args=(), slot=2):
        body = word(operation) + word(len(args))
        for arg in args:
            body += word(len(arg)) + arg + b'\0' * (-len(arg) % 4)
        return struct.pack('<4I', 0x12345678, 16 + len(body), 0x89230020, slot) + body

    def test_mixed_fs_and_user_rpc_preserve_atomic_record_identity(self):
        path = self.policy({'version': 1, 'properties': {'known': 'value', 'absent': None},
                            'sar': {'product_hw': 'synthetic', 'regionmark': 'region',
                                    'projects': {'synthetic': {'region': 7}}}})
        rpc = load_rpc_policy(path)
        packets = [record(), record(self.rpc_packet(0x400f, (b'known\0',)), kind=RPC, slot=2),
                   record(self.rpc_packet(0x4010), kind=RPC, slot=2)]
        fd = self.descriptor()
        writer = Mock(side_effect=lambda unused_fd, data: len(data))
        self.assertEqual(serve(self.backend, 19, fd, rpc=rpc,
                               reader=Mock(side_effect=packets + [b'']), writer=writer), 3)
        self.assert_closed(fd)
        for request, call in zip(packets, writer.call_args_list):
            reply = call.args[1]
            self.assertEqual(reply[:28], request[:28])
            self.assertEqual(reply[32:36], request[32:36])
        prop = writer.call_args_list[1].args[1][32:]
        self.assertEqual(struct.unpack_from('<I', prop, 28)[0], 5)
        self.assertEqual(prop[36:42], b'value\0')
        sar = writer.call_args_list[2].args[1][32:]
        self.assertEqual(struct.unpack_from('<I', sar, 36)[0], 7)

    def test_rpc_unknown_fact_and_invalid_reply_close_without_write(self):
        rpc = load_rpc_policy(self.policy({'version': 1, 'properties': {'other': None}}))
        request = record(self.rpc_packet(0x400f, (b'unknown',)), kind=RPC, slot=2)
        from modem_rpc_backend import Unavailable
        for handler, error in [(rpc, Unavailable), (lambda unused: packet(), RecordError)]:
            fd = self.descriptor()
            writer = Mock()
            with self.assertRaises(error):
                serve(self.backend, 19, fd, rpc=handler,
                      reader=Mock(return_value=request), writer=writer)
            writer.assert_not_called()
            self.assert_closed(fd)
        stale = record(self.rpc_packet(0x400f, (b'other',)), kind=RPC, slot=2, generation=18)
        fd = self.descriptor()
        handler = Mock()
        with self.assertRaises(StaleGeneration):
            serve(self.backend, 19, fd, rpc=handler, reader=Mock(return_value=stale))
        handler.assert_not_called()
        self.assert_closed(fd)

    def test_rpc_name_trace_is_opt_in_bounded_and_name_only(self):
        path = self.policy({'version': 1, 'properties': {'known': 'value'}})
        rpc = load_rpc_policy(path)
        request = record(self.rpc_packet(0x400f, (b'known\0',)), kind=RPC, slot=2)
        seen = []
        fd = self.descriptor()
        writer = Mock(side_effect=lambda unused_fd, data: len(data))
        self.assertEqual(serve(self.backend, 19, fd, rpc=rpc, trace=seen.append,
                               reader=Mock(side_effect=[request, b'']), writer=writer), 1)
        self.assertEqual(seen, [request[HEADER.size:]])
        self.assert_closed(fd)
        self.assertEqual(rpc_request_name(self.rpc_packet(0x400f, (b'known\0',), slot=2)),
                         (0x400f, 'known'))
        # Non-printable bytes are hidden and the name is bounded, never a value.
        hostile = bytes(range(0x20)) * 8
        operation, name = rpc_request_name(self.rpc_packet(0x4010, (hostile,), slot=2))
        self.assertEqual(operation, 0x4010)
        self.assertEqual(name, '.' * 64)
        self.assertEqual(rpc_request_name(self.rpc_packet(0x4010, (), slot=2)), (0x4010, ''))
        # An FS record is never traced, and a provider-less RPC record is
        # traced once before the endpoint closes without a reply.
        fd = self.descriptor()
        writer = Mock(side_effect=lambda unused_fd, data: len(data))
        self.assertEqual(serve(self.backend, 19, fd, rpc=rpc, trace=seen.append,
                               reader=Mock(side_effect=[record(), b'']), writer=writer), 1)
        self.assertEqual(len(seen), 1)
        self.assert_closed(fd)
        fd = self.descriptor()
        writer = Mock()
        with self.assertRaises(UnsupportedOperation):
            serve(self.backend, 19, fd, trace=seen.append,
                  reader=Mock(side_effect=[request]), writer=writer)
        self.assertEqual(seen, [request[HEADER.size:], request[HEADER.size:]])
        writer.assert_not_called()
        self.assert_closed(fd)

    def test_fs_trace_is_opt_in_and_never_prints_payload(self):
        seen = []
        fd = self.descriptor()
        writer = Mock(side_effect=lambda unused_fd, data: len(data))
        # Wide path arguments are terminated UTF-16LE, as every MD request is.
        wide = ('Z:\\NVRAM\\x\0').encode('utf-16le')
        request = record(packet(0x1001, (wide, word(0)), slot=4))
        self.assertEqual(serve(self.backend, 19, fd, fs_trace=lambda s, st: seen.append((s, st)),
                               reader=Mock(side_effect=[request, b'']), writer=writer), 1)
        self.assert_closed(fd)
        self.assertEqual(seen[0][0], 'op=0x1001 Z:\\NVRAM\\x 0')
        # A write payload is reduced to its length, never its bytes.
        payload = b'PRIVATE-CONTENT'
        write = record(packet(0x1004, (word(1), payload, word(len(payload))), slot=4))
        summary = request_summary(0x1004, (1, payload, len(payload)))
        self.assertNotIn('PRIVATE', summary)
        self.assertIn('<%d bytes>' % len(payload), summary)
        fd = self.descriptor()
        self.assertEqual(serve(self.backend, 19, fd, fs_trace=lambda s, st: seen.append((s, st)),
                               reader=Mock(side_effect=[write, b'']),
                               writer=Mock(side_effect=lambda unused_fd, data: len(data))), 1)
        self.assert_closed(fd)
        self.assertNotIn('PRIVATE', seen[-1][0])
        # A non-scalar status is reduced to its type name, never printed.
        self.assertEqual(request_summary(0x1010, (('Z:\\a\0').encode('utf-16le'),)),
                         'op=0x1010 Z:\\a')
        # Bytes after the terminator are counted, never rendered as a path.
        self.assertEqual(request_summary(0x1010, (('Z:\\a\0' + 'stale').encode('utf-16le'),)),
                         'op=0x1010 Z:\\a+5 trailing')
        self.assertEqual(request_summary(0x1010, (None,)), 'op=0x1010 None')

    def test_policy_schema_rejects_ambiguous_or_unproven_facts(self):
        invalid = [[], {}, {'version': True}, {'version': 1, 'extra': 2},
                   {'version': 1, 'properties': []},
                   {'version': 1, 'properties': {'known': 3}},
                   {'version': 1, 'properties': {'known': 'a\0b'}},
                   {'version': 1, 'sar': {'index': 0}},
                   {'version': 1, 'sar': {'product_hw': 'x', 'regionmark': 'y',
                                          'projects': {'x': {'y': True}}}}]
        for value in invalid:
            with self.assertRaises((RecordError, ValueError)):
                load_rpc_policy(self.policy(value))
        path = self.policy({'version': 1})
        path.write_text('{"version":1,"properties":{"x":"a","x":"b"}}')
        with self.assertRaises(RecordError):
            load_rpc_policy(path)

    def test_policy_file_permissions_links_size_and_snapshot_lifetime(self):
        path = self.policy({'version': 1, 'properties': {'known': 'old'}})
        rpc = load_rpc_policy(path)
        path.write_text(json.dumps({'version': 1, 'properties': {'known': 'new'}}))
        self.assertIn(b'old\0', rpc(self.rpc_packet(0x400f, (b'known',))))
        for mode in (0o644, 0o400, 0o660):
            path.chmod(mode)
            with self.assertRaises(RecordError):
                load_rpc_policy(path)
        path.chmod(0o600)
        link = self.root / 'policy-link'
        link.symlink_to(path)
        with self.assertRaises(OSError):
            load_rpc_policy(link)
        link.unlink()
        os.link(path, link)
        with self.assertRaises(RecordError):
            load_rpc_policy(path)
        link.unlink()
        for content in (b'', b' ' * 65537):
            path.write_bytes(content)
            with self.assertRaises(RecordError):
                load_rpc_policy(path)


    def test_cli_refuses_regular_endpoint_and_reports_cleanup_failure_safely(self):
        endpoint = self.root / 'ordinary'
        endpoint.write_bytes(b'')
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            self.assertEqual(main(['--endpoint', str(endpoint), '--root', str(self.root),
                                   '--generation', '19']), 1)
        self.assertEqual(output.getvalue(),
                         'modem backend stopped after an error (RecordError)\n')
        fd = self.descriptor()
        backend = Mock()
        backend.shutdown.return_value = -18
        def close_endpoint(unused_backend, unused_generation, owned_fd, **unused_options):
            os.close(owned_fd)
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            with patch('modem_service_backend.WorkingCopy', return_value=backend), \
                 patch('modem_service_backend.os.open', return_value=fd), \
                 patch('modem_service_backend.os.fstat',
                       return_value=SimpleNamespace(st_mode=stat.S_IFCHR)), \
                 patch('modem_service_backend.serve', side_effect=close_endpoint):
                self.assertEqual(main(['--endpoint', '/explicit/synthetic', '--root',
                                       '/private/synthetic', '--generation', '19']), 1)
        backend.shutdown.assert_called_once()
        self.assertEqual(output.getvalue(), 'modem backend cleanup failed\n')
        self.assert_closed(fd)

    def test_cli_error_logs_do_not_repeat_paths_or_exception_text(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            with patch('modem_service_backend.WorkingCopy',
                       side_effect=RuntimeError('private payload bytes')):
                result = main(['--endpoint', '/private/endpoint', '--root', '/private/root',
                               '--generation', '19'])
        self.assertEqual(result, 1)
        self.assertEqual(output.getvalue(),
                         'modem backend stopped after an error (RuntimeError)\n')
        self.assertNotIn('private payload', output.getvalue())
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            with self.assertRaises(SystemExit) as result:
                main(['--private-unknown', '/private/secret'])
        self.assertEqual(result.exception.code, 2)
        self.assertEqual(output.getvalue(), 'invalid backend arguments\n')


if __name__ == '__main__':
    unittest.main()
