#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic-only backend tests. Never reads an Android snapshot or device."""

import errno
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from modem_fs_backend import (ACKNOWLEDGEMENT, MARKER, MAX_HANDLES, MAX_IO,
                              UnsupportedOperation, WorkingCopy, fs_error)


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
                      'Z:sample', '/sample', 'z:\\sample', 'Z:\\\\sample',
                      'Z:\\sample\0junk'):
            self.assertEqual(self.call(0x1001, path(value), 0x20400), (-16,))
        for value in (b'\x00', b'\x00\xd8', b''):
            self.assertEqual(self.call(0x1001, value, 0x700), (-16,))
        self.assertEqual(self.seed.read_bytes(), bytes(range(256)))

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
        with self.assertRaises(UnsupportedOperation):
            self.call(0x1022, path('Z:/missing'), struct.pack('<10I', *words))
        self.assertEqual(self.backend.handles, {})
        words[0] = 0x0f
        with self.assertRaises(UnsupportedOperation):
            self.call(0x1022, path('Z:/sample'), struct.pack('<10I', *words))

    def test_bounds_and_unknown_semantics(self):
        handle, = self.call(0x1001, path('Z:/sample'), 0x700)
        with self.assertRaises(ValueError):
            self.call(0x1003, handle, MAX_IO + 1)
        with self.assertRaises(ValueError):
            self.call(0x1004, handle, b'x', 2)
        with self.assertRaises(UnsupportedOperation):
            self.call(0x100c, path('Z:/sample'), path('Z:/new'), 0)
        self.assertEqual(self.call(0x1025, path('Z:/missing')), (-9,))
        self.assertEqual(self.call(0x1012, path('R:/tls/*.*'), 0, 0, 0), (-9,))
        with self.assertRaises(UnsupportedOperation):
            self.call(0x1012, path('Z:/*.*'), 0, 0, 0)
        with self.assertRaises(UnsupportedOperation):
            self.call(0x1025, path('Z:/sample'))
        self.assertEqual(self.call(0x101a, 4, 2, 12), (ord('Z'),))
        self.assertEqual(self.call(0x101a, 8, 2, 12), (-2,))
        for query in ((0, 2, 12), (4, 3, 12), (4, 2, 0), (4,), ()):
            with self.assertRaises(UnsupportedOperation):
                self.call(0x101a, *query)
        self.assertEqual(self.call(0x101c), (0,))
        self.assertEqual(fs_error(OSError(errno.EACCES, 'synthetic')), -16)
        self.assertEqual(fs_error(OSError(errno.EMFILE, 'synthetic')), -5)

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
