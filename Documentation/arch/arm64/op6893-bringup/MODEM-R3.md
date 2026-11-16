<!-- SPDX-License-Identifier: GPL-2.0-only -->
# op6893 基带 R3：MD1 MTCMOS 与 M0 上机验收

后续接续：[平台层](MODEM-PLATFORM.md)已增加默认关闭的MD1节点及显式owner，
支持精确LK ON初态并阻止自动关断；本篇“仅接管OFF/没有域节点”为R3历史状态。

2026-11-14，基于 `6db0f4606d6e` 工作树，AI 辅助实现与验证。
本轮吸收新增[用户态/固件分析](MODEM-PROTOCOL.md)，完成 MD1 电源序列首版，
并单独上机验收此前的 M0。该次 M0 镜像不包含 R3 电源代码。
后续 `7576d31c76a4` 已包含 R3 代码并通过资源回归，但没有 MD1 域实例，
仍未实测电源序列；见 [供电记录](MODEM-RAILS.md)。

## M0 实机结果

显式实验镜像 `fe077e30d191`，内核 `7.3.0-op6893-d1-fe077e30d191+`。
从已连接的 Android 进入 fastboot，刷写 boot 后 reboot；未使用 fastboot boot。

```text
[0.246965] op6893-ccci-lk modem-handoff: LK metadata valid: version=3 tags=20 bytes=2664 ccb=1; modem not started
```

检查器绑定成功，读取本次 LK 交接及 tag 快照，SMEM/CCB 校验通过。USB ECM
SSH、独立 Wi-Fi SSH、3 包外网 ping（零丢包）、cache ext4 上 SquashFS/Overlay
Debian rootfs 通过；约 401 秒复查未见 Oops/BUG/panic。此结果不证明 MD 已运行，
也未验证细粒度 SMEM、SCP、CCIF、AT 或 SIM。

实验只临时启用 handoff DT 节点和 LK_INSPECT=y。构建后源码 DTS/defconfig
逐字节恢复，默认配置仍关闭。资源检查器、SID3 provider 和新 MD 电源入口
没有启用；没有恢复 ACK、更新其备份或改动 GPT。

开发机运行内核 7.2.15，而磁盘模块为 7.3.4；native-connect 因 cdc_acm 不存在
失败，改用既有 libusb ECM/TAP 通道。Wi-Fi SSH 独立直连另行成功，不依赖该 TAP。
简化证据见 [运行记录](evidence/modem-m0-mainline-runtime.json)。原始构建、
variant patch、镜像 manifest、刷写和过滤后的运行日志保存在外部构建目录
`mt6893-direct/evidence/modem-m0-live/`；不保存原始 tag payload。

## 电源序列实现

`drivers/pmdomain/mediatek/mt6893-md-power.c` 接入现有 MediaTek genpd，
追加域 ID 24（MD1），保留已有编号。实际板级 DTS **没有**新增 MD 域节点，
也没有 consumer，因此当前默认镜像不会注册、上电或自动关断 MD1。

这层只控制 AP 可操作的 MTCMOS：SPM 控制 key、MD1_PWR_CON、PWR_STATUS
bit0、两路外部 buck 隔离，以及 infracfg 三组保护。依据 A 的
`drivers/clk/mediatek/clk-mt6885-pg.c:spm_mtcmos_ctrl_md1()`：

- 开：unlock → 依次解除隔离 bit0/1 → RESET_B=1 → PWR_ON=1 → 等 ACK=1
  → 释放保护 2_0、2_1、1；厂商不等待 CLR ACK，本实现也没有新增该等待。
- 关：unlock → 依次设置保护 1、2_0、2_1，各等 ACK → PWR_ON=0
  → **等 ACK=0** → 依次隔离 bit0/1 → RESET_B=0。

没有复用通用 MODEM_PWRSEQ 的隔离/复位顺序，没有调用未经确认的 SMC 18/19。
MTCMOS RESET_B 也不是 ATF 的 MD CPU 放行操作。没有访问暗域、清零 CCIF
SRAM、配置 SRCCLKENA、开启时钟、改变供电或发送 modem boot SMC。

初始化只读核对完全 OFF：PWR_STATUS=0、PWR_ON/RESET_B=0、两位隔离及
三组保护 ACK 均到位；任一条件不符返回 EBUSY，不通过电源循环“同步状态”。
MD 域明确要求本地 infracfg 引用；拒绝域内 clocks/domain-supply，四路供电和
CCIF 生命周期由后续平台 consumer 在 runtime PM 前后管理。

每步检查 regmap 错误，ACK 按 10 us 间隔、1 s 预算轮询。任何切换失败即停止，
记录步骤并锁定 FAULT，后续开/关请求返回 EIO，不自动回滚或盲目重试。genpd
失败后不会被这个 helper 重新操作成“看起来正常”；实际部分切换状态必须在
重启/专门恢复路径处理。时间预算约束轮询，不保证一次已卡死的总线访问能返回。

## 验证与限制

[主机测试](tools/test_modem_power.py)直接编译实际 C 序列，以独立的厂商顺序
作为 oracle，覆盖正常开关、相邻位保持、21 个步骤错误注入、6 个初始化读取
错误、8 个不完整初态、5 个 ACK 卡住和失败后双向请求拒绝，ASan/UBSan 通过。
regmap stub 不模拟物理电源、固件 master 或总线死锁。

实际 ARM64 `Image.gz`、modules 和 modpost 构建通过，无编译警告；默认 LK
检查器配置恢复为 n。R3 没有打包/刷入设备，genpd 接入仅通过编译与源码审查，
不能写成 MD 实机上下电成功。验证与源码指纹见
[验证清单](evidence/modem-r3-validation.json)。

后续仍优先 SID3 shutdown/启动电压策略、SCP RV 与 CCISM。上述依赖、完整
SMEM 布局和平台所有权齐全后，再显式添加 MD 域 consumer，测试受控上电、
失败清理和 ATF 放行；此时才开始 HS1/HS2，不把 MTCMOS 编译通过当作可点火。
