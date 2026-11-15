<!-- SPDX-License-Identifier: GPL-2.0-only -->
# SCP 接收：有限排空与代际生命周期后端

2026-11-15，HEAD `6db0f4606d6e` 工作树，AI 辅助设计、实现及测试。
接续 [cfg 归属](MODEM-SCP-CFG.md)。本轮是离线后端，不是 Linux IRQ/worker
驱动；没有请求 IRQ、创建工作队列、接入 MMIO 或完成任何 SCP 启动。

## 已实现的边界

默认关闭 `OP6893_CCCI_SCP_DRAIN`，依赖已有 RX 后端。
`ccci-scp-drain.{c,h}` 直接调用实际 `ccci_scp_rx_step()`，通过调用者提供的
`set_masked` 与 `check` 回调管理五个 mailbox 的整体访问条件。它没有设备注册，
没有对现有资源 owner 增加自动动作；当前没有硬件 caller。

- init 只初始化 CPU 状态，要求调用者已经屏蔽并同步 IRQ、排空 worker。
  只能在对象创建时调用，不能借重新 init 清除故障或重用 generation。
- prepare 仅允许 QUIESCED 状态；要求 generation 非零且严格递增，预算1–32。
  五个 RX 实例均须成功初始化，mailbox编号对应0–4，同一完整不可变布局，
  相同 generation，supported mask 必须等于各自完整 known mask，所有回调
  存在。目的缓冲实际存在/容量足够仍由 RX 初始化调用者保证。
- prepare 先验证全部实例，再要求屏蔽全部来源、核对共享前提，不读 mailbox，
  不开中断。操作失败会消耗该 generation 并使所有已接入 RX 失效。
- run 使用任务**入队时**保存的 generation；旧代任务直接 ESTALE，不访问
  回调，不影响新代状态。PREPARED/ACTIVE之外的同代调用返回 ESHUTDOWN。
- run 先屏蔽全部来源，再按 mailbox0–4进行完整 sweep，每轮之前检查共享
  前提和RX实例。每个邮箱直接执行既有 pending→copy→completion→ACK→deliver。
  全部五个邮箱都空才再次核对前提、重新开中断；本轮预算内有任何非空邮箱
  就进入下一完整 sweep。最大32轮，即每次 run 最多160次 RX step。
- 到达预算仍未取得完整空轮返回 EOVERFLOW，全部 RX 进入 fault，保持屏蔽。
  未知位、copy/completion/ACK错误或任何前提错误同样拒绝继续，不重试、不清
  全部位、不自动重新排队。之前成功批次可能已经交付，故障没有事务回滚。
- set_masked(false)失败后只尝试一次重新屏蔽。分别保留主 error 与
  containment_error；再次屏蔽失败时 masked=false，明确不能宣称硬件已隔离。
  初始屏蔽失败同理，不继续访问 mailbox。

预算限制调用次数，不是墙钟超时，也不保证固件会安静。callback必须本身
有限且不重入；持续流量用保守 fault 处置，后续需要凭实际流量决定是否引入
跨调度的总预算。默认后端不做无限排空，不以重新入队重置计数掩盖风暴。

## STOP 与 reset

状态路径为 QUIESCED → PREPARED → ACTIVE；操作错误进入 FAULT。
PREPARED/ACTIVE/FAULT 均需经 STOPPING → QUIESCED，再建立新的 reset 代。

1. 持有 owner 串行化锁调用 begin_stop：拒绝新事务，屏蔽全部来源，失效
   所有 RX。此时未证明 worker/客户端引用已退出，不能 prepare 新代。
2. **释放 owner 锁**，同步全部 IRQ，再 cancel/drain worker，以及该代 CPU
   消息/客户端引用；不得持锁等待一个需要该锁的 worker。
3. 同步完成后重新持锁调用 finish_stop。它清掉 RX 引用并允许下一次 prepare，
   保留 last_generation，拒绝同代/倒退/溢出绕回的代号。
4. 调用者拥有受控 reset、继承消息处置与新代初始化责任；不能只递增一个
   软件数字，就把同一组 pending 当作新代。错误 ACK 是否生效未知时不能
   重置软件对象后重试。finish_stop本身不执行或证明 reset。

尚无 Linux 同步实现；后端无法验证调用者是否真的完成 synchronize_irq、
cancel_work_sync、客户端排空或 reset。这些是未来 adapter 的必须实现条件，
不是可由传入 generation 自动认证的事实。本轮也没有 READY 状态转移。

## 真实 IRQ adapter 的接续任务

- 五个专用 level-high mailbox IRQ 初始不使能；claim与释放必须整体管理。
  hard IRQ只作必要屏蔽与调度，不能拿进程上下文的生命周期 mutex。
- `set_masked` 必须管理 enable/disable depth并幂等，不能每轮调用
  disable_irq_nosync 就叠加一次深度；错误时不能假定实际屏蔽状态。
- 串行化 gate、入队 generation发布和 IRQ/STOP 竞争需由 adapter 的锁策略
  闭合；当前纯串行测试不证明真实并发、GIC或 workqueue行为。
- 必须备齐全部17个 RX pin 的目的缓冲，包括 response 和暂不支持的客户端
  消息；不能只支持 READY0 就开放整组IRQ。队列满需在ACK前拒绝。
- 完整空轮后到重新开中断之间的新消息依赖已核对的 level-high来源再次触发；
  不通过要求ACK后pending永远为0来吞掉新消息。需实机验证该性质。
- check回调应由唯一cfg/vote/clock/reset owner提供，核对本代有效资源；
  检查不是阻止固件改钟的硬件互斥。其检查粒度为每轮前与重新开IRQ前。
- completion MMIO排序依据、STOP/reset寄存器时序、新代READY判定仍待实现。
  此后端不是 IRQ ownership、实际目的缓冲或安全启动的替代品。

## 验证结果

`tools/test_modem_scp_drain.py` 编译实际 protocol、RX、drain C，ASan/UBSan
验证全部预算1–32（预算前最后一轮安静成功与持续pending耗尽）、完整五邮箱
批次中每个 check/pending/copy/completion/ACK错误、未知位、mask/unmask及
再次mask失败、旧代任务、STOP两阶段、迟到消息、RX实例/回调/完整覆盖拒绝、
代号耗尽；ACK后覆盖模拟设备缓冲仍交付原CPU快照。
测试为串行模型，没有验证真实IRQ竞争、总线、worker取消或受控reset。
既有 RX、2048组合 resource、cfg sanitizer 回归通过。

启用 protocol/RX/drain 的 ARM64 Image.gz/modules 构建通过，vmlinux包含
prepare/run/begin_stop/finish_stop；恢复默认配置后 Image.gz/modules通过，
drain/RX符号不存在。DTS未改，defconfig临时修改已恢复。编译器无warning，
默认配置保留已有FW_LOADER/VT重赋值提示；新增C/H strict checkpatch 0/0/0。
本轮没有boot打包、刷写、重启。通过USB仅读取当前设备，仍为
`80e79074de00`，26M pin_verified=1/fault=0、cfg reserved=1、completion关闭。
这不是新后端的实机验收，外设支持范围未扩大。

日志：`/data/src/mainline/mt6893-direct/evidence/scp-drain-offline/`。
结构化结果：[drain validation](evidence/modem-scp-drain-validation.json)。
