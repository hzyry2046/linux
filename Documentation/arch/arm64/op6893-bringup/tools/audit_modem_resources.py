#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Offline source fingerprints and allowlisted modem/SCP DT resources.

Never connects to a device, hashes a DTB, or exports arbitrary DT properties.
Requires the Python libfdt module. Output describes the supplied saved snapshot,
not the current device. AI-assisted audit utility, not a hardware validator.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess

import libfdt


SOURCES = {
    "A": {
        "arch/arm64/configs/mt6893_defconfig": ["CONFIG_MTK_TINYSYS_SCP"],
        "drivers/clk/mediatek/clk-mt6885-pg.c": ["int spm_mtcmos_ctrl_md1("],
        "drivers/clk/mediatek/clk-mt6885.c": ["#define GATE_IFRAO4_IGN"],
        "drivers/regulator/mt6315-misc.c": ["static void mt6315_S3_default_vosel("],
        "include/linux/mfd/mt6315/registers.h": ["#define MT6315_PMIC_DA_VBUCK"],
        "drivers/misc/mediatek/pmic/mt6359p/v1/pmic.c": ["void vmd1_pmic_setting_on("],
        "drivers/misc/mediatek/eccci/mt6885/modem_secure_base.h": ["enum CCCI_SECURE_REQ_ID"],
        "drivers/misc/mediatek/eccci/mt6885/modem_reg_base.h": ["INFRA_AO_MD_SRCCLKENA"],
        "drivers/misc/mediatek/eccci/mt6885/ccci_platform.c": ["mt_secure_call("],
        "drivers/misc/mediatek/eccci/mt6885/md_sys1_platform.c": [
            "int md_start_platform(", "int md_cd_power_on(", "int md_cd_let_md_go("],
        "drivers/misc/mediatek/eccci/modem_sys1.c": ["static int md_cd_start("],
        "drivers/misc/mediatek/eccci/hif/ccci_hif_ccif.c": [
            "ccif_clk_table[]", "scp_clk_table[]", "void scp_set_clk_off("],
        "include/linux/soc/mediatek/mtk_sip_svc.h": ["MTK_SIP_KERNEL_CCCI_CONTROL"],
    },
    "V": {
        "drivers/clk/mediatek/clk-mt6893-pg.c": ["PGATE(SCP_SYS_MD1"],
        "drivers/misc/mediatek/eccci/fsm/md_sys1_platform.c": ["md_s3_vosel_restore"],
        "drivers/misc/mediatek/eccci/fsm/ccci_fsm_scp_c.c": [
            "int fsm_ccism_init_ack_handler(", "static int ccif_scp_clk_init("],
        "drivers/misc/mediatek/scp/Makefile": ["CONFIG_MTK_TINYSYS_SCP_CM4_SUPPORT"],
        "drivers/misc/mediatek/scp/rv/scp_helper.c": [
            "void scp_region_info_init(", "void scp_recovery_init(", "scpsys_of_ids[]"],
        "drivers/misc/mediatek/scp/rv/scp_awake.c": ["INFRA_IRQ_SET"],
    },
    "M": {
        "drivers/pmdomain/mediatek/mtk-pm-domains.c": [
            "static int scpsys_modem_pwrseq_off(", "pd->data->ext_buck_iso_offs"],
        "drivers/pmdomain/mediatek/mt6893-pm-domains.h": [],
        "drivers/clk/mediatek/clk-mt6893-pmif.c": [],
        "drivers/regulator/mt6315-regulator.c": [".get_voltage_sel", "MT_BUCK(\"vbuck"],
        "drivers/regulator/mt6359-regulator.c": ["MT6359_DA_VPU_EN_ADDR"],
        "arch/arm64/boot/dts/mediatek/mt6893-op6893-boot.dts": ["spmi: spmi@", "modem-handoff"],
    },
    "Q": {
        "arch/arm64/boot/dts/mediatek/mt6895-oplus-qqcandy.dts": [],
    },
}

NODES = [
    "/scpsys@10006000", "/mddriver", "/ccifdriver@10209000",
    "/ap_ccif2@1023c000", "/md_ccif2@1023d000", "/dpmaif@10014000",
    "/scp@10700000", "/scp_clk_ctrl@10721000", "/scp_infra@10001000",
    "/scp_dvfs", "/reserved-memory/mblock-21-SCP-reserved",
    "/reserved-memory/reserve-memory-scp_share",
]
STRINGS = ("compatible", "status", "reg-names", "interrupt-names", "clock-names",
           "core_0", "core_1", "scp_mem_key")
CELLS = ("reg", "interrupts", "size", "alignment", "alloc-ranges", "core_nums",
         "twohart", "mbox_count", "scp_sramSize", "send_table", "recv_table",
         "legacy_table", "scp_feature_tbl", "scp_mem_tbl")


def prop(fdt, node, name):
    try:
        return bytes(fdt.getprop(node, name))
    except libfdt.FdtException as exc:
        if exc.err != -libfdt.NOTFOUND:
            raise
        return None


def cells(raw):
    if len(raw) % 4:
        raise ValueError("non-cell hardware property")
    return list(struct.unpack(">" + "I" * (len(raw) // 4), raw))


def project(fdt):
    result = {}
    for path in NODES:
        node = fdt.path_offset(path)  # Required fixture nodes: fail if absent.
        item = {}
        for name in STRINGS:
            raw = prop(fdt, node, name)
            if raw is not None:
                if not raw.endswith(b"\0"):
                    item.setdefault("unterminated-string-properties", []).append(name)
                item[name] = raw.rstrip(b"\0").decode("ascii").split("\0")
        for name in CELLS:
            raw = prop(fdt, node, name)
            if raw is not None:
                item[name] = [hex(value) for value in cells(raw)]
        if prop(fdt, node, "no-map") is not None:
            item["no-map"] = True
        raw = prop(fdt, node, "clocks")
        if raw is not None:
            refs, clocks, index = cells(raw), [], 0
            while index < len(refs):
                provider = fdt.node_offset_by_phandle(refs[index])
                count_raw = prop(fdt, provider, "#clock-cells")
                if count_raw is None or len(count_raw) != 4:
                    raise ValueError("invalid clock provider cell count")
                count = cells(count_raw)[0]
                if index + 1 + count > len(refs):
                    raise ValueError("truncated clock reference")
                clocks.append({"provider": fdt.get_path(provider),
                               "args": refs[index + 1:index + 1 + count]})
                index += 1 + count
            if "clock-names" in item and len(item["clock-names"]) != len(clocks):
                raise ValueError("clock name/reference count mismatch")
            item["clocks-resolved"] = clocks
        result[path] = item
    return result


def fingerprint(root, files):
    output = []
    for name, needles in files.items():
        raw = (root / name).read_bytes()
        lines = raw.decode().splitlines()
        anchors = {}
        for needle in needles:
            hits = [i for i, line in enumerate(lines, 1) if needle in line]
            if not hits:
                raise ValueError(f"missing source anchor: {name}: {needle}")
            anchors[needle] = hits
        output.append({"path": name, "bytes": len(raw),
                       "sha256": hashlib.sha256(raw).hexdigest(), "anchors": anchors})
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"],
                                   text=True).strip()
    return {"root": str(root), "head": head, "files": output}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--android", type=Path, required=True)
    parser.add_argument("--vendor", type=Path, required=True,
                        help="kernel_device_modules-6.6 root")
    parser.add_argument("--mainline", type=Path, required=True)
    parser.add_argument("--qqcandy", type=Path, required=True)
    parser.add_argument("--saved-dtb", type=Path, required=True)
    parser.add_argument("--date", required=True, help="audit date, YYYY-MM-DD")
    args = parser.parse_args()
    roots = dict(zip(("A", "V", "M", "Q"),
                     (args.android, args.vendor, args.mainline, args.qqcandy)))
    output = {
        "date": args.date,
        "scope": "Offline source fingerprints and allowlisted historical DT hardware "
                 "properties only. No device access, DTB hash, private payload or runtime proof.",
        "sources": {key: fingerprint(roots[key], files) for key, files in SOURCES.items()},
        "historical_fdt": {"path": str(args.saved_dtb),
                           "cell_encoding": "big-endian u32, rendered as hex; reg is "
                                            "untranslated parent-bus cells",
                           "nodes": project(libfdt.Fdt(args.saved_dtb.read_bytes()))},
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
