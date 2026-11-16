<!-- SPDX-License-Identifier: GPL-2.0-only -->
# op6893 普通 CCIF 与 6297 控制环

2026-11-16，AI 辅助实现。修正版 `8ec93b17bbb5` 已实测完整 LK 子区解析→
继承ON接管关电→冷上电→32环和CCIF SRAM初始化/校验→stop→MD1关电。
最终两路IRQ在GIC中屏蔽、计数0，时钟/domain引用均释放；USB/Wi-Fi正常，
MD CPU未放行。仅验收初始化及一次冷电源循环，尚无现场CCIF通信或基带READY。

## 所有权及启用条件

默认关闭 `CONFIG_OP6893_CCCI_CCIF`，依赖现有 MD platform owner。
`modem-platform@10209000` 与 MD1 默认 disabled；probe 不操作 CCIF 寄存器
或 SMEM，不触发电源切换。LK 布局通过完整 tag/SMEM 校验后，owner 独占
AP `0x10209000`、MD `0x1020a000` 两个 4K 窗口及 SPI194/195。
IRQ 注册 `IRQF_NO_AUTOEN`、`IRQ_DISABLE_UNLAZY`，当前没有 enable 接口。
意外 handler 只锁存故障并屏蔽 IRQ，不在可能关电的域中访问 MMIO。

正常与异常环使用 SMEM ID19/20；本机两个子区相邻且共享边界页，因此独占
申请联合物理范围，仅建一个 WC 映射，避免同页重复映射。所有环 I/O 都检查
子区边界；CPU 保存的长度是校验依据，不信任对端修改后的控制长度。这里的
WC 属性遵循本机 A/V 的 `ccci_map_phy_addr()`，不映射其余 SMEM 或 NVRAM。

[平台层](MODEM-PLATFORM.md)完成 `takeover`（继承 ON 时）和 `on` 后，
向 `/sys/bus/platform/devices/10209000.modem-platform/ccif` 写 `prepare`：

1. 同一 owner mutex 下核对 powered、时钟和 domain 引用及实际 MD1 ON；
   两路 IRQ 必须在 GIC 中 masked。
2. 按本机 6297 表格式化正常/异常各16个环，逐个读回控制区和外层标记。
3. infra `+0x150/+0x154` bit8 复位 CCIF0，清双方各512B SRAM；AP最后12B
   写入 `0x7274626e`、ID13 RAW_MDSS_DBG 的 MD 地址及大小。
4. 读回双方完整 SRAM（共享同一footer），以及双方 BUSY/RCHNUM=0，进入 prepared-irqs-masked。

每次启动仅允许一次准备。开始写入后任一步失败锁存 fault，不重试或猜测回滚。
`md_power=off` 和 shutdown 会先检查 masked 并重新复位/核对 SRAM，再关 MD1
及释放时钟；CCIF 故障则保留这些资源供诊断，必须重新启动恢复。未 prepare
时 stop 不操作 CCIF。普通 CCIF0 不得复位 SCP 的 CCIF2。

## 环布局及协议

表取自本机 Android 4.19 与已可用 6.6 的 `*_up_95`，不是 qqcandy 的6298表。
下表为 KiB；q9–15全部为0，但仍保留每个40B的控制/标记位置，不能压缩。

| 队列 | 正常 RX | 正常 TX | 异常 RX/TX |
|---|---:|---:|---:|
| 0 | 80 | 128 | 12 |
| 1 | 80 | 40 | 32 |
| 2 | 40 | 8 | 8 |
| 3 | 80 | 40 | 0 |
| 4 | 20 | 20 | 0 |
| 5 | 20 | 20 | 0 |
| 6 | 64 | 64 | 8 |
| 7 | 0 | 0 | 0 |
| 8 | 8 | 8 | 0 |
| 9–15 | 0 | 0 | 0 |

单环为外层头8B、RX控制12B、TX控制12B、RX数据、TX数据、外层尾8B。
正常合计 `0xb4280`，异常 `0x1e280`；历史子区分别721/121 KiB，尾部各384B
不属于环且保持不动。每个环自身完整清零，外层标记为双字 `ee0000ee` /
`ff0000ff`。SRAM debug 指向 ID13，不能使用 ID18 RAW_RESERVED。

CPU RX/TX 后端实现 `aabbaabb`、有效载荷长度、8B对齐及双字 `ccddeeff` 尾。
有效载荷至少为16B的 CCCI header；跨环复制、容量/空满/不完整包/坏标记均
有明确错误，只有成功复制完整包才推进 AP 指针。TX 的未发布部分可在失败
时被改写，但生产指针不变；调用者必须处理故障后再决定生命周期。对端指针
采样后使用读屏障，AP指针发布前使用完整屏障，同时约束WC读取与写入。

当前后端没有现场收发 caller。IRQ/worker、channel 路由、exception FSM、
CCB/SRAM runtime handshake、doorbell/BUSY/ACK 和 FS/RPC 服务仍待接入。
不能将纯 CPU 包测试视作硬件握手。IRQ低16位数据与高位异常的 ACK 契约必须
分别遵循本机 vendor，不能简单合并为一次全位 ACK。

## 验证及接续

[测试](tools/test_modem_ccif.py)编译实际 ring/hw C，ASan/UBSan 检验两份
同板 vendor 表、全部32个对齐起点×217个有效包长度、RX/TX跨界、padding、
外部canary、坏包/长度/指针、不完整包、零槽及逐回调失败。硬件模型覆盖521个
失败位置、精确复位地址/值、SRAM和状态读回。另逐字抽取实际 prepare/stop，
覆盖65个格式化/校验/复位失败位置、IRQ gate、一次性和停止故障保留。
抽取测试不模拟真实 GIC、devres、缓存属性或 device/sysfs 调度。

启用 Image.gz/modules/modpost、默认板 DTB/schema 和 strict checkpatch通过。
原 MD平台/域/SMEM 回归通过，默认配置与禁用状态保留。结构化记录见
[evidence/modem-ccif-validation.json](evidence/modem-ccif-validation.json)。

完整合并实测已通过，不再为窗口预留或单次寄存器读取单独刷机。接续 IRQ/
worker 和控制通道，再与 SCP
常驻、CCIF2/CCISM、FS/RPC/NVRAM工作副本服务整合；条件齐备才执行 MD CPU
boot `(6,0)`，验证 HS1/HS2。此版本不发出该命令。


## 首轮合并实测与 SRAM 校验修正

`420ed6e96546` 启动后owner ready，LK v3/20tags/2664B、23子区，NC24MiB、
cached76939264B、间隙0x80000。初态lk-on；CHECK_DONE/接管成功进入cold，
冷上电后powered/clocks1/domain1，四路RG电压800/800/800/700mV未改动。
32环均格式化与校验成功；CCIF写入完成后停在reset-and-sram/EIO。

仅补读已由本次初始化写入的最后三个字：AP `0x102092f4/f8/fc` 与MD
`0x1020a2f4/f8/fc` 均为 `7274626e / 40110800 / 00003800`。
双方BUSY/RCHNUM均0，IRQ304/305计数均0，无unexpected、内核告警或Oops，
USB/Wi-Fi SSH和8核正常。该证据表明MD视图也能看到AP footer；旧测试模型
将两边设为独立存储，漏掉这个硬件契约。改成共享SRAM模型后实际旧C断言失败，
修正为两侧都核对相同footer后通过，仍拒绝非footer的非零内容及坏footer。

这是默认关闭、root显式硬件准备入口的功能性错误，不涉及权限边界跨越；
按本树threat-model作为普通bug处理。首次失败锁定保留电源/时钟，没有绕过内核
fault执行重试/关电；重启刷入修正版后完成复测。
原始结果位于 `/data/src/mainline/mt6893-direct/evidence/modem-ccif-image/`。


## 修正版完整实测

`8ec93b17bbb5`（boot SHA256
`085f1797d4b75d5e76e0a5a2ddde321b542eb49fdbd6681acb92acf4e007ee1f`）
通过同一组合流程。CCIF状态依次reserved→prepared-irqs-masked→
stopped-irqs-masked，error/unexpected均0；MD最终stopped、clocks0/domain0。

独立AP侧读回：

| 寄存器 | 最终值 |
|---|---|
| 0x1000616c PWR_STATUS | 0x10580e02 |
| 0x10006300 MD1_PWR_CON | 0x00000008 |
| 0x10006398 MD_BUCK_ISO | 0x00000003 |
| 0x10001228 保护1 ACK | 0xe70c108e |
| 0x10001b90 保护2 ACK | 0x20200401 |
| 0x10001bc4 保护3 ACK | 0x000500c0 |
| 0x0c00011c GICD_ISENABLER7 | 0x00100000 |

GIC bits2/3（hwirq226/227）均0，Linux IRQ304/305计数0；MD1精确OFF读回通过。
关电后不再读取CCIF窗口。Wi-Fi及USB SSH确认同一release和最终状态，8核在线，
cache ext4 ro/norecovery、rootfs lower squashfs ro；未见BUG/WARNING/Oops/
Call trace。boot分区完整回读哈希匹配；没有更改ACK备份或分区表。
SCP runtime保持active0/ready0/generation0，本轮未重新启动SCP或基带。
设备保留该主线，MD1已关闭。未验收热重启、DVFS、CCIF中断/门铃/现场包、
CCISM或HS1/HS2，下一步接普通HIF的IRQ/worker及控制通道状态机。
完整命令结果在 `/data/src/mainline/mt6893-direct/evidence/modem-ccif-fix/`。
