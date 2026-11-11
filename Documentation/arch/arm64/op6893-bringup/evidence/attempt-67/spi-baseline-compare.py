#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compare cached board observations with local vendor non-BT sleep tables."""
import hashlib
import json
from pathlib import Path
import re
import sys

ack = Path('/data/src/6.6-exp/android_kernel_modules_oneplus_mt6833/vendor/mediatek/kernel_modules/connectivity/conninfra/conn_drv/connv2/platform/mt6893')
old = Path('/data/src/kernel_oddo_mt6893/drivers/misc/mediatek/connectivity/conninfra/platform/mt6893')

def table(root):
    source = (root / 'mt6893_pos.c').read_text()
    text = source[source.index('int connsys_spi_master_cfg_mt6893('):]
    text = text[:text.index('\n\treturn 0;\n}') + len('\n\treturn 0;\n}')]
    clean = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    offsets = dict((key, int(value, 16)) for key, value in re.findall(
        r'#define\s+(CONN_WT_SLP_CTL_REG_\w+)\s+(0x[0-9a-fA-F]+)',
        (root / 'include/mt6893_consys_reg_offset.h').read_text()))
    # Audited function has only bt_only conditional branches. The else
    # assignments follow each BT assignment, so final occurrence is non-BT.
    writes = re.findall(r'CONSYS_REG_WRITE(_MASK)?\(\s*CON_REG_WT_SPL_CTL_ADDR\s*\+\s*'
                        r'(\w+)\s*,\s*(0x[0-9a-fA-F]+)\s*(?:,\s*(0x[0-9a-fA-F]+))?\s*\)', clean)
    assert len(writes) == 40, len(writes)
    result = {}
    for masked, name, value, mask in writes:
        assert bool(masked) == bool(mask)
        address = 0x18005000 + offsets[name]
        result[address] = {'name': name, 'mask': int(mask, 16) if mask else 0xffffffff,
                           'target': int(value, 16)}
    assert len(result) == 36
    return result, hashlib.sha256(text.encode()).hexdigest()

want, ack_hash = table(ack)
older, old_hash = table(old)
assert want == older, '4.19 and 6.6 source tables differ'
source = Path('/data/src/mainline/linux/arch/arm64/kernel/op6893-conn.c').read_text()
array = source.split('static const u32 op6893_conn_spi_addresses[] = {')[1].split('};')[0]
addresses = [int(x, 16) for x in re.findall(r'0x[0-9a-fA-F]+', array)]
assert addresses == [0x18001900, 0x18004000, 0x18005008] + list(want)
report = {'source_comparison': '4.19 and 6.6 local non-BT tables identical (not a running-module identity claim)',
          'ack_function_sha256': ack_hash, 'old_function_sha256': old_hash,
          'config_words': len(want), 'capture_words': len(addresses), 'rows': []}
observed = None
if len(sys.argv) == 2:
    capture = Path(sys.argv[1]).read_text()
    assert 'requested=1 samples=39 ' in capture
    pairs = re.findall(r'^address=(0x[0-9a-fA-F]+) value=(0x[0-9a-fA-F]+)$', capture, re.M)
    assert len(pairs) == 39
    assert [int(a, 16) for a, _ in pairs] == addresses
    observed = {int(a, 16): int(v, 16) for a, v in pairs}
    report['adie_control'] = hex(observed[0x18001900])
    report['adie_reset_deasserted'] = bool(observed[0x18001900] & 1)
    report['spi_status'] = hex(observed[0x18004000])
    report['spi_known_busy_mask'] = hex(observed[0x18004000] & 0x3e)
    report['wb_status'] = hex(observed[0x18005008])
    report['wb_top_clock_busy_bit26'] = bool(observed[0x18005008] & (1 << 26))
    report['matching_config_words'] = 0
for address, entry in want.items():
    row = {'address': hex(address), 'name': entry['name'],
           'mask': hex(entry['mask']), 'target': hex(entry['target'])}
    if observed is not None:
        value = observed[address]
        matches = (value & entry['mask']) == entry['target']
        row.update(observed=hex(value), masked_match=matches,
                   prospective_value=hex((value & ~entry['mask']) | entry['target']))
        report['matching_config_words'] += int(matches)
    report['rows'].append(row)
print(json.dumps(report, indent=2))
