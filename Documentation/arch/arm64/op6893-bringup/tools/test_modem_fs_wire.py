#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic FS canonical adapter tests; no device or original NVRAM access."""

from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from modem_fs_backend import ACKNOWLEDGEMENT, MARKER, MAX_IO, WorkingCopy
from modem_fs_wire import (MESSAGE_MAX, MORE, MalformedRequest, StaleGeneration,
                           UnsupportedOperation, decode_request, respond)

K = Path(__file__).resolve().parents[5]


def word(value):
    return struct.pack('<I', value & 0xffffffff)


def wide(value):
    return (value + '\0').encode('utf-16le')


def packet(operation, args, data0=0x40001234, sequence=0x83570000, slot=4):
    body = word(0xffff0000 | operation) + word(len(args))
    for arg in args:
        body += word(len(arg)) + arg + b'\0' * (-len(arg) % 4)
    return struct.pack('<4I', data0, len(body) + 16, sequence | 14, slot) + body


def reply_args(reply):
    # Reuse strict canonical parser after changing only direction for inspection.
    changed = bytearray(reply)
    sequence, = struct.unpack_from('<I', changed, 8)
    struct.pack_into('<I', changed, 8, sequence & 0xffff0000 | 14)
    return decode_request(bytes(changed)).args


class WireTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='modem-fs-wire-synthetic-')
        self.root = Path(self.temp.name) / 'work'
        self.root.mkdir(mode=0o700)
        marker = self.root / MARKER
        marker.write_bytes(ACKNOWLEDGEMENT)
        marker.chmod(0o600)
        (self.root / 'Z').mkdir()
        self.sample = bytes(range(256)) + b'\0\xffpayload\0'
        (self.root / 'Z' / 'sample').write_bytes(self.sample)
        self.backend = WorkingCopy(self.root, 17)

    def tearDown(self):
        self.backend.shutdown()
        self.temp.cleanup()

    def call(self, operation, *args):
        request = packet(operation, args)
        reply = respond(self.backend, 17, request)
        self.assertEqual(struct.unpack_from('<I', reply)[0], 0x40001234)
        self.assertEqual(struct.unpack_from('<I', reply, 4)[0], len(reply))
        self.assertEqual(struct.unpack_from('<I', reply, 8)[0], 0x8357000f)
        self.assertEqual(struct.unpack_from('<I', reply, 12)[0], 4)
        self.assertEqual(struct.unpack_from('<I', reply, 16)[0],
                         0xffff0000 | operation)
        return reply_args(reply)

    def test_binary_open_seek_read_write_close_and_metadata(self):
        handle_bytes, = self.call(0x1001, wide('Z:\\sample'), word(0x21010400))
        handle, = struct.unpack('<I', handle_bytes)
        self.assertEqual(self.call(0x1009, word(handle)), (word(0), word(len(self.sample))))
        self.assertEqual(self.call(0x1002, word(handle), word(256), word(0)), (word(256),))
        data = b'\x80\0\xff\xfe'
        self.assertEqual(self.call(0x1004, word(handle), data, word(len(data))),
                         (word(0), word(len(data))))
        self.assertEqual(self.call(0x1002, word(handle), word(-len(data)), word(1)),
                         (word(256),))
        self.assertEqual(self.call(0x1003, word(handle), word(len(data))),
                         (word(0), word(len(data)), data))
        self.assertEqual(self.call(0x1005, word(handle)), (word(0),))
        self.assertEqual(self.call(0x1003, word(handle), word(1)),
                         (word(-10), word(0), b''))

    def test_known_errors_and_control_operations(self):
        self.assertEqual(self.call(0x1001, wide('Z:/missing'), word(0x700)), (word(-9),))
        self.assertEqual(self.call(0x1001, wide('Z:/../escape'), word(0x20000)), (word(-16),))
        self.assertEqual(self.call(0x1007, wide('Q:/missing')), (word(-9),))
        self.assertEqual(self.call(0x1007, wide('Z:/child')), (word(0),))
        self.assertEqual(self.call(0x1009, word(0xffffffff)), (word(-10), word(0)))
        self.assertEqual(self.call(0x101a, word(4), word(2), word(12)), (word(ord('Z')),))
        self.assertEqual(self.call(0x101a, word(8), word(2), word(12)), (word(-2),))
        self.assertEqual(self.call(0x101c), (word(0),))
        self.assertEqual(self.call(0x1025, wide('T:/missing')),
                         (word(-9), bytes(24)))
        self.assertEqual(self.call(0x1012, wide('R:/missing/*.*'), b'\0', b'\0',
                                   word(64)), (word(-9), bytes(52), b''))

    def test_cmpt_exact_response_and_ignored_pointer_words(self):
        control = struct.pack('<10I', 0x1f, 0, 0, 0x700, 0xdeadbeef,
                              250, 1, 0xffffffff, 32, 0x12345678)
        result = self.call(0x1022, wide('Z:/sample'), control)
        expected = self.sample[250:282]
        self.assertEqual(result, (struct.pack('<II', 0x1f, 0), word(len(self.sample)),
                                  word(len(expected)), expected))
        self.assertEqual(self.backend.handles, {})
        self.assertEqual(self.call(0x1022, wide('Z:/missing'), control),
                         (struct.pack('<Ii', 0, -9), word(0), word(0), b''))
        self.assertEqual(self.backend.handles, {})

    def test_canonical_envelope_rejection_before_backend_access(self):
        original = packet(0x101c, ())
        invalid = [b'', original[:23], original + b'x']
        for offset, value in ((0, MORE), (4, 0), (8, 15), (12, 5),
                              (16, 0x1001), (16, 0xffff1026), (20, 7)):
            changed = bytearray(original)
            struct.pack_into('<I', changed, offset, value)
            invalid.append(bytes(changed))
        for request in invalid:
            with self.subTest(length=len(request)):
                with patch.object(self.backend, 'operate') as operate:
                    with self.assertRaises(MalformedRequest):
                        respond(self.backend, 17, request)
                    operate.assert_not_called()
        with self.assertRaises(MalformedRequest):
            decode_request(b'\0' * (MESSAGE_MAX + 1))

    def test_argument_schema_rejection_before_backend_access(self):
        invalid = [packet(0x1001, (wide('Z:/x'), b'x')),
                   packet(0x1001, (b'odd', word(0))),
                   packet(0x1001, (wide('Z:/x'),)),
                   packet(0x1002, (word(1), word(0), word(3))),
                   packet(0x1003, (word(1), word(MAX_IO + 1))),
                   packet(0x1004, (word(1), b'x', word(2))),
                   packet(0x1004, (b'', b'x', word(1))),
                   packet(0x1005, (word(1), word(2))),
                   packet(0x1009, ()), packet(0x101c, (word(0),)),
                   packet(0x1012, (wide('Z:/*'), b'\0', b'\0', word(0))),
                   packet(0x1013, (word(1), word(0))),
                   packet(0x1022, (wide('Z:/x'), b'\0' * 39))]
        # The structural parser must reject truncated padding and uint32 lengths.
        bad = bytearray(packet(0x1001, (b'xx', word(0))))
        struct.pack_into('<I', bad, 24, 0xffffffff)
        invalid.append(bytes(bad))
        for request in invalid:
            with patch.object(self.backend, 'operate') as operate:
                with self.assertRaises(MalformedRequest):
                    respond(self.backend, 17, request)
                operate.assert_not_called()

    def test_unknown_semantics_do_not_call_backend_or_invent_responses(self):
        unknown = [                   packet(0x101a, (word(4), word(2), word(0))),
                   packet(0x1016, ()),
                   packet(0x1022, (wide('Z:/sample'),
                          struct.pack('<10I', 0xf, 0, 0, 0x700, 0, 0, 1, 0, 1, 0)))]
        for request in unknown:
            with patch.object(self.backend, 'operate') as operate:
                with self.assertRaises(UnsupportedOperation):
                    respond(self.backend, 17, request)
                operate.assert_not_called()

    def test_move_and_file_detail_wire_results(self):
        self.assertEqual(self.call(0x100c, wide('Z:/sample'), wide('Z:/copy'), word(3)),
                         (word(0),))
        self.assertEqual((self.root / 'Z' / 'copy').read_bytes(), self.sample)
        self.assertTrue((self.root / 'Z' / 'sample').exists())
        info = (self.root / 'Z' / 'copy').stat()
        self.assertEqual(self.call(0x1025, wide('Z:/copy')),
                         (word(0), struct.pack('<3Q', info.st_mtime_ns // 1000000000,
                                               info.st_atime_ns // 1000000000,
                                               info.st_ctime_ns // 1000000000)))

    def test_find_family_and_xdelete_canonical_responses(self):
        (self.root / 'Z' / 'one.dat').write_bytes(b'one')
        result = self.call(0x1012, wide('Z:/*.dat'), b'\0', b'\0', word(64))
        handle, = struct.unpack('<I', result[0])
        self.assertEqual(len(result[1]), 52)
        self.assertEqual(result[2], wide('one.dat'))
        self.assertEqual(self.call(0x1013, word(handle), word(64)),
                         (word(-6), bytes(52), b''))
        self.assertEqual(self.call(0x1014, word(handle)), (word(0),))
        target = self.root / 'Z' / 'tree'
        target.mkdir()
        (target / 'a').write_bytes(b'a')
        self.assertEqual(self.call(0x1018, wide('Z:/tree'), word(0x1c)), (word(2),))

    def test_stale_and_stopped_lifecycle_never_emit_reply(self):
        request = packet(0x1001, (wide('Z:/new'), word(0x20000)))
        with patch.object(self.backend, 'operate') as operate:
            with self.assertRaises(StaleGeneration):
                respond(self.backend, 18, request)
            operate.assert_not_called()
        self.backend.shutdown()
        with self.assertRaises(StaleGeneration):
            respond(self.backend, 17, request)

    def test_padding_is_canonicalized_and_payloads_hidden_in_repr(self):
        request = bytearray(packet(0x1001, (wide('Z:/sample'), word(0x700))))
        parsed = decode_request(bytes(request))
        self.assertNotIn('sample', repr(parsed))
        self.assertEqual(parsed.args[0], wide('Z:/sample'))
        reply = respond(self.backend, 17, bytes(request))
        self.assertEqual(len(reply) % 4, 0)


# The oracle decodes and re-encodes actual adapter input/output bodies using the
# same C unit used by the kernel. stdin/stdout contain synthetic bytes only.
C_ORACLE = r'''
#include <stdio.h>
#include <string.h>
#include <linux/unaligned.h>
#include "ccci-fs-protocol.h"
int main(void) {
 u8 in[CCCI_FS_MESSAGE_MAX+1],out[CCCI_FS_MESSAGE_MAX];
 struct ccci_fs_message message;size_t n=fread(in,1,sizeof(in),stdin);int ret;
 if(n<24||n>CCCI_FS_MESSAGE_MAX||get_unaligned_le32(in+4)!=n)return 1;
 ret=ccci_fs_decode(in+16,n-16,&message);if(ret)return 2;
 memcpy(out,in,16);
 ret=ccci_fs_encode(out+16,sizeof(out)-16,message.operation,message.args,message.argc);
 if(ret<0||ret+16!=(int)n)return 3;
 return fwrite(out,1,n,stdout)==n?0:4;
}
'''


class ActualCInteropTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='modem-fs-wire-c-')
        root = Path(cls.temp.name)
        inc = root / 'linux'
        inc.mkdir()
        (inc / 'types.h').write_text('#pragma once\n#include <stdint.h>\n#include <stdbool.h>\n'
                                   '#include <stddef.h>\ntypedef uint8_t u8;'
                                   'typedef uint32_t u32;\n')
        (inc / 'errno.h').write_text('#include <asm-generic/errno.h>\n')
        (inc / 'string.h').write_text('#include <string.h>\n')
        (inc / 'unaligned.h').write_text(
            '#pragma once\n#include <linux/types.h>\n'
            'static inline u32 get_unaligned_le32(const void *p){const u8 *b=p;'
            'return (u32)b[0]|(u32)b[1]<<8|(u32)b[2]<<16|(u32)b[3]<<24;}\n'
            'static inline void put_unaligned_le32(u32 v,void *p){u8 *b=p;'
            'for(unsigned i=0;i<4;i++)b[i]=v>>(8*i);}\n')
        (root / 'oracle.c').write_text(C_ORACLE)
        source = K / 'drivers/misc/mediatek/ccci'
        cls.oracle = root / 'oracle'
        subprocess.run(['cc', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                        '-no-pie', '-I' + str(root), '-I' + str(source),
                        str(source / 'ccci-fs-protocol.c'), str(root / 'oracle.c'),
                        '-o', str(cls.oracle)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_actual_c_decodes_and_roundtrips_synthetic_canonical_exchanges(self):
        with tempfile.TemporaryDirectory(prefix='modem-fs-wire-work-') as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            marker = root / MARKER
            marker.write_bytes(ACKNOWLEDGEMENT)
            marker.chmod(0o600)
            (root / 'Z').mkdir()
            (root / 'Z' / 'sample').write_bytes(bytes(range(256)) * 64)
            backend = WorkingCopy(root, 9)
            try:
                control = struct.pack('<10I', 0x1f, 0, 0, 0x700, 0, 0, 1, 0, MAX_IO, 0)
                requests = [packet(0x101c, ()),
                            packet(0x101a, (word(4), word(2), word(12))),
                            packet(0x1001, (wide('Z:/missing'), word(0x700))),
                            packet(0x1022, (wide('Z:/sample'), control)),
                            packet(0x1022, (wide('Z:/missing'), control)),
                            packet(0x100c, (wide('Z:/sample'), wide('Z:/copy'), word(3))),
                            packet(0x1025, (wide('Z:/copy'),)),
                            packet(0x1025, (wide('T:/missing'),)),
                            packet(0x1012, (wide('R:/missing/*.*'), b'\0', b'\0', word(64))),
                            packet(0x1007, (wide('Z:/child'),)),
                            packet(0x1001, (wide('Z:/sample'), word(0x10400))),
                            packet(0x1002, (word(1), word(64), word(0))),
                            packet(0x1009, (word(1),)),
                            packet(0x1004, (word(1), b'\0\xff\xfe\x80', word(4))),
                            packet(0x1002, (word(1), word(-4), word(1))),
                            packet(0x1003, (word(1), word(4))),
                            packet(0x1005, (word(1),)),
                            packet(0x1012, (wide('Z:/sample'), b'\0', b'\0', word(64))),
                            packet(0x1013, (word(1), word(64))),
                            packet(0x1014, (word(1),)),
                            packet(0x1018, (wide('Z:/child'), word(0x1c)))]
                for request in requests:
                    reply = respond(backend, 9, request)
                    for data in (request, reply):
                        result = subprocess.run([str(self.oracle)], input=data,
                                                stdout=subprocess.PIPE, check=True)
                        self.assertEqual(result.stdout, data)
            finally:
                backend.shutdown()


if __name__ == '__main__':
    unittest.main()
