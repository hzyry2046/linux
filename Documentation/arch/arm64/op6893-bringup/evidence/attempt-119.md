# attempt119：GPU 只读探测，SPMI 与 MT6315

内核 `25f3d093d4db`。

## Android 下厂商驱动的报告

- `gpuinfo`：`Mali-G77 9 cores r0p1 0x9080`。与 Exynos 990（z3s 项目）读到的 ID 相同。
- core mask `0x660067`，电源策略 `coarse_demand`。
- gpufreq：segment 2，41 档，最高 886 MHz / 0.70 V，最低 350 MHz / 0.55 V，
  vsram 0.75 V。完整记录在 `mt6893-direct/evidence/gpu-android/android-gpu.txt`。

## 主线：LK 交接时的状态（`tools/gpu-probe.c`，/dev/mem 只读）

| 项目 | 值 | 含义 |
|---|---|---|
| SPM PWR_STATUS / 2ND | `0x10580e03` | MFG0–6 全部断电 |
| CLK_CFG_5 | `0x01010103` | mfg_sel 选 mfgpll，门控打开 |
| MFGPLL CON0/1 | `0x3e1` / `0x031aec4e` | PLL 使能，posdiv /8，约 350 MHz |

电源域断电时工具不访问 mfgcfg 和 GPU 寄存器。

## SPMI / MT6315

主线 `mediatek,mt6873-spmi` 的寄存器表与厂商 `mt6885-pmif` 完全一致。probe
不改动仲裁器配置，只使用 SW 通道 2。MT6315 SID 7：

- `BUCK_TOP_CON0` = 0x0d：vbuck1、vbuck3、vbuck4 处于开启状态。
- vgpu（vbuck1）为 0.75 V（ELR0 = 0x78），vproc2（vbuck3）为 1.0 V。

所以 vgpu 已经上电，可以作为 MFG0 的 domain supply 使用；但 GPU 的电源域尚未打开。
