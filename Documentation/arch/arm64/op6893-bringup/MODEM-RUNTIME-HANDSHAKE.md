<!-- SPDX-License-Identifier: GPL-2.0-only -->
# 6297 runtime 协商、SRAM 回复与控制握手

2026-11-16，AI 辅助实现。本轮在普通 CCIF owner 内接入默认关闭的
`CONFIG_OP6893_CCCI_HANDSHAKE`，实现 HS1→runtime 回复→HS2 的有状态
consumer。实际 C sanitizer 和 ARM64 构建结果见
[evidence/modem-runtime-handshake-validation.json](evidence/modem-runtime-handshake-validation.json)。
**本轮完全离线，没有打包或刷写镜像、启用真机 IRQ、放行 MD CPU，也没有
真实 HS1/HS2 或蜂窝支持验收。** 当前功能仍停在内部 API，没有 sysfs start。

## 依据和 wire 边界

A 为本机 Android 4.19 `drivers/misc/mediatek/eccci/`，V 为已修复可用的
6.6 模块树 `kernel/kernel_device_modules-6.6/drivers/misc/mediatek/eccci/`。

- A `ccci_modem.c`、V `fsm/ccci_fsm.c`：AP feature 策略、协商和 payload。
- A `modem_sys1.c`、V `fsm/modem_sys1.c`：runtime v2.1 SRAM 上传。
- A/V `inc/ccci_modem.h`：8B feature 头、64槽、查询结构。
- A/V `hif/ccci_hif_ccif.c`：H2D_SRAM=15，BUSY 后写 TCHNUM=15。

实现显式小端编解码，不依赖 C bitfield、结构体 packing 或宿主字节序。
MD 查询魔数 `0x49434343`，AP 查询魔数 `0x43434349`；保持不同方向。

| 对象 | 实现边界 |
|---|---|
| runtime ID14 | 精确4096B，AP/MD 各0x800；必须是非缓存、可映射子区，AP/MD 地址转换和两类 bank 独立校验 |
| feature 流 | 连续64个 ID，头8B：id/support-version/reserved[2]/u32 length；reserved和尾部清零；总长不超过0x800 |
| 支持策略 | caller 提交实际已实现的 capability 和 payload；预留了内存不等于实现了服务，不自动设为支持 |
| MUST | AP 不支持、版本不同即失败；有 payload 的项目必须满足 schema，不生成空 MUST |
| OPTIONAL/BACKCOMP | OPTIONAL 要版本相等；BACKCOMP 要 MD version不小于AP。未知或未实现能力保留不支持槽 |
| payload-free 例外 | id27 MULTI_MD_MPU 在 A/V 是合法零长度 flag，不能按缺少 payload 拒绝 |
| v2.1 上传 | 16B CCCI头 + 0x9c结构 = 0xac整包；tail在整包+168，不是0xac结构再加头 |
| 内存信息 id38 | 同板实际输出 bank0/NC/cache 三个16B条目，总48B；数组容量4不代表输出64B |

当前 codec 只接受已核对的 version0 schema；不是全部 feature 的业务实现。
时间/启动信息、地址、大小等字段仍须由未来 owner 从真实资源与服务生成，
不能直接使用测试中的合成 profile。RTC_32K_LESS 也不能由 CONN 26MHz
strap 推导。AT_CHANNEL_NUM 是 MD runtime 报告的数量，不能据此改 HS2 通道；
本轮要求 BOOT_INFO 指向控制 RX channel0。

## 发布顺序及所有权

`ccci-runtime.c` 先完成全部协商和容量检查，再一次编码，普通失败时输出清零，
不会暴露半条 feature。v2.1 只在 BOOT_INFO 和 MULTI_MD_MPU 都实际协商成功后发送。

`ccci-ccif-tx.c` 使用有限回调后端完成一次发送：

1. 读 AP BUSY bit15；忙则 EBUSY，零写入，不隐式重试。
2. 写完整且补零的 AP runtime 0x800B；不写 MD half。
3. 写 AP SRAM +0x1f0 的0xacB，止于+0x29c，不覆盖 debug footer +0x2f4。
4. 屏障完成 WC 内存/SRAM发布，再逐字读回 SRAM。
5. 写 BUSY=BIT(15)，然后 TCHNUM=15；后者是编号，不是掩码。

任一中途失败不发送后续门铃、不回滚或重试部分写入；RX gate关闭并锁存故障，
owner 保留时钟/电源供诊断，统一 STOP 同步后仍遵循既有故障保留策略。
不能由 callback 直接进行 MD 电源操作。

`ccci-ccif-control.c` 在原 owner 构造时独占预留/映射 runtime 的完整包围页，
不读写内存或寄存器。4096B 可能跨两个4KiB页；只访问精确 runtime 区间，
后续邻接 user 需复用此映射，不能重复认领页面。start 在父生命周期锁下调用，
要求 MD CPU 停止、供电/时钟保持、CCIF prepare 完成和 IRQ 全 masked。
此时且仅此时清零 AP/MD 两半，再安装 RX consumer。一次硬件尝试，不提供重启。

## FSM、超时和停止

状态为 IDLE→WAIT_HS1→PUBLISH→WAIT_HS2→HS2_SEEN；失败锁存 FAILED，
正常停止为 STOPPED。HS2_SEEN 仅代表控制 wire 的里程碑，**不是 radio、
文件服务、SCP 或运营商注册 READY**。STOP 保留已见 HS1/HS2 和首个故障。

- HS1 只能来自 SRAM，精确240B，须通过既有查询头尾/控制头校验；环中 HS1、
  重复 HS1 或错误顺序均失败。RX 先快照再 ACK，之后才能发送回复。
- HS2 只能来自普通 q0/channel0，message0、非HS1标记、精确16B，且正在
  WAIT_HS2；重复或过早的 message0 不会被当作 READY。
- 控制异常和高位 CCIF 通知立即失败；bit7 CCB及其他端口包交给 caller。
  port 非零返回关闭接收，不假成功或丢弃必需服务请求。
- 两个等待阶段各60秒，基于单调 boottime；consumer和1秒定时工作检查超时。
  时间倒退/加法溢出也失败。HS2之后不再保留启动超时。
- timer 失败只调用不等待的 RX abort。正式 STOP 先关闭 control admission、
  同步取消 timer，再停止/同步 IRQ 和 RX worker，最后才检查复位/关电条件。

锁顺序为父 MD mutex→control mutex→RX gate。worker/port 不得获取父 MD
mutex、重入 control 或调用生命周期 start/stop；没有在 control mutex 下
cancel RX 工作。确定性模型覆盖部分交错，不能证明 Linux SMP/GIC 实际时序。

只读 `handshake` sysfs 报告 state/error/active/attempted/bytes/rejected/
hs2_seen；`cpu_release_issued=0` 明确当前无 CPU 释放路径。此属性不会发起操作。
默认 DT/defconfig 不改变，新选项关闭时使用 owner stub。

## 验证与接续

`tools/test_modem_handshake.py` 编译实际 runtime/TX/FSM/control/RX/ring C，
以合成 peer 和 Linux API 模型运行 ASan/UBSan：

- 全部2049个合法输出容量、512组 MD mask/version/AP能力组合；连续 ID、
  reserved清零、schema、AP/MD几何、整包0xac/结构0x9c边界。
- 全601个 TX I/O 失败位置、BUSY零写、读回损坏不发门铃、MD half与邻接
  SRAM不改写，WC屏障与门铃顺序。
- 来源/顺序/重复/缺失MUST/port失败、两阶段超时和时间溢出；HS2后不超时。
- 实际 control→RX SRAM→TX回复→环HS2；超时abort、STOP、一次尝试、
  不合法profile零I/O及已有raw RX占有拒绝。包含原接收层完整回归。

新增C/headers strict checkpatch为0 errors/warnings/checks；完整patch仅有新增文件的
MAINTAINERS提示，仍由现有misc/MediaTek维护范围覆盖。完整重编译在未改动的
connectivity代码中产生既有告警；最终增量构建及新增CCCI代码没有告警。

本轮不建立无实际服务支撑的启动 profile，也不为 dormant 代码单独刷机。
下一组把 CCIF2/CCISM 与常驻 SCP 的真实状态衔接，准备 FS/RPC/NVRAM 私有
工作副本和端口服务。由 owner 从这些有效资源生成能力表并检查服务门控，
再统一接首次 MD CPU release、异常/超时停止和真实 HS1/HS2 合并测试。
DPMAIF/AT/注册/数据上网分别验收，不由 HS2_SEEN 自动宣布完成。


2026-11-16接续顺序修正：SCP硬件READY/资源及服务先准备，CCISM协议完成
在HS2后，不作为MD CPU释放前的等待项。新增core/client的实现边界见
[CCISM](MODEM-CCISM.md)，最终桥/端口caller仍待接入。
