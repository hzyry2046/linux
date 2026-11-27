#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Audit local A/V/Q reset/recovery source, without firmware or device access."""
import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path


def block(text, marker):
    start = text.index(marker)
    end = text.index('\n}', start) + 3
    return text[start:end], text[:start].count('\n') + 1


def audit(root):
    paths = {name: root / 'drivers/misc/mediatek/scp/rv' / name
             for name in ['scp_helper.c', 'scp_helper.h', 'scp_awake.c', 'scp_reg.h']}
    paths['mtk-mbox.c'] = root / 'drivers/soc/mediatek/mtk-mbox.c'
    source = {name: p.read_text() for name, p in paths.items()}
    markers = {
        'initial_release': ('scp_helper.c', 'int reset_scp(int reset)'),
        'recovery_worker': ('scp_helper.c', 'void scp_sys_reset_ws('),
        'halt_wait': ('scp_helper.c', 'void scp_reset_wait_timeout(void)'),
        'recovery_mappings': ('scp_helper.c', 'void scp_recovery_init(void)'),
        'restore_memory': ('scp_awake.c', 'int scp_sys_full_reset(void)'),
        'mailbox_probe': ('mtk-mbox.c', 'int mtk_mbox_probe('),
        'mailbox_ack': ('mtk-mbox.c', 'int mtk_mbox_clr_irq('),
    }
    snippets, records = {}, {}
    for name, (file, marker) in markers.items():
        body, line = block(source[file], marker)
        snippets[name] = body
        records[name] = {'path': str(paths[file]), 'line': line,
                         'body_sha256': hashlib.sha256(body.encode()).hexdigest()}
    initial = snippets['initial_release']
    assert 'writel(1, R_CORE0_SW_RSTN_CLR)' in initial
    assert 'DRAM_RESV_ADDR_REG' in initial and 'DRAM_RESV_SIZE_REG' in initial
    assert 'R_CORE0_SW_RSTN_SET' not in initial and 'scp_sys_full_reset' not in initial
    worker = snippets['recovery_worker']
    assert worker.index('writel(1, R_CORE0_SW_RSTN_SET)') < worker.index('scp_sys_full_reset();')
    assert worker.index('scp_sys_full_reset();') < worker.index('writel(1, R_CORE0_SW_RSTN_CLR)')
    assert 'writel(1, R_CORE1_SW_RSTN_SET)' in worker
    assert 'mtk_mbox_clr_irq' not in worker
    restore = snippets['restore_memory']
    for token in ['memset_io(SCP_TCM, 0, SCP_TCM_SIZE)',
                  'memcpy_to_scp(SCP_TCM', 'memcpy_to_scp(scp_region_info',
                  'sizeof(scp_region_info_copy)', 'memset(scp_ap_dram_virt',
                  'memcpy(scp_ap_dram_virt, tmp,', '* scpreg.core_nums']:
        assert token in restore, token
    mappings = snippets['recovery_mappings']
    assert 'scp_region_info_copy.ap_loader_start' in mappings
    assert 'scp_region_info_copy.ap_dram_start' in mappings
    assert '*4' in mappings.replace(' ', '').replace('\n', '').replace('\t', '')
    assert 'request_firmware' not in source['scp_helper.c'] + source['scp_awake.c']
    probe = snippets['mailbox_probe']
    assert 'request_irq(' in probe and 'mtk_mbox_clr_irq' not in probe and 'writel(' not in probe
    assert 'writel(irq, minfo->clr_irq_reg)' in snippets['mailbox_ack']
    assert 'void scp_reset_wait_timeout' in snippets['halt_wait']
    assert 'B_CORE_HALT' in snippets['halt_wait']
    return {'root': str(root), 'files': {
        name: {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        for name, path in paths.items()}, 'functions': records,
        'checked_facts': {
            'initial_nonsecure_path_releases_without_assert_or_restore': True,
            'recovery_asserts_both_cores_before_memory_restore_and_core0_release': True,
            'ordinary_restore_uses_inherited_loader_and_two_core_dram_backups': True,
            'ordinary_header_copy_uses_compiled_size_not_snapshot_size': True,
            'no_request_firmware_in_helper_or_awake': True,
            'mailbox_probe_requests_irq_without_explicit_pending_clear': True,
            'recovery_worker_has_no_explicit_mailbox_ack': True,
            'halt_wait_returns_no_success_or_timeout_status': True,
        }}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--android', type=Path, default=Path('/data/src/kernel_oddo_mt6893'))
    p.add_argument('--ack', type=Path, default=Path('/data/src/6.6-exp/android_kernel_modules_oneplus_mt6833/kernel/kernel_device_modules-6.6'))
    p.add_argument('--qqcandy', type=Path, default=Path('/data/src/mainline/linux-qqcandy-6.18'))
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    report = {'scope': 'Local source control flow only; does not prove firmware provenance, reset completion or mailbox isolation',
              'trees': {name: audit(getattr(args, name)) for name in ['android', 'ack', 'qqcandy']}}
    # Q shares some recovery control flow, but its compiled header is only 60B.
    # Check actual C layouts; do not widen the MT6893 decoder to copy Q's ABI.
    definitions = []
    for name, expected in [('android', 72), ('ack', 72), ('qqcandy', 60)]:
        root = getattr(args, name)
        text = (root / 'drivers/misc/mediatek/scp/rv/scp_helper.h').read_text()
        definition, _ = block(text, 'struct scp_region_info_st {')
        definition = definition.replace('scp_region_info_st', name + '_region')
        definitions.append(definition + ';')
        definitions.append(f'_Static_assert(sizeof(struct {name}_region)=={expected}, "{name} header size");')
        for field, offset in [('ap_loader_start', 0), ('ap_firmware_start', 8),
                              ('ap_dram_start', 16), ('ap_dram_backup_start', 24),
                              ('struct_size', 28), ('regdump_start', 44), ('regdump_size', 48)]:
            definitions.append(f'_Static_assert(offsetof(struct {name}_region,{field})=={offset}, "{name} {field}");')
        report['trees'][name]['header_compiled_bytes'] = expected
    with tempfile.TemporaryDirectory(prefix='op6893-scp-reset-audit-') as directory:
        file = Path(directory) / 'layout.c'
        file.write_text('#include <stdint.h>\n#include <stddef.h>\n' + '\n'.join(definitions))
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-c', str(file), '-o', str(Path(directory) / 'layout.o')], check=True)
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print('PASS: A/V/Q compiled headers 72/72/60 bytes; initial release vs recovery, exact source mapping formulas, compiled header-copy size, void halt wait, and no explicit mailbox isolation in probe/reset worker')


if __name__ == '__main__':
    main()
