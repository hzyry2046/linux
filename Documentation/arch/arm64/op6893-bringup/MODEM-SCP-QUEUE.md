<!-- SPDX-License-Identifier: GPL-2.0-only -->
# SCP 接收目的队列：整批预留之后才 completion/ACK

2026-11-15，HEAD `6db0f4606d6e` 工作树，AI 辅助设计、实现及测试。
接续 [drain/lifetime](MODEM-SCP-DRAIN.md)。本轮离线实现 CPU 缓冲适配层，
未接入真实 IRQ、worker、MMIO 或 READY 状态机，未增加外设支持验收。

## 接收顺序

原 RX 后端要求 caller 在 ACK 前准备全部目的缓冲，ACK 后 deliver 回调不许
失败。drain 又要求五个邮箱 supported mask 完整覆盖，不能只接 READY0。
新增 `ccci-scp-queue.{c,h}` 把这两个条件落实到固定容量 CPU FIFO。
默认关闭 `OP6893_CCCI_SCP_QUEUE`，依赖 RX，不创建任何 device/initcall。

queue_init 为五组邮箱各建立一个实际 RX 实例及 callback context，全部共用
一个不可变布局、generation、CPU FIFO。包括全部17个 RX pin、response pin，
没有删除通道或重排 offset。每条事件保存 pin 元数据、精确 wire bytes 和
接收代号；只是 opaque CPU 副本，不执行客户端协议、READY 或 modem 转移。
硬件 ops 的 deliver 不被调用，也不要求其存在；交付由本层实现。

一个 mailbox 的批次顺序：

1. wrapper读取 pending；未知/不支持位立即使队列与所有RX失效，不读payload、
   不发completion/ACK。空 pending 不产生副作用。
2. 既有 RX 把整个批次的 wire bytes 精确复制到 CPU snapshot。
3. post_capture wrapper按 pending 位数检查整个批次所需空闲槽位，空间不足
   返回 ENOSPC，**不调用硬件completion，也不调用ACK**；设备消息保持pending。
   有空间才记录完整预留数，调用硬件completion。
4. ACK wrapper检查mask与本次pending一致、预留存在，才转发精确ACK。
   返回错误即失效所有RX并清除CPU队列，不重试，因为ACK可能已经生效。
5. ACK成功后，实际RX逐pin调用内部deliver，将此前CPU snapshot复制到环形
   存储并消费预留。不会再分配内存，不调用外部可失败的客户端，不依赖设备
   缓冲仍保留。pop再按FIFO复制到调用者CPU事件并擦除消费过的槽位。

整批空间检查在复制后、任何completion/ACK之前，因而即使失败前已读payload，
也不允许声称已经消费消息。result.post_attempted表示调用过wrapper，不等于
调用过硬件completion；容量不足时本层不会转发它。

## 容量、串行化与失败

物理上限64条事件，每条最多64 words，运行时capacity可设1–64。
queue对象含全部存储，必须堆分配，不能放内核栈；RX自身精确快照仍在其
有界小栈上。不会导出firmware、raw设备内存或标识数据；当前没有用户接口。

所有queue、RX、drain、客户端pop和STOP操作必须由同一个owner锁串行化；
任何硬件回调都不能重入这些操作。整批预留不需要跨线程原子计数，是依靠
该串行化保证其他producer不能抢占槽位。此实现没有锁，也不证明未来
IRQ/worker adapter已经符合契约。传入layout/ops/context必须活到所有引用
退出之后；输入/输出不得与queue存储重叠。

capacity限制CPU内存占用，不承诺支持无限突发。五邮箱满批次17条，若客户端
在一次drain中不消费，64条容量可能先于32轮drain预算耗尽；此时保守fault并
保持IRQ屏蔽，不丢弃设备新消息后继续运行。未来需根据真实流量决定容量、
消费调度和总预算，但不能用覆盖旧事件或先ACK再分配来掩盖队列满。

任何wrapper硬件错误、未知位或队列满都会invalidate全部RX、擦除所有CPU
队列内容并清空计数，禁止pop和新事务；已经被客户端pop的副本由owner在
STOP/reset时撤销/排空。失效意味着放弃该代，不试图保留此前READY。

drain也可能因共享前提、预算或IRQ mask/unmask失败而独立fault；未来owner
必须在**任何drain失败**后显式queue_invalidate，不得只依赖wrapper清理。
stop先拒绝新操作、屏蔽来源、失效RX/队列，再在owner锁外同步IRQ、worker和
客户端。只有实际完成quiescence/reset旧消息隔离后才允许重新queue_init，
不能以清空CPU存储或更新软件generation假装硬件已建立新代。

pop拒绝零/不同generation，空队列返回ENODATA，fault返回ESHUTDOWN；
失败时清空有效的输出对象，避免调用者误用旧事件。pop本身不验证新代来源，
也不证明payload可信。以后READY handler必须另行检查来源/本代启动条件。

## 验证结果

`tools/test_modem_scp_queue.py` 编译实际protocol、RX、drain、queue C，
ASan/UBSan覆盖：

- 全部17个pin精确数据/response/generation/FIFO次序；ACK覆盖设备wire，
  队列仍保存原快照；硬件deliver永不调用。
- 64种容量×5邮箱，整批够用和不足；每种容量精确装满后再来一条拒绝；
  旧事件占空间导致剩余不足一整批时不发completion/ACK。
- 1000次环形复用、变长消息尾部及消费槽位擦除。
- 每个邮箱pending/read/completion/ACK回调的每个错误位置，无重试；未知位、
  fault后全部RX拒绝、CPU存储擦除及stale generation拒绝。
- 五组queue-backed RX与真实drain成功排空和持续流量容量耗尽的联动。
- 每个邮箱缺失ops/回调、畸形pin、无hardware deliver、错误初始化参数拒绝。

测试没有模拟GIC、真实IRQ并发、bus或worker取消。原drain/RX/resource/cfg
sanitizer回归通过。启用protocol/RX/drain/queue的ARM64 Image.gz/modules
通过，vmlinux含queue init/pop/invalidate；恢复默认配置后构建通过且queue、
drain和RX符号不存在。临时defconfig已恢复，DTS未改。新增C/H strict
checkpatch 0/0/0，编译器无warning；保留原FW_LOADER/VT配置重赋值提示。

本轮没有打包boot、刷写或重启。USB被动检查设备仍为 `80e79074de00`，
26M pin_verified=1/fault=0，cfg reserved=1、completion关闭。这不算队列的
实机验收。日志：`/data/src/mainline/mt6893-direct/evidence/scp-queue-offline/`。
结构化证据：[queue validation](evidence/modem-scp-queue-validation.json)。

下一步将队列对象、drain和Linux IRQ/worker统一放进现有资源owner，先实现
IRQ初始不使能、enable/disable深度平衡、入队generation及STOP锁外同步。
随后核对并接入completion写排序和完整MMIO操作，再设计受控reset与本代READY。
