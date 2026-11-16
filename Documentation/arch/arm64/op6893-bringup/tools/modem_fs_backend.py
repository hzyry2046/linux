#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline structured FS prototype, not a CCCI daemon or wire codec.

Only caller-provisioned private working copies are accepted. Never point this at
Android mounts or original backups: no import/copy/restore operation is provided.
The marker is an explicit acknowledgement, not proof of snapshot provenance.
No operation prints paths, payloads or file contents. Calls must be serialized.
Move is unsupported (its third argument and copy/replace rules are unknown).
FindFirst/GetFileDetail can report a missing path, but successful result layouts
and wildcard searching are unsupported. CMPT_Read accepts only all-five-step
requests with read-only 0x700 flags; only its success result layout is known.
GetDrive accepts exactly the two observed query tuples, never arbitrary flags.
All other operation codes, directory opens, OTP/device/ioctl access, restart
recovery, copying originals and wire dispatch remain outside this prototype.
An UnsupportedOperation is a local readiness failure, not a vendor response.
"""

import errno
import os
import stat
import struct

MARKER = '.op6893-fs-working-copy'
ACKNOWLEDGEMENT = b'PRIVATE DISPOSABLE MODEM FS WORKING COPY\n'
DRIVES = frozenset('ZXYWVUTSRQ')
MAX_HANDLES = 0x81
MAX_IO = 0x4000
MAX_PATH = 1024


def fs_error(exc):
    """The vendor errors established by static analysis; no host text leaks."""
    return {errno.ENOENT: -9, errno.EACCES: -16, errno.EPERM: -16,
            errno.ELOOP: -16, errno.EMFILE: -5}.get(exc.errno, -18)


class UnsupportedOperation(Exception):
    """Internal readiness failure; must not be serialized as a vendor errno."""


class WorkingCopy:
    """Directory-fd rooted engine; generation is checked on every request.

    Provision root mode 0700, marker mode 0600 with ACKNOWLEDGEMENT contents,
    and zero or more uppercase drive directories. Missing drives stay missing.
    Original backups must live outside root and must not share file hardlinks.
    Returns tuples matching operation response arguments, without wire packing
    except CMPT's documented eight-byte (completed bitmap, error) argument.
    """

    def __init__(self, root, generation):
        if not isinstance(generation, int) or generation <= 0:
            raise ValueError('positive generation required')
        self.root = -1
        self.handles = {}
        self.generation = generation
        self.active = False
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                     os.O_CLOEXEC)
        try:
            info = os.fstat(fd)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise ValueError('working root must be owned and private')
            marker = os.open(MARKER, os.O_RDONLY | os.O_NOFOLLOW |
                             os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=fd)
            try:
                info = os.fstat(marker)
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                        info.st_uid != os.geteuid() or
                        stat.S_IMODE(info.st_mode) != 0o600 or
                        os.read(marker, len(ACKNOWLEDGEMENT) + 1) !=
                        ACKNOWLEDGEMENT):
                    raise ValueError('explicit working-copy marker required')
            finally:
                os.close(marker)
        except BaseException:
            os.close(fd)
            raise
        self.root = fd
        self.active = True

    @staticmethod
    def _path(path):
        if not isinstance(path, bytes) or not path or len(path) > MAX_PATH:
            raise PermissionError(errno.EACCES, 'invalid path')
        try:
            text = path.decode('utf-16le', errors='strict')
        except UnicodeError:
            raise PermissionError(errno.EACCES, 'invalid path') from None
        # One optional terminator, never silently truncate embedded NULs.
        if text.endswith('\0'):
            text = text[:-1]
        text = text.replace('\\', '/')
        if ('\0' in text or '..' in text or len(text) < 3 or
                text[0] not in DRIVES or text[1:3] != ':/'):
            raise PermissionError(errno.EACCES, 'invalid path')
        parts = text[3:].split('/')
        if parts and parts[-1] == '':
            parts.pop()
        if any(not part or part == '.' or ':' in part for part in parts):
            raise PermissionError(errno.EACCES, 'invalid path')
        return [text[0], *parts]

    def _parent(self, path):
        parts = self._path(path)
        fd = os.dup(self.root)
        try:
            for part in parts[:-1]:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY |
                                  os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            return fd, parts[-1]
        except BaseException:
            os.close(fd)
            raise

    @staticmethod
    def _regular(fd):
        info = os.fstat(fd)
        # Also prevents FIFO/device access and modification of hardlinked seeds.
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise PermissionError(errno.EACCES, 'non-private regular file')
        return info

    @staticmethod
    def _flags(flags):
        if not isinstance(flags, int) or flags < 0 or flags > 0xffffffff:
            raise ValueError('invalid open flags')
        result = os.O_RDONLY if flags & 0x100 else os.O_RDWR
        if flags & 0x10000:
            result = os.O_RDWR | os.O_CREAT
        if flags & 0x20000:
            # Defer truncation until fstat rejects hardlinks/special files.
            result = os.O_RDWR | os.O_CREAT
        if flags & 0x10000000:
            result |= os.O_NONBLOCK
        return result | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK

    def _open(self, path, flags):
        if len(self.handles) == MAX_HANDLES:
            return -5
        native_flags = self._flags(flags)
        parent, name = self._parent(path)
        try:
            try:
                info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                if not native_flags & os.O_CREAT:
                    raise
            else:
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise PermissionError(errno.EACCES, 'non-private file')
            fd = os.open(name, native_flags, 0o660, dir_fd=parent)
        finally:
            os.close(parent)
        try:
            self._regular(fd)
            if flags & 0x20000:
                os.ftruncate(fd, 0)
        except BaseException:
            os.close(fd)
            raise
        handle = next(i for i in range(1, MAX_HANDLES + 1)
                      if i not in self.handles)
        self.handles[handle] = fd, flags
        return handle

    def _close(self, handle):
        entry = self.handles.pop(handle, None)
        if entry is None:
            return -10
        fd, flags = entry
        result = 0
        try:
            if flags & 0x1030000:
                os.fsync(fd)
        except OSError as exc:
            result = fs_error(exc)
        finally:
            try:
                os.close(fd)
            except OSError as exc:
                if not result:
                    result = fs_error(exc)
        return result

    @staticmethod
    def _length(length):
        if not isinstance(length, int) or not 0 <= length <= MAX_IO:
            raise ValueError('I/O limit exceeded')

    def _missing_only(self, path):
        parent, name = self._parent(path)
        try:
            if any(char in name for char in '*?['):
                raise UnsupportedOperation('directory search response unresolved')
            os.stat(name, dir_fd=parent, follow_symlinks=False)
        finally:
            os.close(parent)
        raise UnsupportedOperation('successful response schema unresolved')

    def _cmpt(self, path, control):
        if not isinstance(control, bytes) or len(control) != 40:
            raise ValueError('CMPT_Read requires ten u32 words')
        words = struct.unpack('<10I', control)
        if words[0] != 0x1f or words[3] != 0x700 or words[6] not in (0, 1, 2):
            raise UnsupportedOperation('unobserved CMPT_Read variant')
        self._length(words[8])
        completed, size, data, handle = 0, 0, b'', None
        error = 0
        try:
            handle = self._open(path, words[3])
            if handle < 0:
                error = handle
            else:
                completed |= 1
                fd = self.handles[handle][0]
                size = self._regular(fd).st_size
                if size > 0xffffffff:
                    raise OSError(errno.EOVERFLOW, 'size exceeds wire field')
                completed |= 2
                offset = struct.unpack('<i', control[20:24])[0]
                os.lseek(fd, offset, words[6])
                completed |= 4
                data = os.read(fd, words[8])
                completed |= 8
        except OSError as exc:
            error = fs_error(exc)
        finally:
            if handle is not None and handle > 0:
                close_error = self._close(handle)
                if not close_error:
                    completed |= 16
                elif not error:
                    error = close_error
        if error:
            raise UnsupportedOperation('CMPT failure response schema unresolved')
        return struct.pack('<Ii', completed, error), size, len(data), data

    def operate(self, generation, op, *args):
        """Structured API. Invalid input raises; known host errors become FS codes.

        A stale/stopped generation always returns (-10,) without I/O. Unknown
        semantics raise UnsupportedOperation so a future transport must stop,
        rather than pretend that a guessed vendor response was sent.
        """
        if not self.active or generation != self.generation:
            return (-10,)
        try:
            if op == 0x1001:
                return (self._open(*args),)
            if op == 0x1005:
                return (self._close(*args),)
            if op in (0x1002, 0x1003, 0x1004, 0x1009):
                handle, *rest = args
                if handle not in self.handles:
                    return {0x1003: (-10, 0, b''),
                            0x1004: (-10, 0),
                            0x1009: (-10, 0)}.get(op, (-10,))
                fd = self.handles[handle][0]
                if op == 0x1002:
                    offset, whence = rest
                    if whence not in (0, 1, 2) or not -(1 << 31) <= offset < (1 << 31):
                        raise ValueError('invalid seek')
                    position = os.lseek(fd, offset, whence)
                    if position > 0x7fffffff:
                        raise OSError(errno.EOVERFLOW, 'seek exceeds signed reply')
                    return (position,)
                if op == 0x1003:
                    length, = rest
                    self._length(length)
                    data = os.read(fd, length)
                    return 0, len(data), data
                if op == 0x1004:
                    data, length = rest
                    self._length(length)
                    if not isinstance(data, bytes) or length != len(data):
                        raise ValueError('write length mismatch')
                    return 0, os.write(fd, data)
                if rest:
                    raise ValueError('unexpected size arguments')
                size = self._regular(fd).st_size
                if size > 0xffffffff:
                    raise OSError(errno.EOVERFLOW, 'size exceeds wire field')
                return 0, size
            if op == 0x1007:
                path, = args
                parent, name = self._parent(path)
                try:
                    os.mkdir(name, 0o770, dir_fd=parent)
                finally:
                    os.close(parent)
                return (0,)
            if op == 0x101a:
                if args == (4, 2, 12):
                    return (ord('Z'),)
                if args == (8, 2, 12):
                    return (-2,)
                raise UnsupportedOperation('GetDrive query tuple unresolved')
            if op == 0x101c:
                if args:
                    raise ValueError('SetDiskFlag has no arguments')
                return (0,)
            if op == 0x1022:
                return self._cmpt(*args)
            if op in (0x1012, 0x1025):
                self._missing_only(args[0])
            if op == 0x100c:
                raise UnsupportedOperation('Move third argument unresolved')
            raise UnsupportedOperation('operation not implemented')
        except OSError as exc:
            error = fs_error(exc)
            if op == 0x1003:
                return error, 0, b''
            if op in (0x1004, 0x1009):
                return error, 0
            return (error,)

    def shutdown(self):
        """Revoke generation first, close/fsync every handle, return first error."""
        self.active = False
        error = 0
        for handle in list(self.handles):
            result = self._close(handle)
            if not error:
                error = result
        if self.root >= 0:
            os.close(self.root)
            self.root = -1
        return error
