<!-- SPDX-License-Identifier: GPL-2.0-only -->
# SCP core0/core1/TCM：唯一 owner 的静默映射

2026-11-15，HEAD `6db0f4606d6e` 工作树，接续
[reset/恢复审计](MODEM-SCP-RESET-RESTORE.md)。Codex 根据“继续推进”任务辅助
实现、源码对照、测试及实机验证；尚需人工审查，不添加 AI Signed-off-by。

本轮已将 core0/core1/TCM 的资源预留和映射接入现有 boot-lifetime owner。
设备保留测试主线 `db337399ee04`。本轮没有读取这三个新窗口，不能将映射成功
解释为 core1/TCM 总线可达、双核已停止、reset 生效或 SCP/基带可用。

## 资源归属和访问属性

Android 4.19 `kernel_oddo_mt6893/arch/arm64/boot/dts/mediatek/mt6893.dts`
及已可用 6.6 `kernel_device_modules-6.6/arch/arm64/boot/dts/mediatek/mt6893.dtsi`
的 SCP reg 表一致：

|资源|起点|大小|本轮操作|
|---|---|---|---|
|core0 配置|0x10730000|0x1000|独占预留及映射|
|core1 配置|0x10740000|0x1000|独占预留及映射|
|完整 TCM|0x10500000|0x180000|独占预留及映射|

新增默认关闭 `OP6893_CCCI_SCP_CORE_TCM_RESERVE`，依赖 dormant receive
reservation，且排除 `CORE0_OBSERVE`，间接关闭其 TCM/pending 读取选项。
AP 侧 TOPCK、bootstrap 和保留区 bookkeeping observer 仍可使用；它不再
映射 core0 或 TCM header。旧 `core0` 属性保留但返回 `EOPNOTSUPP`，
`header` 和 `pending` 属性不生成。历史只读实验配置在新选项关闭时保持原行为。

实现位于 `ccci-scp-resource-hold.c`：按名称检查全部三个资源的精确几何，
全部合法后才开始预留。复制资源描述并设置 `IORESOURCE_MEM_NONPOSTED`，
不修改 OF 的共享描述；使用与现有 cfg/mailbox 一致的 Device-nGnRnE 映射，
不创建 cached RAM 别名。TCM 目前没有复制或普通内存访问调用，后续搬运仍须
单独审查权限、对齐、顺序与屏障，不能把映射指针当普通 RAM。

三个 `devm_ioremap_resource()` 全成功才向 owner 发布指针。缺失/错误资源、
已有 claim 冲突、映射失败均使 probe 失败，由 devres 回收此前取得的窗口；
不会继续安装 receive IRQ 或发布 sysfs。与旧 observer 的互斥同时通过 Kconfig
和资源独占 claim 保障。本轮没有引入可开启读写的接口。

`core_tcm` sysfs 在 owner mutex 下只报告映射状态、总字节数和静态零 I/O。
零值来自当前没有访问调用的实现，并非硬件跟踪器统计。`reset_generation`
继续为0，无 receive start caller，无 reset/restore/READY 接口。

DT 资源表在 cfg 和五个 mailbox 后追加 core0/core1/TCM，节点默认 disabled。
binding 接受旧六项或完整九项，拒绝七/八项以及 reg 与 names 数量不一致。
两个 DT 节点中可以描述同一物理区域，但本实验只有 resource owner 实际取得
这些窗口；AP observer 不创建第二份映射。

## 离线验证

- `tools/test_modem_scp_mmio_owner.py` 提取并编译实际 owner/probe/预留和状态
  函数，四个配置分支在 ASan/UBSan 下通过。逐一测试三个资源缺失、地址/
  尺寸错误、各位置映射失败及 `ENOMEM/EBUSY/EINVAL/EIO`；验证完整集合才
  发布、失败不安装 receive、共享资源描述不变、原有 IRQ owner 互斥。
- 既有 core0、TCM、resource、MMIO、receive 和 restore 模型回归通过。
  主机模型不替代硬件总线属性、时序或停止语义验证。
- 实际 olddefconfig 确认同时请求旧 reader 与新选项时新选项不生效；移除旧
  core0 后新选项可启用，TCM/pending reader 关闭。
- 启用 Image.gz/modules 和恢复默认 Image.gz/modules 通过；默认无新增
  core_tcm 状态函数符号，构建输出配置已恢复默认。strict checkpatch 0/0/0。
- binding、启用 board/merged DTB 和默认 board DTB 验证通过；另以 DTB
  fixture 确认旧六项可用，七/八项及六/九混合数量被 schema 拒绝。

## 实机验收

测试镜像 `/data/src/mainline/mt6893-direct/dist/db337399ee04/boot.img`：

- release `7.3.0-op6893-d1-db337399ee04+`；boot SHA256 为
  `3bd0ce54f7371c25ad98234df31320e83b534b5ee934007792155ae7b293bfce`，
  设备 boot 分区回读一致。提前排队 boot-only 刷写和 reboot，再按用户确认
  执行 sync + SysRq reboot，由用户拦截 fastboot；不使用 fastboot boot。
- `/proc/iomem` 确认完整 TCM、core0/core1、cfg 和五个 mailbox 共九块
  全归 `10724000.scp-resource-hold`；没有 observer 子 claim。
- `core_tcm` mapped=3、bytes=1581056；寄存器/TCM 读写0。原六页 MMIO
  读写0、prepared=0、generation=0；其 fault=1 是未 prepare 的初始关闭状态。
- 五个 `op6893-scp-rx` action，hwirq468–472 均 masked，所有CPU计数0；
  worker/queued/events/generation 均0，没有启动 receive。
- 首次资源查询 attempted=0、SCP absent，说明没有 probe 请求。随后一次显式
  `26m` pin：SCP user1、mask0x02、pin_verified=1、fault=0；没有 release/retry。
- USB/Wi-Fi 各三轮均通过；CCF bootstrap 引用3/3、26MHz，八核在线，UFS
  sda/b/c 均RO；cache ext4 ro,norecovery，lower squashfs ro，根为 overlay。
- 旧 core0 入口访问失败、header/pending 属性不存在；故障关键词扫描0命中。
  debugfs 初始未挂载，挂载后读取 CCF bookkeeping，不读 SCP MMIO。

实机原始记录、配置、schema fixture、构建/刷写日志在
`/data/src/mainline/mt6893-direct/evidence/scp-core-tcm-reserve/`；
[结构化验收](evidence/modem-scp-core-tcm-owner-runtime.json)。未改变分区表、
未更新 ACK 备份，没有导出固件/TCM payload、设备身份或校准数据。

## 接续 TODO

1. 将原有 core0/精确68/72-byte header 的受限读取迁到同一 owner mutex，
   独立验证 core1 的读取偏移、前后条件和超时策略。先审查只读 allowlist，
   不重新启用 legacy observer 或建立映射别名。映射验收不算读取验收。
2. 在两核停止证据和 mailbox/GIC/CPU 队列旧消息隔离契约成立后，再设计
   assert-only 操作；reset alias/WFI 读回均不自动证明 CPU/DMA 全停。
3. 继续确认 LK loader/firmware/DRAM backup 来源、有效期和一致性。布局
   planner 只证明几何；没有这些证据不能恢复复制或发布新 generation。
4. 之后才衔接 receive preparation、正常 IRQ、core0 release、新代 READY，
   最后推进 SCP↔CCCI/MD 启动。当前仍未启用 IRQ 或启动 SCP/MD。


### 后续进度：R5.21

双核受限寄存器与精确header读取已迁入统一owner，并在 `cebf84a7d29e` 实机
验收，详见 [统一owner只读观测](MODEM-SCP-OWNER-OBSERVE.md)。新增独立默认
关闭选项；本文件R5.20镜像仍为纯映射实验，不能将后续读数归入其验证范围。
