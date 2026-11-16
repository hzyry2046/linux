#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic pure user RPC fixtures plus actual kernel codec compatibility."""
from dataclasses import FrozenInstanceError
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

from modem_rpc_backend import (MalformedRequest, PropertySnapshot, SarSnapshot,
                               Unavailable, decode_request, respond)

SRC = Path(__file__).resolve().parents[5] / 'drivers/misc/mediatek/ccci'


def request(operation, args=(), slot=2):
    payload = b''.join(struct.pack('<I', len(arg)) + arg + b'\0' * (-len(arg) % 4)
                       for arg in args)
    return struct.pack('<6I', 0x12345678, 24 + len(payload), 0x81230020,
                       slot, operation, len(args)) + payload


def replies(packet):
    # Use request decoder for independently inspecting the encoded reply args.
    header = list(struct.unpack_from('<6I', packet))
    header[2] = header[2] & 0xffff0000 | 32
    header[4] &= 0xffff
    return decode_request(struct.pack('<6I', *header) + packet[24:]).args


class RpcTests(unittest.TestCase):
    def setUp(self):
        self.props = PropertySnapshot(((b'test.value', b'abc'), (b'test.absent', None),
                                       (b'test.empty', b''), (b'test.long', b'x' * 91)))
        self.projects = ((b'test_hw', ((b'test_region', 7),)),)
        self.sar = SarSnapshot(b'test_hw', b'test_region', self.projects)

    def test_property_wire_and_identity(self):
        for key in (b'test.value', b'test.value\0'):
            packet = request(0x400f, (key,))
            reply = respond(packet, properties=self.props)
            self.assertEqual(struct.unpack_from('<6I', reply),
                             (0x12345678, 40, 0x81230021, 2, 0xffff400f, 2))
            self.assertEqual(reply[24:], struct.pack('<IiI', 4, 3, 4) + b'abc\0')
            self.assertEqual(replies(reply), (struct.pack('<i', 3), b'abc\0'))

    def test_absence_only_when_explicit(self):
        for key in (b'test.absent', b'test.empty'):
            reply = respond(request(0x400f, (key,)), properties=self.props)
            self.assertEqual(replies(reply), (b'\0' * 4, b'\0'))
        for properties in (None, PropertySnapshot(())):
            with self.assertRaises(Unavailable):
                respond(request(0x400f, (b'test.unknown',)), properties=properties)
        with self.assertRaises(Unavailable):
            respond(request(0x400f, (b'test',)), properties=self.props)

    def test_property_bounds_and_ignored_extra_arguments(self):
        reply = respond(request(0x400f, (b'test.long',)), properties=self.props)
        self.assertEqual(replies(reply), (struct.pack('<i', 91), b'x' * 91 + b'\0'))
        for argc in range(1, 7):
            reply = respond(request(0x400f, (b'test.value',) + (b'ignored',) * (argc - 1)),
                            properties=self.props)
            self.assertEqual(replies(reply)[1], b'abc\0')
        for args in ((), (b'',), (b'\0',), (b'test\0value',), (b'test.value\0\0',)):
            with self.assertRaises(MalformedRequest):
                respond(request(0x400f, args), properties=self.props)

    def test_sar_source_policy_and_sentinel(self):
        for argc in range(7):
            reply = respond(request(0x4010, (b'ignored',) * argc), sar=self.sar)
            self.assertEqual(replies(reply), (b'\0' * 4, struct.pack('<I', 7)))
        for index in (0, 0xffff, 0xffffffff):
            sar = SarSnapshot(b'x', b'y', ((b'x', ((b'y', index),)),))
            self.assertEqual(replies(respond(request(0x4010), sar=sar)),
                             (b'\0' * 4, struct.pack('<I', index)))
        for hw, region in ((b'absent', b'test_region'), (b'test_hw', b'absent')):
            sar = SarSnapshot(hw, region, self.projects)
            self.assertEqual(replies(respond(request(0x4010), sar=sar)),
                             (b'\0' * 4, struct.pack('<I', 0xffff)))
        with self.assertRaises(Unavailable):
            respond(request(0x4010))

    def test_facts_are_strict_and_immutable(self):
        for facts in ([], ((b'x', bytearray(b'y')),), ((b'x', b'\0'),),
                      ((b'x', b'x' * 92),), ((b'', b'x'),),
                      ((b'x', b'a'), (b'x', b'b'))):
            with self.assertRaises(ValueError):
                PropertySnapshot(facts)
        with self.assertRaises(FrozenInstanceError):
            self.props.facts = ()
        self.assertNotIn('test.value', repr(self.props))
        for index in (-1, True, 0x100000000, b'7'):
            with self.assertRaises(ValueError):
                SarSnapshot(b'x', b'y', ((b'x', ((b'y', index),)),))
        for projects in ((), [], ((b'x', ()),),
                         ((b'x', ((b'y', 1), (b'y', 2))),),
                         ((b'x', ((b'y', 1),)), (b'x', ((b'z', 2),)))):
            with self.assertRaises(ValueError):
                SarSnapshot(b'x', b'y', projects)
        with self.assertRaises(FrozenInstanceError):
            self.sar.product_hw = b'other'
        self.assertNotIn('test_hw', repr(self.sar))

    def test_packet_validation(self):
        valid = request(0x400f, (b'test.value',))
        bad = [b'', bytearray(valid), valid[:-1], valid + b'\0']
        for offset, value in ((4, 0), (8, 33), (12, 3), (16, 0xffff400f), (20, 7),
                              (24, 0xffffffff)):
            packet = bytearray(valid)
            struct.pack_into('<I', packet, offset, value)
            bad.append(bytes(packet))
        for packet in bad:
            with self.assertRaises(MalformedRequest):
                respond(packet, properties=self.props)
        for op in (0x4002, 0x4014, 0x1234):
            with self.assertRaises(Unavailable):
                respond(request(op), properties=self.props, sar=self.sar)
        for slot in range(3):
            reply = respond(request(0x400f, (b'test.value',), slot), properties=self.props)
            self.assertEqual(struct.unpack_from('<I', reply, 12)[0], slot)

    def test_actual_kernel_codec_compatibility(self):
        fixtures = []
        for key in (b'test.value', b'test.absent', b'test.long'):
            req = request(0x400f, (key,))
            fixtures.append((req, respond(req, properties=self.props)))
        for sar in (self.sar, SarSnapshot(b'absent', b'absent', self.projects)):
            req = request(0x4010)
            fixtures.append((req, respond(req, sar=sar)))
        with tempfile.TemporaryDirectory(prefix='op6893-user-rpc-') as directory:
            tmp = Path(directory)
            inc = tmp / 'linux'
            inc.mkdir()
            (inc / 'types.h').write_text('''#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
typedef uint8_t u8; typedef uint32_t u32; typedef int32_t s32;
''')
            (inc / 'errno.h').write_text('#include <asm-generic/errno.h>\n')
            (inc / 'string.h').write_text('#include <string.h>\n')
            (inc / 'unaligned.h').write_text('''#pragma once
#include <linux/types.h>
static inline u32 get_unaligned_le32(const void *p) {
 const u8 *b=p;return (u32)b[0]|(u32)b[1]<<8|(u32)b[2]<<16|(u32)b[3]<<24;
}
static inline void put_unaligned_le32(u32 v,void *p) {
 u8 *b=p;for(unsigned i=0;i<4;i++)b[i]=v>>(i*8);
}
''')
            (tmp / 'test.c').write_text('''
#include <assert.h>
#include <stdio.h>
#include "ccci-rpc-protocol.h"
int main(int argc,char **argv) {
 unsigned char req[2048],reply[2048];struct ccci_rpc_message message;
 assert(argc==3);FILE *f=fopen(argv[1],"rb");assert(f);
 size_t n=fread(req,1,sizeof(req),f);assert(!fclose(f));
 f=fopen(argv[2],"rb");assert(f);size_t m=fread(reply,1,sizeof(reply),f);assert(!fclose(f));
 assert(!ccci_rpc_decode_request(req,n,&message));
 assert(!ccci_rpc_validate_reply(&message,reply,m));return 0;
}
''')
            subprocess.run(['cc', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                            '-no-pie', '-I' + str(tmp), '-I' + str(SRC),
                            str(SRC / 'ccci-rpc-protocol.c'), str(tmp / 'test.c'),
                            '-o', str(tmp / 'test')], check=True)
            for req, reply in fixtures:
                (tmp / 'request').write_bytes(req)
                (tmp / 'reply').write_bytes(reply)
                subprocess.run([str(tmp / 'test'), str(tmp / 'request'),
                                str(tmp / 'reply')], check=True)


if __name__ == '__main__':
    unittest.main()
