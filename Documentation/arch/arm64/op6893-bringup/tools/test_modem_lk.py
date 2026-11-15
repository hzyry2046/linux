#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile and exercise the real CCCI parser and FDT merger on the host.

Only synthetic tag payloads are used. The optional --lk-dtb is an offline FDT
fixture: only its modem header is inspected, never physical modem memory.
"""
import argparse
import ctypes as C
from pathlib import Path
import struct
import subprocess
import tempfile

KERNEL = Path(__file__).resolve().parents[5]


class Region(C.Structure):
    _fields_ = [('base', C.c_uint64), ('size', C.c_uint64)]


class Header(C.Structure):
    _fields_ = [('base', C.c_uint64), ('size', C.c_uint32),
                ('version', C.c_uint32), ('count', C.c_uint32)]


class Tag(C.Structure):
    _fields_ = [('offset', C.c_uint32), ('data', C.c_uint32), ('size', C.c_uint32)]


class Layout(C.Structure):
    _fields_ = [('smem', Region), ('ap_md1', Region), ('ccb', Region),
                ('ccb_present', C.c_bool)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board-dtb', type=Path)
    parser.add_argument('--lk-dtb', type=Path)
    parser.add_argument('--header-property', type=Path)
    args = parser.parse_args()
    assert bool(args.board_dtb) == bool(args.lk_dtb), 'Pass both DTB fixtures'
    with tempfile.TemporaryDirectory(prefix='op6893-modem-test-') as directory:
        tmp = Path(directory)
        inc = tmp / 'linux'
        inc.mkdir()
        (inc / 'types.h').write_text('''#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
typedef uint64_t u64;
typedef uint32_t u32;
typedef uint8_t u8;
''')
        (inc / 'init.h').write_text('#include <linux/types.h>\n#define __init\n')
        (inc / 'errno.h').write_text('#include <asm-generic/errno.h>\n')
        (inc / 'limits.h').write_text('#include <linux/types.h>\n#define U64_MAX UINT64_MAX\n')
        (inc / 'string.h').write_text('#include <string.h>\n')
        (inc / 'kernel.h').write_text('#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))\n')
        (inc / 'libfdt.h').write_text('#include <libfdt.h>\n')
        (inc / 'unaligned.h').write_text('''#pragma once
#include <linux/types.h>
static inline u32 get_unaligned_le32(const void *data) {
 const u8 *p=data;
 return (u32)p[0] | (u32)p[1]<<8 | (u32)p[2]<<16 | (u32)p[3]<<24;
}
static inline u64 get_unaligned_le64(const void *data) {
 const u8 *p=data;
 return (u64)get_unaligned_le32(p) | (u64)get_unaligned_le32(p+4)<<32;
}
static inline u64 get_unaligned_be64(const void *data) {
 const u8 *p=data; u64 result=0;
 for (unsigned i=0;i<8;i++) result=(result<<8)|p[i];
 return result;
}
''')
        wrapper = tmp / 'wrapper.c'
        wrapper.write_text('''#include <linux/soc/mediatek/ccci-lk.h>
int decode(const void *p, size_t n, struct ccci_lk_header *h) {
 return ccci_lk_decode_header(p,n,h);
}
bool contains(const struct ccci_lk_region *r, u64 b, u64 n) {
 return ccci_lk_contains(r,b,n);
}
''')
        common = ['cc', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                  '-Wno-sign-compare', '-fsanitize=undefined',
                  '-fno-sanitize-recover=all', '-I'+str(tmp),
                  '-I'+str(KERNEL/'include')]
        lib = tmp / 'test.so'
        subprocess.run(common + ['-shared', '-fPIC', str(wrapper),
                       str(KERNEL/'drivers/misc/mediatek/ccci/ccci-lk.c'),
                       str(KERNEL/'arch/arm64/kernel/op6893-fdt.c'),
                       '-lfdt', '-o', str(lib)], check=True)
        api = C.CDLL(str(lib))
        api.decode.argtypes = [C.c_void_p, C.c_size_t, C.POINTER(Header)]
        api.contains.argtypes = [C.POINTER(Region), C.c_uint64, C.c_uint64]
        api.contains.restype = C.c_bool
        api.ccci_lk_parse.argtypes = [C.POINTER(Header), C.c_void_p, C.c_size_t,
                                     C.POINTER(Region), C.POINTER(Region),
                                     C.POINTER(Tag), C.POINTER(Layout)]
        nc, cached = Region(0x8e000000, 0x1800000), Region(0x88000000, 0x4960000)
        header = Header()
        raw_header = struct.pack('<QIiiiI4i4x', 0xbff70000, 248, 0, 3, 2, 1, 0, 0, 0, 0)
        assert api.decode(raw_header, len(raw_header), C.byref(header)) == 0
        assert header.base == 0xbff70000 and header.count == 2
        for offset, fmt, value in [(8, '<I', 0), (8, '<I', 65537),
                                   (12, '<i', -1), (16, '<i', 1),
                                   (16, '<i', 4), (20, '<i', -1),
                                   (20, '<i', 129), (24, '<I', 0),
                                   (24, '<I', 3), (28, '<i', -1),
                                   (40, '<i', 1), (0, '<Q', 2**64-32)]:
            bad = bytearray(raw_header)
            struct.pack_into(fmt, bad, offset, value)
            assert api.decode(bytes(bad), len(bad), C.byref(header)) < 0
            assert bytes(header) == bytes(C.sizeof(Header))
        for length in [0, 1, 28, 44, 47, 49, 64]:
            assert api.decode(raw_header + bytes(64), length, C.byref(header)) < 0
        padded = bytearray(raw_header)
        padded[44:] = b'pad!'
        assert api.decode(bytes(padded), 48, C.byref(header)) == 0
        assert not api.contains(C.byref(Region(2**64-10, 20)), 2**64-5, 1)
        assert not api.contains(C.byref(nc), nc.base+nc.size, 1)
        assert api.contains(C.byref(nc), nc.base, nc.size)
        print('PASS: header ABI, versions, lengths, errors, flags, padding and interval overflow')

        if args.header_property:
            live = args.header_property.read_bytes()
            assert api.decode(live, len(live), C.byref(header)) == 0
            assert api.contains(C.byref(Region(0xbff70000, 0x10000)),
                                header.base, header.size)
            print('PASS: supplied current-boot header decodes inside the board tag reservation')

        def fixture():
            raw = bytearray(248)
            struct.pack_into('<64sIII', raw, 0, b'smem_layout', 160, 40, 76)
            struct.pack_into('<64sIII', raw, 76, b'ccb_info', 200, 16, 0)
            struct.pack_into('<Q7I4x', raw, 160, nc.base, 0, 0x100000, 0, 0, 0, 0, nc.size)
            struct.pack_into('<QI4x', raw, 200, cached.base+0x10000, 0x20000)
            return raw

        workspace = (Tag * 128)()
        layout = Layout()

        def parse(raw, count=2, version=3, size=None, length=None):
            h = Header(0xbff70000, len(raw) if size is None else size, version, count)
            C.memset(C.byref(layout), 0xa5, C.sizeof(layout))
            ret = api.ccci_lk_parse(C.byref(h), bytes(raw), len(raw) if length is None else length,
                                    C.byref(nc), C.byref(cached), workspace, C.byref(layout))
            if ret:
                assert bytes(layout) == bytes(C.sizeof(layout)), 'Partial result escaped'
            return ret

        assert parse(fixture()) == 0
        assert layout.ap_md1.base == nc.base and layout.ap_md1.size == 0x100000
        assert layout.ccb_present and layout.ccb.base == cached.base+0x10000
        assert parse(fixture(), version=2) == 0
        for off, fmt, val in [(64, '<I', 2**32-1), (68, '<I', 2**32-1),
                              (72, '<I', 0), (72, '<I', 1), (72, '<I', 76+1),
                              (148, '<I', 76), (148, '<I', 247),
                              (140, '<I', 160), (64, '<I', 76),
                              (68, '<I', 39), (144, '<I', 15),
                              (160, '<Q', nc.base-1), (192, '<I', nc.size+1),
                              (168, '<I', nc.size), (172, '<I', 0),
                              (180, '<I', 1),
                              (200, '<Q', cached.base+cached.size),
                              (208, '<I', 2**32-1)]:
            bad = fixture()
            struct.pack_into(fmt, bad, off, val)
            assert parse(bad) < 0, (off, fmt, val)
        for bad in [bytearray(248), fixture()[:75]]:
            assert parse(bad) < 0
        for mode in range(4):
            bad = fixture()
            if mode == 0:
                bad[:64] = b'x'*64
            elif mode == 1:
                bad[76:140] = bad[:64]
            elif mode == 2:
                bad[:64] = b'unknown'.ljust(64, b'\0')
            else:
                bad[76:140] = b'private_unknown'.ljust(64, b'\0')
                assert parse(bad) == 0 and not layout.ccb_present
                continue
            assert parse(bad) < 0
        for count in [0, 129, 2**32-1]:
            assert parse(fixture(), count=count) < 0
        assert parse(fixture(), size=249) < 0
        assert parse(fixture(), version=4) < 0
        last = fixture()
        struct.pack_into('<I', last, 148, len(last))
        assert parse(last) == 0
        # Exercise the maximum accepted chain, including a late back-edge.
        count = 128
        long_chain = bytearray(count*76+40)
        for i in range(count):
            name = b'smem_layout' if i == 0 else f'unknown_{i}'.encode()
            struct.pack_into('<64sIII', long_chain, i*76, name,
                             count*76 if i == 0 else len(long_chain),
                             40 if i == 0 else 0,
                             (i+1)*76 if i+1 < count else 0)
        long_chain[count*76:] = fixture()[160:200]
        assert parse(long_chain, count=count) == 0
        struct.pack_into('<I', long_chain, (count-2)*76+72, 76)
        assert parse(long_chain, count=count) < 0
        print('PASS: synthetic SMEM/CCB, names, cycles, header/payload overlaps, truncated fields and reservation bounds')

        # Run the actual parser with exact-sized heap buffers under ASan/UBSan.
        fuzz = tmp/'fuzz.c'
        fuzz.write_text('''#include <stdlib.h>
#include <string.h>
#include "ccci-lk.h"
static u32 seed=0x6893;
static u32 next(void) { seed=seed*1664525+1013904223; return seed; }
int main(void) {
 struct ccci_lk_tag w[CCCI_LK_MAX_TAGS]; struct ccci_lk_layout l;
 struct ccci_lk_region r={0,0xffffffff};
 for (unsigned i=0;i<20000;i++) {
  unsigned n=next()%1024; unsigned char *p=malloc(n?n:1);
  for (unsigned j=0;j<n;j++) p[j]=next()>>24;
  struct ccci_lk_header h={.size=n,.version=2+(i&1),.count=next()%140};
  if (n>=76 && (i&1)) { memset(p,0,64); memcpy(p,"unknown",7); }
  ccci_lk_parse(&h,p,n,&r,&r,w,&l); free(p);
 }
 return 0;
}
''')
        exe = tmp/'fuzz'
        subprocess.run(common + ['-fsanitize=address',
                       '-I'+str(KERNEL/'drivers/misc/mediatek/ccci'), str(fuzz),
                       str(KERNEL/'drivers/misc/mediatek/ccci/ccci-lk.c'),
                       '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
        print('PASS: 20000 bounded random inputs under AddressSanitizer and UBSan')

        if args.board_dtb:
            test_merge(api, args.board_dtb, args.lk_dtb)


def test_merge(api, board_path, lk_path):
    for name, argv, restype in [
        ('op6893_merge_fdt', [C.c_void_p, C.c_int, C.c_void_p, C.c_void_p], C.c_int),
        ('fdt_open_into', [C.c_void_p, C.c_void_p, C.c_int], C.c_int),
        ('fdt_path_offset', [C.c_void_p, C.c_char_p], C.c_int),
        ('fdt_getprop', [C.c_void_p, C.c_int, C.c_char_p, C.POINTER(C.c_int)], C.c_void_p),
        ('fdt_setprop', [C.c_void_p, C.c_int, C.c_char_p, C.c_void_p, C.c_int], C.c_int),
        ('fdt_delprop', [C.c_void_p, C.c_int, C.c_char_p], C.c_int),
        ('fdt_set_name', [C.c_void_p, C.c_int, C.c_char_p], C.c_int),
    ]:
        fn = getattr(api, name)
        fn.argtypes, fn.restype = argv, restype
    board = C.create_string_buffer(board_path.read_bytes())
    original = C.create_string_buffer(lk_path.read_bytes())

    def clone(src=original):
        out = C.create_string_buffer(1024*1024)
        assert api.fdt_open_into(src, out, len(out)) == 0
        return out

    def node(tree, path):
        n = api.fdt_path_offset(tree, path.encode())
        assert n >= 0, path
        return n

    def prop(tree, path, name):
        length = C.c_int()
        p = api.fdt_getprop(tree, node(tree, path), name.encode(), C.byref(length))
        return C.string_at(p, length.value) if p else None

    def setprop(tree, path, name, raw):
        assert api.fdt_setprop(tree, node(tree, path), name.encode(), raw, len(raw)) == 0

    def delete(tree, path):
        assert api.fdt_delprop(tree, node(tree, path), b'ccci,modem_info_v2') == 0

    def merged(src, b=board):
        out = C.create_string_buffer(1024*1024)
        assert api.op6893_merge_fdt(out, len(out), b, src) == 0
        assert prop(out, '/chosen', 'bootargs') == prop(b, '/chosen', 'bootargs')
        assert api.fdt_path_offset(out, b'/mddriver') < 0
        return prop(out, '/chosen', 'ccci,modem_info_v2')

    header = prop(original, '/chosen', 'ccci,modem_info_v2')
    assert len(header) == 48
    assert merged(original) == header
    for path in ['/chosen', '/mddriver']:
        src = clone()
        delete(src, path)
        assert merged(src) == header
    for offset, fmt, value in [(0, '<Q', 0x40000000), (8, '<I', 65537),
                               (16, '<I', 99), (20, '<I', 0),
                               (24, '<I', 3), (28, '<I', 1)]:
        bad = bytearray(header)
        struct.pack_into(fmt, bad, offset, value)
        for same in [False, True]:
            src = clone()
            setprop(src, '/chosen', 'ccci,modem_info_v2', bytes(bad))
            if same:
                setprop(src, '/mddriver', 'ccci,modem_info_v2', bytes(bad))
            assert merged(src) is None
    for raw in [b'', header[:-1], header+b'junk']:
        src = clone()
        setprop(src, '/chosen', 'ccci,modem_info_v2', raw)
        assert merged(src) is None
    src = clone()
    assert api.fdt_set_name(src, node(src, '/chosen'), b'chosen@0') == 0
    assert merged(src) == header
    src = clone()
    setprop(src, '/reserved-memory/mblock-22-ccci_tag_mem', 'reg',
            struct.pack('>QQ', 0xbff80000, 0x10000))
    assert merged(src) is None
    src = clone()
    delete(src, '/chosen')
    delete(src, '/mddriver')
    stale = clone(board)
    setprop(stale, '/chosen', 'ccci,modem_info_v2', header)
    assert merged(src, stale) is None
    print('PASS: real merger preserves equal/single-source headers, accepts chosen@0, omits malformed/conflicting/unreserved/stale handoff without blocking AP boot')


if __name__ == '__main__':
    main()
