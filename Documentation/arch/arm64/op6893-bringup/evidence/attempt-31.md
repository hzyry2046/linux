# Attempt31: live PMIF clock and error-path audit

No new kernel image or flash. Device continues boot268105891ada with
Debian9825862f46b0. Only fixed status-register reads performed, no target
register writes, clock changes, IRQ enable/clear or PMIC transaction injection.
No GPT/ACK changes. Uptime404s,8CPUs,SSH and watchdog feeder confirmed.

## Clock topology established from ACK

Source root: /data/src/6.6-exp/android_kernel_modules_oneplus_mt6833/kernel/kernel_device_modules-6.6.
Sources and SHA256 recorded by evidence/attempt-31/audit.py in audit.json.

| Consumer name | Provider ID | Hardware / parent |
|---|---|---|
| spi | infracfg_ao CLK_IFRAO_PMIC_AP | gate bit1 at status0x10001090 |
| wrap | infracfg_ao CLK_IFRAO_PMIC_TMR | gate bit0 at status0x10001090 |
| ulposc | topckgen CLK_TOP_PWRAP_ULPOSC_SEL | mux bits10:8, gate bit15 at0x10000090 |
| ulposc_osc | topckgen CLK_TOP_OSC_D10 | ulposc /10 fixed factor |

Both infra gates use fpwrap_ulposc_ck, itself a1:1 factor of pwrap_ulposc_sel.
Parent selectors0..4 are osc_d10,clk26m,osc_d4,osc_d8,osc_d16. Vendor
clk-mt6893.c:1043 parent list;1844 active mux;2108 gate registers;2240 gates.
MT_CCF_MUX_DISABLE=0 selects the gate-capable mux definition. Gate set
register0x80 disables; clear0x84 enables, status0x90 is active-high disabled.
Top config set/clear0x94/0x98, update register0x8 bit2; do not write these
without an actual clock driver and lifecycle review. ACK DT:774 pwrap,
1162/1168 provider addresses,149 fixed ulposc260MHz declaration.

Live CLK_CFG_8=0x05010001 -> selector0 (osc_d10), gate bit15 clear.
Infra status=0 -> PMIC AP/TMR gates enabled. Nominal selected parent26MHz
comes from ACK's260MHz oscillator declaration divided by10; not a measured
frequency and not proof of oscillator calibration or control ownership.
Current mainline has no MT6893 topckgen/infracfg provider; clk_summary is
absent on this build. Do not substitute a26MHz fake clock for these gates.

## Error path findings

Live init=1,timer_ctrl=3,SPI enable=1,IRQ group3 enable=0,flag=0.
Snapshot agrees with attempt30 and repeated samples are unchanged; see
snapshot.json,snapshot-later.json,comparison.json. Zero group3 enable means
this sample does not establish usable wrapper error interrupt coverage.

ACK mt6885 int_en_all=0x30; generic probe ORs it into group3 enable,
programs timer3 and requests GIC SPI220. Handler reads0x450 and clears
observed bits at0x454. Its ARB_V3 branch also handles CRC/MPU conditions with
additional PMIC/controller writes; do not copy this as a harmless logger.
Meaning/coverage of enabled bits4/5 is not established by the local handler.
No error injection, IRQ enable or recovery validation performed.

Mainline mt6873 sparse table lacks INT_FLG,INT_CLR,WDT_SRC_EN. The diagnostic
mt6885 branch correctly bypasses generic init/handler. Additionally ACK's
mt6885 table lacks WDT_SRC_EN while the generic probe unconditionally calls
pwrap_writel for that entry; pwrap_writel directly indexes the table. Thus
that source expression resolves to offset0 (INIT_DONE), not a verified WDT
source register. Reproduced by source-table assertions only; hardware impact
not tested, no live ACK execution claim. No external bug report or ACK patch.

## Concrete next implementation boundary

1. Implement real MT6893 clock providers, beginning with the audited PMIF
   fixed factors, selector and AP/TMR gates. Review provider registration,
   parent propagation, disable/unwind paths and oscillator ownership first.
   Keep unused-clock suppression and other consumers' inherited resources.
2. Bind four real clock references and compare PMIF state before/after;
   validate PMIC reads/keys,USB,UFS and8CPUs. No parent/rate changes needed.
3. Give MT6885 a dedicated register/type description and error path rather
   than filling unrelated legacy offsets. Establish bits4/5 semantics before
   enabling sources; no intentional live transport faults during bring-up.
4. ADC/regulators/DVFS remain deferred. ADC probe writes reset/config state.

New helper: `python3 pmif-snapshot.py` checks board/release over pinned native
SSH, reads only seven audited registers and emits raw+decoded JSON. Executed
successfully twice; source audit assertions pass. Snapshot is sequential,
not atomic, and does not test PMIC reads or claim kernel clock ownership.
Kernel unchanged, so no kernel rebuild or new dt-schema validation performed.
Analysis/tooling generated with Codex assistance; no commits or Signed-off-by.
