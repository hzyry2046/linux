#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline fixtures for the Android metadata collector; never invokes adb."""
from pathlib import Path
import os
import struct
import subprocess
import tempfile

COLLECTOR = Path(__file__).with_name('collect_modem_scp_metadata.sh')


def main():
    with tempfile.TemporaryDirectory(prefix='op6893-scp-observe-') as directory:
        root = Path(directory)
        misc = root / 'sys/class/misc/scp'
        misc.mkdir(parents=True)
        dt = root / 'sys/firmware/devicetree/base'
        scp = dt / 'scp@10700000'
        scp.mkdir(parents=True)
        (misc / 'scp_A_status').write_text('SCP A is ready\n')
        (scp / 'core_nums').write_bytes(struct.pack('>I', 2))
        (scp / 'secure_dump').write_bytes(b'disable\0')
        # Reading any of these side-effect attributes would hang the fixture.
        for name in ['scp_A_awake_lock', 'scp_A_awake_unlock', 'scp_A_reg_status',
                     'scp_ipi_test', 'scp_reset', 'wdt_reset']:
            os.mkfifo(misc / name)
        (scp / 'TaskContext_ptr').write_text('NEVER-EXPORT-THIS')
        (root / 'proc').mkdir()
        (root / 'proc/cmdline').write_text('NEVER-EXPORT-CMDLINE-OR-SERIAL')

        def collect():
            result = subprocess.check_output(['sh', str(COLLECTOR), str(root)],
                                             text=True, timeout=5)
            assert 'NEVER-EXPORT' not in result
            pairs = [line.split('=', 1) for line in result.splitlines()]
            assert len(pairs) == len(dict(pairs))
            return dict(pairs)

        data = collect()
        assert data['schema'] == 'op6893-scp-metadata-v1'
        assert data['ready-before'] == data['ready-after'] == 'ready'
        assert data['dt:scp@10700000/core_nums'] == 'hex:00000002'
        assert data['dt:scp@10700000/secure_dump'] == 'hex:64697361626c6500'
        assert data['dt:scp@10700000/core_1'] == 'unavailable'
        for value, expected in [('SCP A is not ready\n', 'not-ready'),
                                ('NEVER-EXPORT-UNKNOWN-STATUS\n', 'unrecognized')]:
            (misc / 'scp_A_status').write_text(value)
            data = collect()
            assert data['ready-before'] == data['ready-after'] == expected
        (misc / 'scp_A_status').unlink()
        assert collect()['ready-before'] == 'unavailable'
        (scp / 'reg').write_bytes(b'\xff' * 1025)
        assert collect()['dt:scp@10700000/reg'] == 'oversize'
        (scp / 'reg').write_bytes(b'\xff' * 1024)
        assert collect()['dt:scp@10700000/reg'] == 'hex:' + 'ff' * 1024
        (scp / 'reg').write_bytes(b'')
        assert collect()['dt:scp@10700000/reg'] == 'hex:'
        (scp / 'reg').unlink()
        (scp / 'reg').mkdir()
        assert collect()['dt:scp@10700000/reg'] == 'read-error'
        # Android kernels also expose the same OF tree through /proc/device-tree.
        dt.rename(root / 'proc/device-tree')
        assert collect()['dt:scp@10700000/core_nums'] == 'hex:00000002'
    print('PASS: fixed hardware allowlist, normalized READY, absent/empty/oversize/unreadable properties, proc OF fallback')
    print('PASS: FIFO traps prove side-effect attributes not read; arbitrary status/cmdline not exported')


if __name__ == '__main__':
    main()
