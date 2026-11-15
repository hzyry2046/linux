<!-- SPDX-License-Identifier: GPL-2.0-only -->
# SCP RX MMIO 后端：non-posted 映射与完成顺序

2026-11-15，HEAD `6db0f4606d6e` 工作树，AI 辅助本地源码分析、实现及测试。
接续 [IRQ 归属](MODEM-SCP-IRQ.md)。本轮只做离线实现和构建，没有刷写、
重启或操作真实 mailbox。设备仍运行 `49092bac2836`，五个 IRQ 保持 masked。

## 参考代码实际做了什么

同板 Android 4.19：

- `drivers/misc/mediatek/scp/rv/scp_awake.c:scp_clr_spm_reg()` 用普通
  `writel(1, SCP_TO_SPM_REG)`，地址为 cfg+0x94。
- `drivers/soc/mediatek/mtk-mbox.c:mtk_mbox_isr()` 在复制消息后调用 post
  callback，再由 `mtk_mbox_clr_irq()` 普通 writel 本批精确 mask。
- 没有独立 recv-status 资源时，`mtk_mbox_read_recv_irq()` 读同一 CLR 地址。
- `drivers/misc/mediatek/include/mt-plat/sync_write.h` 虽定义 raw write+
  dsb(sy) 宏，上述 completion/ACK 路径没有使用它。

已可用的同板6.6采用相同普通 writel 顺序，另有此前已核对的 AP cfg/GPR7
可选路径；本机历史 DT 未启用这两个选项。qqcandy MT6895 同样写 cfg+0x94，
不作为本机总线行为或地址的独立证明。不能仅因源文件包含同步写宏，就把
普通 writel 解释成该宏；也不能用厂商代码可用证明任意 flush read 安全。

## 本轮选择的映射及排序

新增默认关闭的 `OP6893_CCCI_SCP_MMIO`，依赖 RX、HAS_IOMEM 和
ARM64_4K_PAGES。`ccci-scp-mmio.{c,h}` 是没有 platform caller 的后端。

`ccci_scp_mmio_reserve()` 要求未来 owner 提供六个完整4 KiB资源：

|资源名|起始地址|大小|
|---|---|---|
|scp-cfg|0x10724000|0x1000|
|mbox0|0x107fb000|0x1000|
|mbox1|0x107fc000|0x1000|
|mbox2|0x107fd000|0x1000|
|mbox3|0x107fe000|0x1000|
|mbox4|0x107ff000|0x1000|

先校验全部资源和不支持的替代协议属性，再逐个申请并映射。在资源的本地
副本设置 IORESOURCE_MEM_NONPOSTED，不修改 OF 共享资源描述。根据本树
`lib/devres.c`，devm_ioremap_resource 会据此调用 ioremap_np，失败直接返回，
没有退回普通 ioremap。`arch/arm64/include/asm/io.h` 将该 API 映射为
Device-nGnRnE。完整页归属和4 KiB页配置限制用于避免相邻子窗口使用不同
页属性；必须替换当前 cfg/pending 的映射，不能与它们同时映射相同物理页。
申请失败的 caller 必须终止 probe，让 devres 回收部分资源，不能继续使用。
这不能阻止绕过资源管理器的第三方映射，接线前还要审计实际所有者。

具体事务继续由既有 RX/queue 驱动：

1. `pending` 用 readl 读取 mailbox+0x10c。
2. `read_words` 在64-word边界内逐个 readl，再 put_unaligned_le32 保存 wire
   字节；不使用 memcpy_fromio，不读填充，不改变 wire 字节序。
3. 所有 payload 已复制后，post 向 cfg+0x94 writel(1)，随后 mb()。
4. ACK 只向该 mailbox+0x10c writel 精确 mask，随后 mb()。
5. RX/queue 才发布已保存的 CPU 快照。

此处 non-posted 映射承担禁止 early write acknowledgement 的映射语义；
mb() 在本 ARM64 树展开为 dsb(sy)，承担 CPU 完成/排序屏障。不是在普通
posted 映射后单加通用屏障来声称总线已 flush。没有读取未核实的 cfg 清位
寄存器，也没有依赖跨窗口 dummy read。ACK 后不读回或要求 pending 为0，
允许下一条消息已到达。源码依据另见 `Documentation/driver-api/device-io.rst`
的 ioremap_np 小节和 `Documentation/driver-api/io_ordering.rst`。

这是准备上机验证的实现选择，不能证明本机 fabric 的实际应答位置、SPM
逻辑已清位或固件已消费数据；ARM64 映射及屏障也不能替代协议确认。普通
readl/writel 没有可返回的总线故障状态，SError 不会被转换为 callback errno。
本轮尚未在硬件上建立这六个映射或执行任何寄存器操作。

## 生命周期及故障边界

prepare 无 I/O，验证完整 RX 布局后记录新的非零 generation、五组 known
mask 和 owner 提供的 prerequisite callback。它没有建立硬件 reset 代际的
能力；调用者必须先同步 IRQ/work/客户端、执行真实 reset/旧消息隔离。
活动时拒绝再次 prepare；失效后仍拒绝小于等于上次的代号。递增数字并不
提供重试不确定 ACK 的权限。

所有调用使用唯一 owner 的串行化。每个硬件 callback 先检查该代的
clock/vote/lifetime 条件；检查失败使整个 MMIO 对象 sticky fault，全部端口
拒绝后续访问，不自动重试。检查不能依赖 READY，否则 READY 自身无法接收。
连续 word 读取中不逐字重新查询资源，也不声称与固件状态全局原子同步。

MMIO ops 的 deliver 为 NULL，只供 queue_init 使用，不能直接当作 RX 的
目的地。queue/drain 负责整批空间、快照、未知位拒绝和所有 RX 失效；周边
排空故障必须同时 invalidate queue 和 MMIO。端口 context 会跨 prepare
复用，本身不是 generation token：owner/drain 必须先拒绝旧代排队工作。
后端没有 IRQ 开启、清全部 pending、reset/awake、客户端通知或 READY 状态。

## 验证与接续

`tools/test_modem_scp_mmio.py` 编译真实 protocol/RX/queue/drain/MMIO C，
ASan/UBSan 模型覆盖：全部资源在映射前校验、每个部分映射失败/冲突、替代
协议拒绝、原资源属性不变、六个 non-posted 页申请、初始化无访问、精确
32-bit wire 复制和不对齐 CPU 输出、64-word边界、post/barrier/ACK/barrier
顺序、ACK破坏原设备缓冲仍交付正确快照、ACK时新消息到达、各操作前资源
检查失败、未知位/队列不足不写 completion、失效与代号拒绝、完整空扫及
有限预算故障。模型不能证明 ARM64/总线或 Linux 并发；没有注入真实中断。

启用/默认 ARM64 Image.gz/modules 构建通过，无新增编译器告警；默认
.config 与原始保存内容完全一致。启用 vmlinux 包含 MMIO API，默认 vmlinux
没有这些符号。post/ACK 的 ARM64 对象反汇编均保留 dsb sy。新增 C/H 全文件
strict checkpatch 为0/0/0；IRQ/queue/drain/RX/cfg/resource 回归通过。已有
FW_LOADER/VT defconfig 重赋值提示保留。没有改动 DTS/binding 或打包新 boot。
日志在 `/data/src/mainline/mt6893-direct/evidence/scp-mmio-offline`，最终结果
见 [验证数据](evidence/modem-scp-mmio-validation.json)。
此选项没有 platform caller，当前 DT/binding 仍只有 cfg 资源；启用编译也
不会自动执行 reserve/prepare/任何 MMIO。设备保留原 IRQ 测试镜像，USB
只读回归仍为五个 masked IRQ、26M pin_verified=1、cfg寄存器读写0。

接续任务：

1. 扩展 owner 的 DT/binding 资源，替换原 cfg 映射并关闭 pending observer，
   在唯一 owner 中连接六个 non-posted 资源；先验证资源独占及映射，不消费消息。
2. 接 owner 真实 prerequisite callback、全部 queue/RX、drain 和客户端失效；
   重做可开启 IRQ 的锁、disable 深度平衡、入队时 generation 及 STOP 同步。
3. 实现真实受控 reset 和旧消息隔离后，才 prepare 本代 RX、开启接收并验证
   READY0；继承消息或空 pending 都不提供本代 READY。之后才推进 SCP/MD 启动。


2026-11-15 后续：已新增唯一 owner 的独立映射 opt-in、完整 DT/binding
资源和 pending observer 互斥，见 [MMIO owner 接入](MODEM-SCP-MMIO-OWNER.md)。
本篇无 caller 的描述记录最初离线阶段；新路径仅调用 reserve，尚无 prepare/RX。
