#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic-only backend tests. Never reads an Android snapshot or device."""

import errno
import os
from pathlib import Path
import struct
import tempfile
import time
import unittest
from unittest.mock import patch

from modem_fs_backend import (ACKNOWLEDGEMENT, MARKER, MAX_HANDLES, MAX_IO,
                              MAX_TREE_DEPTH, UnsupportedOperation, WorkingCopy,
                              fs_error)


def path(value):
    return (value + '\0').encode('utf-16le')


class BackendTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='modem-fs-synthetic-')
        self.root = Path(self.temp.name) / 'work'
        self.root.mkdir(mode=0o700)
        marker = self.root / MARKER
        marker.write_bytes(ACKNOWLEDGEMENT)
        marker.chmod(0o600)
        (self.root / 'Z').mkdir()
        self.seed = Path(self.temp.name) / 'original'
        self.seed.write_bytes(bytes(range(256)))
        # Real independent bytes, never a hardlink into the original snapshot.
        (self.root / 'Z' / 'sample').write_bytes(self.seed.read_bytes())
        self.backend = WorkingCopy(self.root, 7)

    def tearDown(self):
        self.backend.shutdown()
        self.temp.cleanup()

    def call(self, op, *args):
        return self.backend.operate(7, op, *args)

    def test_binary_read_write_size_seek_and_original_untouched(self):
        handle, = self.call(0x1001, path('Z:\\sample'), 0x21010400)
        self.assertEqual(self.call(0x1009, handle), (0, 256))
        self.assertEqual(self.call(0x1002, handle, 64, 0), (64,))
        data = b'\0\xff\xfe\x80\0'
        self.assertEqual(self.call(0x1004, handle, data, len(data)), (0, len(data)))
        self.assertEqual(self.call(0x1002, handle, -len(data), 1), (64,))
        self.assertEqual(self.call(0x1003, handle, len(data)), (0, len(data), data))
        with patch('modem_fs_backend.os.fsync', wraps=os.fsync) as sync:
            self.assertEqual(self.call(0x1005, handle), (0,))
            sync.assert_called_once()
        self.assertEqual(self.seed.read_bytes(), bytes(range(256)))
        self.assertEqual(self.call(0x1005, handle), (-10,))
        self.assertEqual(self.call(0x1003, handle, 1), (-10, 0, b''))

    def test_readonly_missing_and_create_truncate(self):
        self.assertEqual(self.call(0x1001, path('S:\\missing'), 0x700), (-9,))
        handle, = self.call(0x1001, path('Z:\\sample'), 0x700)
        self.assertEqual(self.call(0x1004, handle, b'x', 1), (-18, 0))
        with patch('modem_fs_backend.os.fsync') as sync:
            self.assertEqual(self.call(0x1005, handle), (0,))
            sync.assert_not_called()
        handle, = self.call(0x1001, path('Z:\\sample'), 0x20400)
        self.assertEqual(self.call(0x1009, handle), (0, 0))
        self.call(0x1005, handle)
        handle, = self.call(0x1001, path('Z:\\new'), 0x10400)
        self.assertGreater(handle, 0)
        self.call(0x1005, handle)
        self.assertEqual(self.call(0x1007, path('Z:\\child\\')), (0,))
        self.assertEqual(self.call(0x1007, path('Q:\\child')), (-9,))

    def test_flags_and_close_sync_errors_do_not_leak_handles(self):
        for flags in (0x10000, 0x20000, 0x1000000, 0x21010400):
            handle, = self.call(0x1001, path('Z:\\sample'), flags)
            fd = self.backend.handles[handle][0]
            with patch('modem_fs_backend.os.fsync',
                       side_effect=OSError(errno.EIO, 'synthetic')):
                self.assertEqual(self.call(0x1005, handle), (-18,))
            with self.assertRaises(OSError):
                os.fstat(fd)
            self.assertNotIn(handle, self.backend.handles)

    def test_utf16_and_traversal_rejected_before_file_open(self):
        for value in ('Z:\\..\\original', 'Z:\\a..b', 'Z:\\a\\.\\b',
                      'Z:sample', '/sample', 'z:\\sample', 'Z:/',
                      'Z:\\sample\0junk'):
            self.assertEqual(self.call(0x1001, path(value), 0x20400), (-16,))
        for value in (b'\x00', b'\x00\xd8', b''):
            self.assertEqual(self.call(0x1001, value, 0x700), (-16,))
        self.assertEqual(self.seed.read_bytes(), bytes(range(256)))

    def test_drive_root_attributes_and_create(self):
        self.assertEqual(self.call(0x1010, path('Z:')), (0x10,))
        self.assertEqual(self.call(0x1010, path('Z:\\')), (0x10,))
        self.assertEqual(self.call(0x1010, path('U:')), (-9,))
        self.assertEqual(self.call(0x1007, path('Z:')), (-18,))
        self.assertEqual(self.call(0x1007, path('W:')), (0,))
        self.assertEqual(self.call(0x1010, path('W:')), (0x10,))

    def test_readonly_directory_open_and_size(self):
        (self.root / 'Z' / 'nvram').mkdir()
        handle, = self.call(0x1001, path('Z:\\nvram'), 0x900)
        self.assertGreater(handle, 0)
        self.assertGreaterEqual(self.call(0x1009, handle)[1], 0)
        self.assertEqual(self.call(0x1005, handle), (0,))
        for flags in (0x10000, 0x20000, 0x200):
            self.assertEqual(self.call(0x1001, path('Z:\\nvram'), flags), (-16,))

    def test_restore_without_bin_region_fails_closed(self):
        self.assertEqual(self.call(0x1021, path('Z:/NVRAM/NVD_DATA/SM21_003'),
                                   b'\0\0\0\0', b'\0\0\0\0'), (-18,))

    def test_get_attributes_readonly_and_directory_bits(self):
        (self.root / 'Z' / 'dir').mkdir()
        (self.root / 'Z' / 'ro').write_bytes(b'x')
        (self.root / 'Z' / 'ro').chmod(0o444)
        self.assertEqual(self.call(0x1010, path('Z:/sample')), (0,))
        self.assertEqual(self.call(0x1010, path('Z:/ro')), (1,))
        self.assertEqual(self.call(0x1010, path('Z:/dir')), (0x10,))
        self.assertEqual(self.call(0x1010, path('Z:/missing')), (-9,))

    def test_get_disk_info_record_matches_vendor_fields(self):
        status, record = self.call(0x100e, path('Z:'), b'\0\0\0\0')
        self.assertEqual(status, 0)
        self.assertEqual(len(record), 84)
        sector, total, free = struct.unpack_from('<III', record, 0x30)
        cluster, = struct.unpack_from('<I', record, 0x40)
        self.assertEqual((sector, cluster), (512, 512))
        self.assertGreater(total, 0)
        self.assertGreaterEqual(free, 0)
        self.assertEqual(record[:0x30], bytes(0x30))
        self.assertEqual(record[0x3c:0x40], bytes(4))
        self.assertEqual(record[0x44:], bytes(len(record) - 0x44))
        self.assertEqual(self.call(0x100e, path('C:'), b'\0\0\0\0'), (-16,))

    def test_drive_doubled_separator_matches_one_separator(self):
        # Observed MD request form: "X://md_nv_config.txt" with flag 0x700.
        for value in ('Z://sample', 'Z:\\\\sample', 'Z:///sample'):
            handle, = self.call(0x1001, path(value), 0x700)
            self.assertEqual(self.call(0x1009, handle), (0, 256))
            self.assertEqual(self.call(0x1005, handle), (0,))
        self.assertEqual(self.call(0x1001, path('X://md_nv_config.txt'), 0x700), (-9,))

    def test_symlink_hardlink_and_special_files_cannot_escape_or_truncate(self):
        (self.root / 'Z' / 'link').symlink_to(self.seed)
        (self.root / 'Z' / 'parent').symlink_to(self.seed.parent,
                                                 target_is_directory=True)
        os.link(self.seed, self.root / 'Z' / 'hard')
        os.mkfifo(self.root / 'Z' / 'fifo')
        for target in ('link', 'hard', 'fifo', 'parent/original'):
            self.assertLess(self.call(0x1001, path('Z:/' + target), 0x20400)[0], 0)
        self.assertEqual(self.seed.read_bytes(), bytes(range(256)))
        self.assertEqual(self.backend.handles, {})

    def test_handle_bound_and_generation_revocation(self):
        handles = [self.call(0x1001, path('Z:/sample'), 0x700)[0]
                   for unused in range(MAX_HANDLES)]
        self.assertEqual(len(set(handles)), MAX_HANDLES)
        self.assertEqual(self.call(0x1001, path('Z:/sample'), 0x700), (-5,))
        with patch('modem_fs_backend.os.open') as opener:
            self.assertEqual(self.backend.operate(8, 0x1001, path('Z:/x'),
                                                  0x20400), (-10,))
            opener.assert_not_called()
        fds = [entry[0] for entry in self.backend.handles.values()]
        self.assertEqual(self.backend.shutdown(), 0)
        self.assertEqual(self.call(0x101c), (-10,))
        for fd in fds:
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_cmpt_exact_success_and_short_read(self):
        words = [0x1f, 0, 0, 0x700, 0xdeadbeef, 64, 1, 0xffffffff, 32, 42]
        result = self.call(0x1022, path('Z:/sample'), struct.pack('<10I', *words))
        self.assertEqual(result, (struct.pack('<II', 0x1f, 0), 256, 32,
                                  bytes(range(64, 96))))
        words[5], words[8] = 250, 32
        self.assertEqual(self.call(0x1022, path('Z:/sample'),
                                   struct.pack('<10I', *words))[2:],
                         (6, bytes(range(250, 256))))
        self.assertEqual(self.backend.handles, {})
        self.assertEqual(self.call(0x1022, path('Z:/missing'),
                                   struct.pack('<10I', *words)),
                         (struct.pack('<Ii', 0, -9), 0, 0, b''))
        self.assertEqual(self.backend.handles, {})
        # Bit 0 is mandatory: the vendor serializes {completed=0, error=-18}.
        words[0] = 0x0e
        self.assertEqual(self.call(0x1022, path('Z:/sample'),
                                   struct.pack('<10I', *words)),
                         (struct.pack('<Ii', 0, -18), 0, 0, b''))
        # Without the close bit the file is closed but completion stays 0x0f.
        words[0] = 0x0f
        self.assertEqual(self.call(0x1022, path('Z:/sample'),
                                   struct.pack('<10I', *words))[0],
                         struct.pack('<II', 0x0f, 0))
        # Observed MD variant: open+size+close only.
        words[0], words[3] = 0x13, 0x100
        self.assertEqual(self.call(0x1022, path('Z:/sample'),
                                   struct.pack('<10I', *words)),
                         (struct.pack('<II', 0x13, 0), 256, 0, b''))
        words[0] = 0x20
        with self.assertRaises(UnsupportedOperation):
            self.call(0x1022, path('Z:/sample'), struct.pack('<10I', *words))

    def test_bounds_and_unknown_semantics(self):
        handle, = self.call(0x1001, path('Z:/sample'), 0x700)
        with self.assertRaises(ValueError):
            self.call(0x1003, handle, MAX_IO + 1)
        with self.assertRaises(ValueError):
            self.call(0x1004, handle, b'x', 2)
        self.assertEqual(self.call(0x100c, path('Z:/sample'), path('Z:/new'), 0),
                         (-2,))
        self.assertEqual(self.call(0x1025, path('Z:/missing')), (-9, bytes(24)))
        self.assertEqual(self.call(0x1012, path('R:/tls/*.*'), 0, 0, 64),
                         (-9, bytes(52), b''))
        self.assertEqual(self.call(0x1012, path('Z:/*.*'), 0, 0, 64),
                         (-6, bytes(52), b''))
        info = (self.root / 'Z' / 'sample').stat()
        self.assertEqual(self.call(0x1025, path('Z:/sample')),
                         (0, struct.pack('<3Q', info.st_mtime_ns // 1000000000,
                                         info.st_atime_ns // 1000000000,
                                         info.st_ctime_ns // 1000000000)))
        self.assertEqual(self.call(0x101a, 4, 2, 12), (ord('Z'),))
        self.assertEqual(self.call(0x101a, 8, 2, 12), (-2,))
        for query in ((0, 2, 12), (4, 3, 12), (4, 2, 0), (4,), ()):
            with self.assertRaises(UnsupportedOperation):
                self.call(0x101a, *query)
        self.assertEqual(self.call(0x101c), (0,))
        self.assertEqual(fs_error(OSError(errno.EACCES, 'synthetic')), -16)
        self.assertEqual(fs_error(OSError(errno.EMFILE, 'synthetic')), -5)

    def test_move_copies_regular_file_without_deleting_source(self):
        source, target = path('Z:/sample'), path('Z:/new')
        for flags in (1, 3, 0x10001, 0x10003):
            self.assertEqual(self.call(0x100c, source, target, flags), (0,))
            self.assertEqual((self.root / 'Z' / 'new').read_bytes(), bytes(range(256)))
            self.assertEqual((self.root / 'Z' / 'sample').read_bytes(), bytes(range(256)))
        self.assertEqual(self.call(0x100c, source, target, 2), (-18,))
        self.assertEqual(self.call(0x100c, source, target, 0x10002), (0,))
        self.assertFalse((self.root / 'Z' / 'new').exists())
        self.assertEqual(self.call(0x100c, source, target, 0x10002), (-18,))
        for flags in (0, 4, 0x20001):
            self.assertEqual(self.call(0x100c, source, target, flags), (-2,))
        self.assertEqual(self.call(0x100c, source, source, 1), (-2,))

    def test_move_mode_checks_and_private_paths(self):
        source, target = path('Z:/sample'), path('Z:/new')
        original = self.root / 'Z' / 'sample'
        original.chmod(0o444)
        self.assertEqual(self.call(0x100c, source, target, 3), (-45,))
        self.assertEqual(self.call(0x100c, source, target, 1), (0,))
        (self.root / 'Z' / 'new').chmod(0o444)
        self.assertEqual(self.call(0x100c, source, target, 0x10001), (-45,))
        (self.root / 'Z' / 'dir').mkdir()
        self.assertEqual(self.call(0x100c, source, path('Z:/dir'), 0x10001), (0,))
        self.assertTrue((self.root / 'Z' / 'dir').is_file())
        self.assertEqual(self.call(0x100c, source, path('Z:/../outside'), 1), (-16,))
        (self.root / 'Z' / 'link').symlink_to(self.seed)
        self.assertEqual(self.call(0x100c, source, path('Z:/link'), 1), (-16,))
        self.assertEqual(self.seed.read_bytes(), bytes(range(256)))

    def test_move_stages_source_before_destination_truncate(self):
        target = self.root / 'Z' / 'new'
        target.write_bytes(b'unchanged')
        with patch('modem_fs_backend.os.read', return_value=b''):
            self.assertEqual(self.call(0x100c, path('Z:/sample'), path('Z:/new'), 1), (-1,))
        self.assertEqual(target.read_bytes(), b'unchanged')
        with patch('modem_fs_backend.os.write', return_value=0):
            self.assertEqual(self.call(0x100c, path('Z:/sample'), path('Z:/new'), 1), (-1,))
        self.assertEqual(target.read_bytes(), b'')
        self.assertTrue((self.root / 'Z' / 'sample').exists())

    def test_cmpt_failure_stage_masks_and_safe_zero_metadata(self):
        control = struct.pack('<10I', 0x1f, 0, 0, 0x700, 123, 64, 1, 123, 32, 123)
        with patch('modem_fs_backend.os.lseek', side_effect=OSError(errno.EIO, 'synthetic')):
            self.assertEqual(self.call(0x1022, path('Z:/sample'), control),
                             (struct.pack('<Ii', 3, -18), 256, 0, b''))
        with patch('modem_fs_backend.os.read', side_effect=OSError(errno.EIO, 'synthetic')):
            self.assertEqual(self.call(0x1022, path('Z:/sample'), control),
                             (struct.pack('<Ii', 7, -18), 256, 0, b''))
        with patch.object(self.backend, '_regular',
                          side_effect=[(self.root / 'Z' / 'sample').stat(),
                                       OSError(errno.EIO, 'synthetic')]):
            self.assertEqual(self.call(0x1022, path('Z:/sample'), control),
                             (struct.pack('<Ii', 1, -18), 0, 0, b''))
        self.assertEqual(self.backend.handles, {})
        real_close = self.backend._close
        def failing_close(handle):
            real_close(handle)
            return -18
        with patch.object(self.backend, '_close', side_effect=failing_close):
            result = self.call(0x1022, path('Z:/sample'), control)
            self.assertEqual(result[:3], (struct.pack('<Ii', 15, -18), 256, 32))
        self.assertEqual(self.backend.handles, {})

    def test_find_family_attributes_names_handles_and_end_of_search(self):
        directory = self.root / 'Z'
        (directory / 'one.dat').write_bytes(b'abc')
        (directory / 'two.dat').write_bytes(b'defg')
        (directory / 'ro.dat').write_bytes(b'r')
        (directory / 'ro.dat').chmod(0o444)
        (directory / 'folder.dat').mkdir()
        handle, entry, name = self.call(0x1012, path('Z:/*.dat'), 0, 0x11, 256)
        self.assertGreater(handle, 0)
        self.assertEqual(len(entry), 52)
        names = {name.decode('utf-16le').rstrip('\0')}
        self.assertEqual(entry[11], 0)
        self.assertEqual(entry[12], 1)
        status, entry, name = self.call(0x1013, handle, 256)
        self.assertEqual(status, 0)
        names.add(name.decode('utf-16le').rstrip('\0'))
        self.assertEqual(names, {'one.dat', 'two.dat'})
        self.assertEqual(self.call(0x1013, handle, 256), (-6, bytes(52), b''))
        self.assertIn(handle, self.backend.searches)
        self.assertEqual(self.call(0x1014, handle), (0,))
        self.assertEqual(self.call(0x1013, handle, 256), (-10, bytes(52), b''))
        self.assertEqual(self.call(0x1014, handle), (-10,))
        handle, entry, name = self.call(0x1012, path('Z:/*.dat'), 0x10, 0, 256)
        self.assertEqual(name, 'folder.dat\0'.encode('utf-16le'))
        self.assertEqual(entry[11], 0x10)
        self.assertEqual(self.call(0x1005, handle), (0,))
        handle, entry, name = self.call(0x1012, path('Z:/*.dat'), 1, 0, 256)
        self.assertEqual(name, 'ro.dat\0'.encode('utf-16le'))
        self.assertEqual(entry[11], 1)
        self.call(0x1014, handle)

    def test_find_vendor_dos_quirks_and_name_truncation(self):
        (self.root / 'Z' / 'length.name').write_bytes(b'x' * 9)
        fixed = time.struct_time((2024, 7, 29, 23, 58, 59, 0, 211, -1))
        with patch('modem_fs_backend.time.localtime', return_value=fixed):
            handle, entry, name = self.call(0x1012, path('Z:/length.name'), 0, 0, 4)
        self.assertEqual(name, 'len\0'.encode('utf-16le'))
        self.assertEqual(entry[12], 0)
        self.assertEqual(struct.unpack_from('<I', entry, 14)[0], 0x59bdbf5b)
        self.assertEqual(entry[14:18], entry[22:26])
        self.assertEqual(struct.unpack_from('<I', entry, 28)[0], 9)
        expected = bytearray(52)
        struct.pack_into('<I', expected, 14, 0x59bdbf5b)
        struct.pack_into('<I', expected, 22, 0x59bdbf5b)
        struct.pack_into('<I', expected, 28, 9)
        self.assertEqual(entry, bytes(expected))
        self.call(0x1014, handle)
        handle, entry, name = self.call(0x1012, path('Z:/length.name'), 0, 0, 1)
        self.assertEqual(name, b'')
        self.assertEqual(entry[12], 0)
        self.call(0x1014, handle)
        with self.assertRaises(ValueError):
            self.call(0x1012, path('Z:/*'), 0, 0, 0)
        raw = os.fsencode(self.root / 'Z') + b'/high\xff.bin'
        fd = os.open(raw, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        handle, entry, name = self.call(0x1012, path('Z:/high?.bin'), 0, 0, 256)
        self.assertEqual(name, b'h\0i\0g\0h\0\xff\0.\0b\0i\0n\0\0\0')
        self.call(0x1014, handle)
        self.assertTrue(self.backend._match(b'a[bc]', b'a[bc]'))
        self.assertFalse(self.backend._match(b'a[bc]', b'ab'))
        self.assertFalse(self.backend._match(b'*.*', b'nodot'))
        self.assertTrue(self.backend._match(b'*a?*b', b'caZzzb'))

    def test_find_private_entries_and_shared_handle_limit(self):
        (self.root / 'Z' / 'link').symlink_to(self.seed)
        self.assertEqual(self.call(0x1012, path('Z:/link'), 0, 0, 64),
                         (-16, bytes(52), b''))
        self.assertEqual(self.backend.searches, {})
        for unused in range(MAX_HANDLES - 1):
            self.call(0x1001, path('Z:/sample'), 0x700)
        handle, entry, name = self.call(0x1012, path('Z:/sample'), 0, 0, 64)
        self.assertEqual(handle, 128)
        self.assertEqual(self.call(0x1001, path('Z:/sample'), 0x700), (-5,))
        self.assertEqual(self.call(0x1012, path('Z:/sample'), 0, 0, 64),
                         (-5, bytes(52), b''))
        search_fd = self.backend.searches[handle].fd
        self.backend.shutdown()
        with self.assertRaises(OSError):
            os.fstat(search_fd)
        self.assertEqual(self.backend.searches, {})

    def test_recursive_xdelete_flags_counts_and_move_directory_destination(self):
        def tree(name):
            target = self.root / 'Z' / name
            (target / 'child').mkdir(parents=True)
            (target / 'a').write_bytes(b'a')
            (target / 'child' / 'b').write_bytes(b'b')
            return target
        target = tree('all')
        self.assertEqual(self.call(0x1018, path('Z:/all'), 0x1c), (4,))
        self.assertFalse(target.exists())
        target = tree('files')
        self.assertEqual(self.call(0x1018, path('Z:/files'), 0x14), (2,))
        self.assertTrue((target / 'child').is_dir())
        self.assertEqual(self.call(0x1018, path('Z:/files'), 0x18), (2,))
        target = tree('top')
        self.assertEqual(self.call(0x1018, path('Z:/top'), 4), (1,))
        self.assertTrue((target / 'child' / 'b').exists())
        self.assertEqual(self.call(0x1018, path('Z:/top'), 16), (0,))
        for flags in (0, 1, 0x20):
            self.assertEqual(self.call(0x1018, path('Z:/top'), flags), (-2,))
        self.assertEqual(self.call(0x1018, path('Z:/sample'), 0x1c), (-2,))
        self.assertEqual(self.call(0x1018, path('Z:/'), 0x1c), (-16,))
        target = tree('move')
        self.assertEqual(self.call(0x100c, path('Z:/sample'), path('Z:/move'), 0x10001), (0,))
        self.assertEqual(target.read_bytes(), bytes(range(256)))
        target = tree('delete_only')
        self.assertEqual(self.call(0x100c, path('Z:/sample'), path('Z:/delete_only'),
                                   0x10002), (4,))
        self.assertFalse(target.exists())
        self.assertTrue((self.root / 'Z' / 'sample').exists())

    def test_recursive_delete_preflight_rejects_links_without_mutating_tree(self):
        target = self.root / 'Z' / 'tree'
        target.mkdir()
        (target / 'safe').write_bytes(b'keep')
        (target / 'outside').symlink_to(self.seed)
        self.assertEqual(self.call(0x1018, path('Z:/tree'), 0x1c), (-16,))
        self.assertEqual((target / 'safe').read_bytes(), b'keep')
        self.assertEqual(self.seed.read_bytes(), bytes(range(256)))
        (target / 'outside').unlink()
        os.link(self.seed, target / 'hard')
        self.assertEqual(self.call(0x1018, path('Z:/tree'), 0x1c), (-16,))
        self.assertEqual((target / 'safe').read_bytes(), b'keep')
        self.assertEqual(self.call(0x100c, path('Z:/tree/safe'), path('Z:/tree'),
                                   0x10001), (-16,))

    def test_recursive_depth_bound_preserves_entire_tree(self):
        target = self.root / 'Z' / 'deep'
        target.mkdir()
        (target / 'safe').write_bytes(b'keep')
        child = target
        for unused in range(MAX_TREE_DEPTH):
            child = child / 'child'
            child.mkdir()
        with self.assertRaises(UnsupportedOperation):
            self.call(0x1018, path('Z:/deep'), 0x1c)
        self.assertEqual((target / 'safe').read_bytes(), b'keep')
        self.assertTrue(child.is_dir())

    def test_marker_is_mandatory_and_private(self):
        marker = self.root / MARKER
        marker.unlink()
        with self.assertRaises(FileNotFoundError):
            WorkingCopy(self.root, 8)
        marker.write_bytes(ACKNOWLEDGEMENT)
        marker.chmod(0o644)
        with self.assertRaises(ValueError):
            WorkingCopy(self.root, 8)


if __name__ == '__main__':
    unittest.main()
