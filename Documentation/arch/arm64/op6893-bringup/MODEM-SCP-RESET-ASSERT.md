<!-- SPDX-License-Identifier: GPL-2.0-only -->
# SCP 双核 SET：实际写入完成，复位效果未确认

**2026-11-16接续更正：** 本文记录的是首次SET实验及当时判读。
后续初始释放实验已实测CLR后bit0=1、SET后bit0=0，原判据确实写反，
详见[初始启动实验](MODEM-SCP-INITIAL-KICK.md)。原始EIO记录保留，不代表
复位写入失效。修正版源码采用active-low读回，尚未替换设备运行镜像。

2026-11-16，基于 `b705479df18f` 工作树，镜像 `248c64a7dd23`。
AI 辅助实现、源码对照、构建、上机测试和文档整理。
两核 SET bit0 读回均0，接口返回 `EIO`。不能验收复位成功，亦不能仅据此
判定写入无效。设备保留该主线，USB/Wi-Fi SSH 可用，未启动 SCP/基带。

## 实现和厂商依据

默认关闭 `OP6893_CCCI_SCP_RESET_ASSERT`，在已有唯一 owner 内增加
`reset_assert`、`reset_state`；不增加映射或 probe 时硬件动作。
显式 `echo assert > reset_assert` 的顺序为：

1. 持 owner mutex 检查显式26M pin、SPM投票、TOPCK选择及gate，标记请求。
2. 锁外 STOP、同步 IRQ/worker；重新持锁并检查前置条件。
3. 向 `0x10730004`、`0x10740004` 各写1；执行 ARM64 `mb()`（DSB SY）。
4. 各读一次 SET bit0，复查前置条件；任一bit0为0则返回EIO。

一次请求后不自动重试，没有CLR、恢复复制或fallback SMC。
底本为本机可用6.6的 `drivers/misc/mediatek/scp/rv/scp_helper.c` 中
`scp_sys_reset_ws()` non-secure TIMEOUT/AWAKE分支，该分支不等待WFI。
地址与同树 `mt6893.dtsi`、`scp_reg.h` 一致。刷写前Android DT确认
`secure_dump=disable`、两核，原SCP状态为ready。

**要求bit0读回1是实验判据，尚不是已证明的寄存器契约。** 厂商实现仅打印
读回值，并不按值拒绝后续恢复。本次EIO不能直接解释为硬件复位失败，也
不能忽略后宣布成功。软件STOP不证明全部CPU/DMA及mailbox旧消息已隔离。

## 实机结果

预先排队目标设备的flash boot和reboot，Android执行sync + SysRq reboot
后刷写完成，没有使用fastboot boot。release为
`7.3.0-op6893-d1-248c64a7dd23+`。

|项目|结果|
|---|---|
|启动初始状态|reset requested/attempted/writes/reads均0；core/TCM读写0；五IRQ masked|
|26M pin|accepted=1、pin_verified=1，SCP资源投票0x02|
|SET前|两核CLR/SET/gated/halt采样位均0；header精确68字节、geometry valid|
|实际SET|requested=1、attempted=1、writes=2、reads=2|
|读回及返回|core0_set=0、core1_set=0、latched=0、error=-5，sysfs写返回EIO|
|SET后|两核采样位仍0；header尺寸/布局不变；TCM写入0|
|接收状态|closing=1、五IRQ masked；interrupt/worker/event计数0，generation0|
|健康检查|USB/Wi-Fi各一次SSH成功；五个LVTS温度接口约38–43°C，无匹配的实际内核故障|

`core_tcm`观察计数为register_reads=72、register_writes=2、tcm_reads=72、
tcm_writes=0；reset helper另两次读由`reset_state.reads`单独计数。
`core_tcm.reset_supported=0`是原观测接口的固定字段，实际写入看reset_state。

首次启动因cache内旧模块vermagic不符，GPU模块未加载。随后构建匹配模块，
仅传到`/run/scp-reset-modules/`加载：gpu_sched/panfrost成功，出现renderD128，
GPU probe成功、初始频率约350MHz。未写cache、未做图形压力/DVFS验收；
重启后仍需匹配模块。本镜像保留此前GPU OPP/供电耦合、MFGPLL、LVTS/cooling更新。

## 验证和证据

- 实际reset C后端及owner sysfs路径ASan/UBSan通过：STOP锁边界、前置失败、
  两次写/DSB/读回、postcheck失败、读回不符和重复请求拒绝。
- 启用ARM64 Image.gz、后续匹配modules构建、定向strict checkpatch通过。
  实验DTS/defconfig源文件已恢复，out仍为实验配置。未重复默认/启用全矩阵、
  schema全套及无关8核/存储/按键测试；仅一次pin、一次SET和前后观测。
- [结构化记录](evidence/modem-scp-reset-assert-validation.json)；原始日志位于
  `/data/src/mainline/mt6893-direct/evidence/scp-reset-assert/`，包括before.log、
  assert.log、health-usb.log、health-wifi.log、modules-runtime.log。

## 接续重点

1. 核对同板4.19/6.6的SCP内部时钟、供电/DRAM请求、AP访问权限和SET可读语义。
   TOPCK输出26M与SPM投票不证明整个内部访问链路。特别核对vendor reset
   worker的`scp_lpm_req_dram()`与内部clock init，不能直接套用新式SCP SMC枚举。
   当前仅读取三个偏移的掩码，不能从低位全0推断整页全0、掉电或权限阻断。
2. 找到依据后，一轮合并访问前置、实际reset和可解释的状态验证，不为每次
   映射/读操作单独刷机，也不以删除EIO判据把本轮结果改成成功。
3. reset路径有效后整合mailbox旧消息丢弃、generation/READY和恢复/释放。

旧[恢复审计](MODEM-SCP-RESET-RESTORE.md)中未执行SET等描述属于R5.19历史
状态；本轮按用户要求采用可用vendor强制SET路径。DMA隔离、备份来源及
mailbox清理仍未完成；当前结果不支持直接进入restore/release。
