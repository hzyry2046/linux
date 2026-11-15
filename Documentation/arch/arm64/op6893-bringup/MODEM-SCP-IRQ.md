<!-- SPDX-License-Identifier: GPL-2.0-only -->
# SCP mailbox IRQ：初始不使能的实际归属

2026-11-15，HEAD `6db0f4606d6e` 工作树，AI 辅助实现及本地源码/API核对。
接续 [目的队列](MODEM-SCP-QUEUE.md)。本阶段是NO_AUTOEN资源申请与异常
containment，尚无正常RX worker、arm操作或硬件接收；验证结果见文末。

## 归属与初始状态

默认关闭 `OP6893_CCCI_SCP_IRQ_RESERVE`，依赖同一内建cfg/SPM owner及CPU
queue。resource owner的probe在cfg预留完成后调用 `ccci_scp_irq_reserve()`，
不创建第二个平台驱动，不发送SMC，不读写SCP/mailbox寄存器。

resource DT节点增加五个interrupts/names，顺序mbox0–4，GIC SPI436–440，
level-high。observer仍只解析同样描述，不申请IRQ，不发生两个action争抢。
默认节点disabled；不改历史LK节点、分区表、保留内存或恢复备份。

申请前先完整验证五个OF specifier：arm,gic-v3、controller available、
三cells、SPI类型0、编号436+i、flags4。之后按name取得Linux IRQ，拒绝重复
虚拟IRQ、错误trigger及不等于468+i的GIC hwirq（SPI编号+32）。要求IRQ chip
没有bus_lock/bus_sync_unlock，避免hard handler持raw spinlock时进入可睡眠
bus操作。这是本板原生GIC约束，不是通用所有irqchip的接入实现。

使用 `devm_request_irq(..., IRQF_NO_AUTOEN, ...)`，不shared、不配置wake，
不调用enable_irq，不提供sysfs arm入口，不启用drain或生成新reset代。
单个堆对象含五个action上下文、work与CPU queue存储；queue始终faulted且
没有RX硬件ops。之前的drain接收后端尚未在这个对象中初始化或运行，避免
以成功桩填充尚缺的MMIO/completion。正常接收仍是接续工作。

## 意外handler与关闭顺序

IRQ动作本应一直禁用；若意外进入handler，不读取pending或payload，也不
清SPM通知/ACK/接受READY。handler只在短raw gate锁内：记录unexpected、
对已申请来源各增加至多一次disable_irq_nosync、未closing时queue fault_work。
重复handler不会叠加disable深度。正常NO_AUTOEN已有一层disable，异常或
cleanup额外增加一层，最后由free_irq撤销action；本阶段不平衡成enable，
因为根本没有重新开启入口。未来可启用adapter须重新设计并测试深度平衡，
不能把这个封闭阶段直接当作正常RX的enable/disable实现。

fault_work仅拿共享owner mutex，失效/擦除CPU queue，记录work_runs；没有
正常消息处理或自动重试。queue_work的排队与closing使用同一gate，STOP
关门后不会再出现新排队。本阶段generation固定未建立，状态报告0；没有
借用继承pending来生成READY，也不以意外handler建立新代。

清理顺序：

1. 不持owner mutex，gate内置closing并contain已申请来源。
2. 释放gate，逐个synchronize_irq，随后cancel_work_sync。
3. 再持owner mutex失效/擦除CPU queue。此时worker已退出，避免持锁等待
   一个需要同一锁的worker。
4. devm stop action注册在所有IRQ action之后，LIFO teardown时先完成上述
   quiescence，再devm_free_irq，最后释放CPU对象。部分申请失败时先显式stop，
   再让probe失败的devres teardown释放已申请action；action注册失败则由
   devm_add_action_or_reset立即stop。

内建owner不开放unbind。此STOP用于devres失败/清理，不执行SCP reset，
没有客户端事件需要排空，也未释放boot-lifetime SPM pin。后续有真实RX时
还需把drain/队列/客户端引用和reset generation纳入同一关闭顺序。

## 只读状态

`/sys/devices/platform/10724000.scp-resource-hold/irq` 报告申请数、
GIC mask读取数、unexpected/work_runs/closing，以及arm_supported=0、
generation=0、queue_active=0、ready_known=0。

GIC mask通过IRQ API `irq_get_irqchip_state(... MASKED ...)` 获取；本树
`drivers/irqchip/irq-gic-v3.c:gic_irq_get_irqchip_state()` 查询
GICD_ISENABLER，不读SCP/mailbox寄存器，不读取/清除IRQ pending。
查询错误直接返回错误，masked不足5时显示实际值，不编造成功。状态各部分
分别加锁采集，不是与固件/整个GIC原子同步的快照，也不是中断送达测试。

## 验证与接续

`tools/test_modem_scp_irq.py` 编译实际IRQ owner C，ASan/UBSan模型覆盖五个
NO_AUTOEN申请、全部OF spec错误、映射/trigger/hwirq/bus-lock拒绝、每个
部分申请失败、devres action失败、重复handler的disable上界、worker、
closing后插入迟到handler不再排队、同步等待在owner锁外以及GIC查询错误。
模型不是GIC或Linux IRQ并发仿真；注入意外handler不等于实机中断触发验收。
新增C/H及resource owner全文件strict checkpatch为0/0/0；既有queue/drain/
RX/resource/cfg回归通过。

实验boot镜像 `49092bac2836`，release `7.3.0-op6893-d1-49092bac2836+`。
启用/默认 Image.gz、modules、board/merged DTB 定向 schema 均通过，默认
DTS/config 已恢复，默认节点 disabled 且不包含实验 IRQ/resource/queue/drain
符号。既有 defconfig 的 FW_LOADER/VT 重赋值提示保留，无新增编译器告警。

实机已启动该镜像，boot 分区回读 SHA256 与镜像一致。五个实际 action 对应
GIC hwirq 468–472，所有 CPU 中断计数为0；USB 三轮与 Wi-Fi 三轮查询均为
requested=5、gic_masked=5、unexpected=0、work_runs=0、closing=0。
arm_supported/generation/queue_active/ready_known 均为0。没有触发软件IRQ
或清pending来制造测试，因此仅验收申请及屏蔽，不代表消息接收或中断送达。

先只读核对资源，再显式一次26M pin：SCP user1、mask=0x02、pin_verified=1、
fault=0；CCF引用3/3、26 MHz。cfg预留4096字节、寄存器读写0、completion
关闭，五组pending/unknown仍0，core0/header稳定。observer自身的
irq_requested=0仅描述它未申请IRQ；五个action由resource owner持有。
USB/Wi-Fi SSH、8核、UFS三LUN只读、cache ext4 ro,norecovery、lower squashfs
只读及overlay root回归通过；限定故障关键字扫描无匹配。

结构化结果见 [实测记录](evidence/modem-scp-irq-runtime.json)，原始构建及
运行记录在 `/data/src/mainline/mt6893-direct/evidence/scp-irq-live`。设备保留
本镜像，未修改分区表或恢复备份，未启动SCP/MD或建立READY。

接续：在唯一owner内提供真实RX MMIO/completion与资源check，初始化全部
queue-backed RX和drain；实现可启用IRQ/worker的锁与深度平衡、真实入队
代号和客户端消费，再闭合受控reset/旧消息隔离/本代READY。没有这些条件，
不能因为IRQ申请成功就打开接收。


2026-11-15 接续：真实寄存器操作的默认关闭后端及 non-posted 映射 helper
已完成离线构建/模型验证，见 [MMIO准备](MODEM-SCP-MMIO.md)。尚未接入该IRQ
owner，当前五IRQ始终屏蔽的实测边界不变。
