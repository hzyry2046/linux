<!-- SPDX-License-Identifier: GPL-2.0-only -->
# op6893 普通 CCIF 与 6297 控制环

2026-11-16，AI 辅助实现。此版本完成离线实现、sanitizer 与启用 ARM64
构建；尚未在设备执行 CCIF 初始化、MD 接管或电源切换。最后实测镜像仍是
`e8509e81dbc3`，不能据此宣称基带或 CCIF 通信可用。

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
4. 读回双方完整 SRAM，以及双方 BUSY/RCHNUM=0，进入 prepared-irqs-masked。

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

下一次实测合并 LK 子区校验→继承ON接管→冷上电→CCIF准备→关电，不为窗口
预留或单次寄存器读取单独刷机。成功后接 IRQ/worker 和控制通道，再与 SCP
常驻、CCIF2/CCISM、FS/RPC/NVRAM工作副本服务整合；条件齐备才执行 MD CPU
boot `(6,0)`，验证 HS1/HS2。此版本不发出该命令。
