<!-- SPDX-License-Identifier: GPL-2.0-only -->
# SCP Linux IRQ/work 接收 adapter：离线阶段

2026-11-15，HEAD `6db0f4606d6e` 工作树；按“继续推进”任务，AI 辅助实现、
分析及测试。接续 [唯一 owner 映射](MODEM-SCP-MMIO-OWNER.md)。本轮不重启或
刷写，设备保持 `fba1be648ead`；新代码尚无 platform caller，不增加硬件验收。

## 实现范围

新增默认关闭 `OP6893_CCCI_SCP_RECEIVE`，依赖 MMIO_RESERVE 和 DRAIN，
只编译 `ccci-scp-receive.c`。它组合既有 non-posted MMIO、17 个 RX pin
的 CPU FIFO、有限轮次 drain，以及 Linux hard IRQ/workqueue adapter。
原资源 owner 仍调用旧 IRQ reservation，没有切换到新 adapter。
未来 constructor 必须替换旧申请，不能同时申请两套 action。

`receive_reserve()` 先校验全部 OF/GIC 描述，复用旧 IRQ 路径提取的校验
helper，再逐个申请五个专用 NO_AUTOEN action。校验仍要求 GICv3、
LEVEL_HIGH、hwirq 468–472，无 sleeping bus-lock。申请/清理阶段不访问
SCP 寄存器、不执行 prerequisite callback、不调用 start。部分申请失败
先同步已申请 IRQ 和 worker，再由 probe 的 devres 释放资源。
最后注册的 devres action 先停止 transport，MMIO 与 owner mutex 必须活得更久。

## 锁、代际和接收流程

- control mutex 串行化 start/STOP，覆盖释放 owner mutex 的同步间隙。
- 外部 owner mutex 串行化 MMIO、队列、drain、资源检查和 CPU event copy。
- raw gate 保护 IRQ 屏蔽/排队、closing、armed、generation 和排队 token。
  hard handler 不取 mutex、不读写 mailbox、不执行 SMC、不交付客户端。

初始 NO_AUTOEN 对应每个 IRQ 的一个 disable depth。位图只记录这一个
自有深度；重复 mask 不重复 disable，unmask 只平衡已持有的深度。
handler 先 mask 全部五路，再合并通知。首次排队捕获 generation，后来的
中断不覆盖已有 token。worker 在 owner mutex 下取 token 并验证代际，
调用 drain；只有完成五组 mailbox 的完整空 sweep 才 unmask。
worker 最后 unmask 后发生的新 IRQ 可以再次排队同一个 work。

start 要求调用者已经建立真实 reset generation 和旧消息隔离，再准备
MMIO、完整队列和 drain，排一次初始有预算的 sweep。返回成功只表示已排队。
数字递增本身没有硬件授权含义。进入 preparation 的尝试消耗该 generation，
失败后必须 STOP，再使用严格更新且有实际 reset 依据的代际。

STOP 先在 gate 内关闭排队并 mask，然后在不持有 owner mutex 的情况下
synchronize_irq/cancel_work_sync；之后持有 owner mutex 失效队列和 MMIO、
完成 drain 的两阶段停止，再将对象标为 quiesced。control mutex 防止
另一 start 越过这个同步屏障；最后一次 generation 不会因 STOP 清零。
devres release 另外设置 terminal，后续 start 被拒绝。

任何前置条件、未知 pending 位、队列容量、预算或调度错误都会保持 IRQ
屏蔽并失效 MMIO/整个 CPU FIFO，不重试消息。错误代际的 pop 返回 ESTALE，
不破坏当前队列。pop 只复制 CPU event，没有外部客户端回调或 READY 转换。

RX callback 契约明确为 process context、owner 串行化且禁止重入；资源和
clock 检查可能睡眠，不能从 hard IRQ 调用。新增 resource_check() 仅在
已 pin 后进行 bounded 只读查询，核对 26 MHz、SCP 用户身份/有效性及完整
资源 mask；失效后锁定，不自动 pin/retry/release，也不依赖 READY。
本轮未把它连接到平台 owner 的实际 prerequisite wrapper。

## 验证和限制

`tools/test_modem_scp_receive.py` 编译实际 receive/MMIO/queue/RX/drain C，
使用确定性 IRQ、work、mutex、devres 和寄存器模型，启用 ASan/UBSan。
覆盖五路 NO_AUTOEN、每处 IRQ resolve/request 失败和 devres action 失败、
启动前意外 IRQ、全板精确快照及破坏性 ACK、IRQ 合并、worker 运行中再排队、
STOP 期间迟到 IRQ、取消 pending work、同代拒绝/新代重启/terminal、
旧代 token 零新增 I/O、每个 prerequisite 检查点故障、pop 故障、
未知 pending、队列满、预算耗尽和 queue_work 不一致。

resource 测试补充未 pin/已 fault/错误时钟的零查询路径、成功只读检查、
每处 query 错误、身份/有效性/投票变化与两次采样不一致。另跑 IRQ、MMIO、
owner 双路径、queue、drain、RX 回归。全部通过。

启用和恢复默认配置各构建 ARM64 Image.gz/modules，日志无 warning/error；
启用 vmlinux 有 receive/resource_check 符号，默认配置无这些符号。
相关 C/header strict checkpatch 为 0 errors/0 warnings/0 checks。
没有 DTS/binding 变化，未创建新的测试 boot.img。

模型不能证明真实 Linux SMP、workqueue/GIC 时序、MMIO 完成或消息协议。
后续仍需唯一 owner prerequisite wrapper、constructor 的互斥替换接入，
先验证 dormant/no-I/O 状态；实际 reset/旧消息隔离、固件/客户端约束完成后
才允许调用 start、启用 IRQ、执行 completion/ACK 或接收本代 READY。
尚未启动 SCP/基带，不能计作 modem 可用。

USB 只读复查当前设备：mapped=6、register_reads/writes=0、prepared=0、
generation=0；五 IRQ masked，unexpected/work_runs=0；26 MHz pin_verified=1、
mask=0x02、resource fault=0。没有为复查执行 pin、reset 或 pending 读取。
证据目录 `/data/src/mainline/mt6893-direct/evidence/scp-receive-offline/`；
结构化结果见 [validation](evidence/modem-scp-receive-validation.json)。

后续 R5.18 已完成静默 constructor 接入与实机验收，见 [唯一owner接入](MODEM-SCP-RECEIVE-OWNER.md)；start 仍无调用者，reset generation仍0。
