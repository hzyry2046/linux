# attempt120：GPU 电源域上电，读到 GPU_ID

内核 `a7d50ee674c1`。原始记录在 `mt6893-direct/evidence/attempt-120/`。

## 第一次尝试：MFG1 超时（`ae7817dba5fe`）

`op6893-gpu-probe` 请求打开 MFG1 时返回 -110。MFG0 能正常上电，随后被回滚。

手动按厂商顺序（`spm_mtcmos_ctrl_mfg0/1`）写 PWR_CON：MFG0 和 MFG1 都能上电，
SRAM ACK 也正常。说明问题不在电源开关，而在总线保护（bus protection）的释放上。

释放前 `SUB_INFRA_VDNR_STA1` = 0x00050000：bit16 和 bit18 由其他主设备持有。
主线 `MT6893_TOP_AXI_PROT_EN_SUB_INFRA_VDNR_MFG1_STEP5` 写成了
`GENMASK(19, 17)`，而厂商的 `MFG1_PROT_STEP2_2_MASK` 只有 bit17 和 bit19。
bit18 永远不会清零，所以轮询超时。

## 修复后（`a7d50ee674c1`）

主线 scpsys 依次打开 MFG0→MFG1→MFG2–6。BG3D 门控本来就是开的
（MFG_CG_CON = 0）。按厂商 `mt_gpufreq_external_cg_control` 设置
ASYNC/GLOBAL/QCHANNEL 之后读到：

| 寄存器 | 值 |
|---|---|
| GPU_ID | `0x90800011`（G77，r0p1） |
| L2_FEATURES | `0x07120206` |
| SHADER_PRESENT | `0x660067`（9 核，与 Android 一致） |
| L2_PRESENT | `0x1` |

下电后 PWR_STATUS 回到 `0x10580e03`，PWR_CON 回到 0x1112，总线保护重新置位，
vgpu 和 vsram_others 被关闭。第二次上电和下电同样正常。

## 未做

- MFG 时钟 mux 和 MFGPLL 仍沿用 LK 的设置（约 350 MHz），没有 DVFS。
- 没有 panfrost，GPU 还没有执行过任何任务。
