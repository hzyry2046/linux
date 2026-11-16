<!-- SPDX-License-Identifier: GPL-2.0-only -->
# SCP 初始启动接入 Linux IRQ / RX

2026-11-16，AI 辅助实现及定向验证。承接
[一次初始释放](MODEM-SCP-INITIAL-KICK.md)，使用 LK 已载入的镜像，
不等待完整 recovery/backup 恢复器，不添加新 SMC 或内部时钟写入。

## 接口与一次完整实验

默认关闭 `CONFIG_OP6893_CCCI_SCP_INITIAL_BOOT`，资源 owner 节点仍默认
`disabled`。probe 只解析完整 14 TX / 17 RX 表，不做自动启动。
显式 `pin=26m` 后，向 `initial_boot` 写 `test`：

1. 与旧 `reset_assert` 共用一次请求门闩，锁外 STOP、同步 IRQ/worker。
2. 双核 SET/DSB/active-low 读回，核对精确 header 的几何及本次 share 保留区。
3. 双核持续处于复位，检查五组 pending，任何未知来源拒绝；只对已知旧通知
   执行 completion=1、精确 W1C，屏障后确认五组均 0，不读取旧消息负载。
4. 建立不可复用的本轮 generation=1，准备全部 RX、启动 IRQ/worker，再写
   share GPR1/2、core0 CLR/DSB。STOP 已清空软件队列；残留 GIC pending 即使
   触发 handler，也只会 drain 空 mailbox，不能制造 READY。
5. 最多三秒消费 generation-tagged CPU 事件。channel9/22 必须精确一 word、
   非 response、长度4且值=TCM大小0x180000。其他客户端/logger通知消费后擦除，
   不跟随固件指针，不回填日志地址或发送 APCCCI。
6. 成功/失败均锁外 STOP、双核重新 SET，再恢复原 AP GPR1/2，撤销 generation。
   资源检查失败可能阻止 MMIO 清理，故单独报告 `cleanup_error`，不能只看 READY。

`boot_state` 的 `ready_observed/ready_channel` 只记录本次历史观测；结束时
`ready_now=0`，不代表双核常驻运行、完整 SCP 客户端或基带可用。
超时不会重试、重启或写 TCM/固件。外设仍可通过 USB/Wi-Fi 维护。

## 验证

定向 ASan/UBSan 运行实际 owner 控制函数、SET helper 和旧通知丢弃函数：
双 READY、generation 不符、畸形 READY、启动/接收失败、超时、各阶段前置条件
失败、旧通知未知来源/未清除、精确 W1C 与清理；通过。
既有实际 MMIO/queue/RX/drain 定向测试通过；全部修改的 kernel C/H
strict checkpatch 0/0/0。启用 ARM64 Image.gz、FDT/协议检查和打包 round-trip
通过，无编译警告；与本轮无关的外设回归明确跳过，未当作已重测。
实验 DTS/defconfig 已恢复。镜像 `b74f21c0411e`：
`/data/src/mainline/mt6893-direct/dist/b74f21c0411e/boot.img`，SHA256
`d4eb93042588665449f4e9c2dc2191178a7a9530517f0f00f5c9e7499cb16438`。
首轮 `b74f21c0411e` 实测 READY1 经过 Linux IRQ/worker/队列到达，
`events=1, channel=22, error=0, cleanup_error=0`；两核最终 raw=0xff00，
header68/geometry 正常，USB/Wi-Fi SSH 可用。mailbox 寄存器读/写42/4，
completion写2，IRQ2次、worker3次、unexpected0。

首轮同时复现 STOP 后软件 disable 但 `gic_masked=0`：GICv3 没有 irq_disable
回调，generic IRQ 默认 lazy disable，并不立即屏蔽硬件。接收 adapter 为五个
专用 IRQ 设置 `IRQ_DISABLE_UNLAZY`，释放时在 STOP 后清除标志。改进模型将
软件 depth 与硬件 mask 分离：模拟旧行为能复现屏蔽断言失败，修正版实际
receive/MMIO/queue/drain ASan/UBSan 通过。此问题属于实验驱动功能错误，
未证明非特权攻击路径，不作为安全漏洞报告。

修正版完整启用镜像 `949a860a1a85`，boot SHA256
`7131750e689e4db46c10bb378616bd18743cdff48ebb3299bc90ed2379a8a981`，
同样完成 ARM64/FDT/打包检查、恢复实验 DTS/defconfig。修正版实测：
READY1 再次经完整接收路径到达，error/cleanup_error 均0；IRQ2、worker3、
unexpected0，STOP 后 `gic_masked=5`、CPU 队列空、generation0，双核raw=0xff00。
三秒内成功结束，没有等待超时。再次写 test 返回 EALREADY，计数未变。
本次两轮均从新 LK 启动环境开始，硬件旧 pending 为0；非零旧消息丢弃及
未知来源/拒绝清除路径由实际函数模型覆盖，未声称真机覆盖。

USB/Wi-Fi SSH 均可用，LVTS 五温度接口可读，未见匹配内核故障。
两份 GPU 模块重新编译并只上传 tmpfs，Panfrost probe 成功；cache 旧模块
仍不匹配当前 release，没有更改 cache 模块或重做 GPU/DVFS 压测。
设备保留 `949a860a1a85` 主线，SCP 双核保持复位，MD 未启动。

证据目录 `/data/src/mainline/mt6893-direct/evidence/scp-initial/`：
`hardware.log` 为首次成功及 GIC 不符，`hardware-fixed.log` 为修正版结果；
`unlazy-before.log` / `unlazy-after.log` 为复现/回归，`after-usb-fixed.log` /
`after-wifi-fixed.log` 为维护连接及结束状态。
[结构化验证](evidence/modem-scp-initial-boot-validation.json)。

下一步依据本轮实际接收结果，接持续消费、AP awake 和 CCCI；当前 bounded test
不提供常驻 SCP 服务，不启动 MD，完整 restore 留给后续恢复路径。
