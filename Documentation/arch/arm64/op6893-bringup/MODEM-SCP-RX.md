<!-- SPDX-License-Identifier: GPL-2.0-only -->
# SCP mailbox RX：资源审计与有界接收后端

2026-11-15，HEAD `6db0f4606d6e` 工作树，AI 辅助源码分析、实现及测试。
接续 [主线 TCM 观测](MODEM-SCP-TCM.md)。本轮离线实现；设备仍运行
`3ccec64b58d4`，未刷写/重启或操作 mailbox。没有收到或接受真实 READY。

## 同板 A/V 的资源与接收顺序

依据保存 ACK DT `/scp@10700000`，不是本次运行时硬件验证：

|mailbox|data base / bytes|SET / CLR|init|GIC SPI number / type|
|---|---|---|---|---|
|0|0x107fb000 / 256|0x107fb100 / 0x107fb10c|0x107a5020|436 / level-high|
|1|0x107fc000 / 256|0x107fc100 / 0x107fc10c|0x107a5024|437 / level-high|
|2|0x107fd000 / 256|0x107fd100 / 0x107fd10c|0x107a5028|438 / level-high|
|3|0x107fe000 / 256|0x107fe100 / 0x107fe10c|0x107a502c|439 / level-high|
|4|0x107ff000 / 256|0x107ff100 / 0x107ff10c|0x107a5030|440 / level-high|

SPI number 是 GIC DT 中断单元，不是 Linux 动态分配的 IRQ number。
IPC0/IPC1 另用 SPI434/435，不等同于 mailbox IRQ。
fixture 没有 `mboxN_send/recv`，A/V `mtk_mbox_read_recv_irq()` 因而读 CLR
地址作为 pending，`mtk_mbox_clr_irq()` 向同址写精确 mask 清位。
初始化路径会映射 init，但不能从函数存在就推断启动时一定写 init。
本轮没有创建任何这些 MMIO 映射或 IRQ consumer。

完整布局保持 14 TX/17 RX/5 mailbox，不能删除不关心的 channel 后重排。
APCCCI RX channel7 为 mailbox1/word28/bit14/2 words；
READY0 channel9 为 mailbox1/word40/bit20/1 word；
READY1 channel22 为 mailbox3/word30/bit15/1 word，本轮不接 core1。
READY0 payload 是 TCM size，保存 DT `scp_sramSize=0x180000`。
A 的 ready handler 在验证大小前标 ready，本实现不会照搬该顺序。

A/V `mtk_mbox_isr()` 的关键顺序：读 pending，复制本次 pending 对应消息，
运行 RX post callback，清本次已处理 mask，然后通知 process-context consumer。
部分 ISR callback 在清位前已经运行；本后端选择在清位成功后统一交付，
避免错误清理前发布状态。厂商 `mtk_mbox_polling()` 先清位再复制，不能作为
这个 RX 事务的顺序底本。实际 write ordering、清位语义及重入仍待硬件确认。

`scp_ipi_table.h` 的 mailbox post callback 是 `scp_clr_spm_reg()`。
A 向 SCP cfg+0x94（0x10724094）写1清 SCP→SPM 通知；V 在可选
`scp-cfgreg-ap-en` 下改用 AP cfg+0x18，`scp-ipc-wa` 下还有 GPR7 清理。
保存本机 DT 没有这两个可选属性，不能据此推断所有启动版本都一样。
它与 AP 主动发送的 awake lock/unlock 是两条路径。这里必须先闭合共享
寄存器归属，不能在 RX 后端中隐式映射或用成功桩略过。
资源、IRQ、属性与 A/V 源码指纹见
[审计数据](evidence/modem-scp-rx-resource-audit.json)。

## 默认关闭的后端

新增 `OP6893_CCCI_SCP_RX`，依赖既有 protocol helper，默认 n。
实现 `drivers/misc/mediatek/ccci/ccci-scp-rx.{c,h}`，没有 device/probe、
MMIO、IRQ 注册、时钟/awake/reset 操作或任何现存硬件 caller。

`ccci_scp_rx_init()` 接收已成功验证的完整不可变布局、mailbox、已准备好
目的缓冲的 supported mask、非零 reset generation 及 caller ops。
再次检查目标 mailbox RX 的 offset/size/irq/重复 channel/重叠边界。
不重新推导或改变全表偏移。初始化无 I/O，失败清除字段并保持 fault。
layout/ops/context 生命周期与不重入由 owner 保证。

一次 `ccci_scp_rx_step()` 有固定上界，不在 IRQ 中无限排空：

1. 仅读一次 pending；0 则无后续副作用。未知或未注册位使整个批次拒绝，
   不读取 payload、不清任何位，进入 sticky fault。
2. 对每个 pending pin 复制精确 words*4 wire bytes 到独立 CPU snapshot；
   不读对齐填充、不依赖设备缓冲在 ACK 后保持不变。
3. 必须调用 board `post_capture`，成功后仅 ACK 本次已复制位。ACK callback
   负责 ordered write completion；不能要求 bits 一直为0，新消息可能已到达。
4. ACK 成功后才交付各 pin 的快照及 generation。deliver 不得失败或重入，
   必须当场复制 transient 数据，实际客户端空间由 owner 在 ACK 前预留。

读 pending、任意 payload、板级完成或 ACK 失败都会锁定实例，不发布本次
消息。ACK 错误即使可能已生效，也不推断未消费，更不能重试。上层 IRQ
wrapper 必须屏蔽并处置来源；本后端没有替它屏蔽 IRQ，也不以 clear-all
掩盖未知位。`ccci_scp_rx_invalidate()` 供 owner 在 STOP/reset 时失效。
重新 init 只允许 owner 在中断 masked/synchronized 后建立新 reset generation，
不能为了重试错误而重新 init。同代迟到事件由未来状态机拒绝。

`ccci_scp_decode_ready0()` 只检查已定位 READY0 pin、非 response、1 word、
精确4字节小端 payload 与 caller 提供的可信 TCM size 完全相等。
它不判断 IRQ 来源、新旧代际或镜像身份，不设置 READY 标志。
已有 CCISM BOOTING/RBREADY decoder 与此硬件 READY 事件保持独立。

## 验证

`tools/test_modem_scp_rx.py` 编译实际 protocol/RX C，以 ASan/UBSan 验证：
完整本机布局下各 mailbox 的 750 组批次、严格 copy/post/ack/deliver 顺序、
ACK 立即覆盖设备缓冲仍交付原快照、所有操作失败不交付、TX/未知/未注册
位不清除、sticky fault/STOP 失效、迟到新批次、bit31、64-word 边界、
畸形 pin 拒绝、READY0 精确长度/大小/core1/response 拒绝及不对齐 CPU buffer。
原有布局/wire 回归通过。测试没有模拟总线、GIC、中断风暴或 firmware。

启用 protocol+RX 的 ARM64 Image.gz/modules 构建通过，vmlinux 有 RX 后端
符号；随后恢复默认配置构建 Image.gz/modules，通过且 RX 符号不存在。
没有打包或刷写新 boot。编译器无新增 warning；strict checkpatch 0/0/0。
默认配置保留原有 FW_LOADER/VT 两条重复赋值提示。
日志在 `mt6893-direct/evidence/scp-rx-offline/`，结果见
[验证数据](evidence/modem-scp-rx-validation.json)。

## 下一步

先做默认关闭的 mailbox pending 只读预检，核对本次硬件 MMIO 和 IRQ 描述，
不 ACK、不读未知 payload、不请求或开启 IRQ，避免消费继承的旧消息。
然后建立共享 clock/寄存器 provider、IRQ containment 和初始化代际责任。
完整 RX transport 必须提前准备所有可能接收通道的目的缓冲，决定不支持
channel 的处置方式；只有 READY0 handler 并不足以安全清理整组 IRQ。

正式 IRQ owner 还须实现 bounded drain budget、未知位/持续触发时屏蔽、
worker 与 STOP/reset 同步、全部回调引用生命周期和板级 SPM completion。
解除复位前安装真正 READY 接收路径；继承 pending 或缓存数据不得直接
接受为本代 READY。不因本轮 backend 通过就发送 awake、释放复位或启动 MD。
